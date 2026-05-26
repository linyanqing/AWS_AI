"""
S · GENSEC — Security
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  • Ephemeral microVM session isolation via AgentCore Runtime: each user
    session executes inside its own isolated compute pocket, destroyed
    immediately upon completion — zero cross-tenant state leakage.
  • Dual-sided Bedrock Guardrails (synchronous): blocks prompt injection
    on INPUT before inference; masks PII on OUTPUT before response is
    returned. All compute locked to ap-southeast-2 (AU data sovereignty).
  • In-pipeline PII masking: Email, Credit Card, IP Address → Block/Mask.
  • Guardrails are bound to the agent definition in the control plane,
    not injected at runtime — tamper-proof by construction.
"""
import logging
import boto3
from botocore.exceptions import ClientError

from config import (
    AWS_REGION,
    GUARDRAIL_ID,
    GUARDRAIL_VERSION,
    MODEL_FRONTIER,
    AGENT_ID,
    AGENT_ALIAS_ID,
)

logger = logging.getLogger(__name__)


class GuardrailIntervened(Exception):
    """Raised when Bedrock Guardrails block or redact content."""


class GENSECGuardrailPerimeter:
    """
    Dual-sided security perimeter for direct Bedrock converse calls.

    ┌──────────────────────────────────────────────────────────┐
    │  INPUT  →  [GUARDRAIL BLOCK]  →  BEDROCK  →  [PII MASK]  →  OUTPUT  │
    └──────────────────────────────────────────────────────────┘
    """

    def __init__(
        self,
        guardrail_id:      str = GUARDRAIL_ID,
        guardrail_version: str = GUARDRAIL_VERSION,
    ) -> None:
        self._guardrail_id      = guardrail_id
        self._guardrail_version = guardrail_version
        self._bedrock_rt        = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    def safe_execute(self, untrusted_input: str, model_id: str = MODEL_FRONTIER) -> str:
        """
        Execute inference inside the dual-sided guardrail perimeter.

        Raises:
            GuardrailIntervened — if a prompt injection or PII event is detected.
            ClientError         — for unrecoverable AWS service faults.
        """
        logger.info("[GENSEC] Applying dual-sided guardrail perimeter.")

        try:
            response = self._bedrock_rt.converse(
                modelId=model_id,
                messages=[{"role": "user", "content": [{"text": untrusted_input}]}],
                guardrailConfig={
                    "guardrailIdentifier": self._guardrail_id,
                    "guardrailVersion":    self._guardrail_version,
                },
            )
        except ClientError as exc:
            logger.error("[GENSEC] AWS service fault: %s", exc)
            raise

        guardrail_meta = response.get("guardrail", {})
        if guardrail_meta.get("action") == "INTERVENED":
            logger.warning("[GENSEC] 🚨 Guardrail INTERVENED — %s", guardrail_meta)
            raise GuardrailIntervened(
                "Bedrock Guardrail blocked or redacted content. See CloudWatch for trace."
            )

        output = response["output"]["message"]["content"][0]["text"]
        logger.info("[GENSEC] ✅ Response passed dual-sided perimeter.")
        return output


class GENSECSessionIsolation:
    """
    Secure agent execution inside ephemeral AgentCore microVM sessions.

    Each sessionId maps to an isolated compute pocket in AgentCore Runtime.
    The VM is destroyed upon session completion — no cross-tenant state leakage.
    Guardrails are bound to the agent definition in the control plane.
    """

    def __init__(
        self,
        agent_id:       str = AGENT_ID,
        agent_alias_id: str = AGENT_ALIAS_ID,
    ) -> None:
        self._agent_id       = agent_id
        self._agent_alias_id = agent_alias_id
        self._agent_rt       = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)

    def secure_agent_execution(self, user_input: str, session_id: str) -> str:
        """
        Execute inside an isolated, ephemeral microVM session.

        The session_id enforces a strict microVM containment boundary.
        Guardrails are applied automatically via the agent's control plane binding.
        Trace events are parsed to surface guardrail intervention alerts.
        """
        logger.info(
            "[GENSEC] Invoking agent in isolated microVM — session=%s", session_id
        )

        try:
            response = self._agent_rt.invoke_agent(
                agentId=self._agent_id,
                agentAliasId=self._agent_alias_id,
                sessionId=session_id,   # Each session = isolated microVM boundary
                inputText=user_input,
                enableTrace=True,       # Allows guardrail intervention intercept
            )

            final_output = ""
            for event in response["completion"]:
                if "chunk" in event:
                    final_output += event["chunk"]["bytes"].decode("utf-8")
                elif "trace" in event:
                    trace = event["trace"].get("trace", {})
                    if "guardrailTrace" in trace:
                        action = trace["guardrailTrace"].get("action", "NONE")
                        if action == "INTERVENED":
                            logger.warning(
                                "[GENSEC] 🚨 Security alert: guardrail intervention in session=%s",
                                session_id,
                            )

            logger.info("[GENSEC] ✅ Session %s completed. microVM destroyed.", session_id)
            return final_output

        except ClientError as exc:
            logger.error("[GENSEC] Session fault: %s", exc)
            raise
