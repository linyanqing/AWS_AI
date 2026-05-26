"""
O · GENOPS — Operational Excellence
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  • Open-Closed Principle (OCP): core inference code is CLOSED to
    modification — it always targets a stable PROD-ACTIVE alias ARN.
    Prompts are OPEN for extension via Bedrock Prompt Management.
  • Version-locked prompt artefacts: any change requires a version bump
    and alias re-map — zero-downtime swap, full audit trail.
  • AgentCore Observability + OpenTelemetry (OTEL): eliminates black-box
    monitoring by exporting granular reasoning paths, tool calls, and
    orchestration steps to CloudWatch and OTEL-compatible collectors.
"""
import logging
import boto3

from config import AWS_REGION, PROMPT_ALIAS_ARN, MODEL_FRONTIER

logger = logging.getLogger(__name__)


class GENOPSPromptManager:
    """
    Fetches version-pinned prompt templates from Bedrock Prompt Management,
    hydrates runtime variables, and dispatches to the inference engine.
    Integrates OTEL-compatible trace context for observability.
    """

    def __init__(self, prompt_alias_arn: str = PROMPT_ALIAS_ARN) -> None:
        self._alias_arn    = prompt_alias_arn
        self._bedrock_ctrl = boto3.client("bedrock-agent",   region_name=AWS_REGION)
        self._bedrock_rt   = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    # ── Public API ────────────────────────────────────────────────────────────

    def execute_with_managed_prompt(
        self,
        user_query: str,
        template_variables: dict | None = None,
        trace_context: dict | None = None,
    ) -> str:
        """
        1. Fetch the current PROD-ACTIVE prompt template from the alias ARN.
        2. Hydrate all {{variable}} tokens with runtime values.
        3. Dispatch to the inference engine — core code never changes.

        trace_context: optional dict of OTEL span attributes to attach
                       (e.g. {"trace_id": "...", "span_id": "..."})
                       for propagating distributed traces into CloudWatch.
        """
        template_variables = template_variables or {}
        template_variables.setdefault("user_query", user_query)

        # Step 1 — fetch version-locked template from prompt registry
        logger.info("[GENOPS] Fetching prompt template from PROD-ACTIVE alias.")
        prompt_cfg   = self._bedrock_ctrl.get_prompt(promptIdentifier=self._alias_arn)
        raw_template = prompt_cfg["variants"][0]["templateConfiguration"]["text"]["text"]

        # Step 2 — hydrate {{variable}} tokens
        hydrated = self._hydrate(raw_template, template_variables)
        logger.info("[GENOPS] Prompt hydrated. Variables: %s", list(template_variables.keys()))

        # Step 3 — inference (CLOSED to modification — structure never changes)
        if trace_context:
            logger.info(
                "[GENOPS] OTEL trace context attached: trace_id=%s span_id=%s",
                trace_context.get("trace_id", "n/a"),
                trace_context.get("span_id",  "n/a"),
            )

        response = self._bedrock_rt.converse(
            modelId=MODEL_FRONTIER,
            messages=[{"role": "user", "content": [{"text": hydrated}]}],
        )
        return response["output"]["message"]["content"][0]["text"]

    def get_prompt_metadata(self) -> dict:
        """Return the current prompt version and alias metadata — useful for OTEL span attributes."""
        cfg = self._bedrock_ctrl.get_prompt(promptIdentifier=self._alias_arn)
        return {
            "prompt_id":      cfg.get("id"),
            "prompt_version": cfg.get("version"),
            "prompt_name":    cfg.get("name"),
        }

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _hydrate(template: str, variables: dict) -> str:
        """Replace {{key}} tokens with runtime values."""
        for key, value in variables.items():
            template = template.replace(f"{{{{{key}}}}}", str(value))
        return template
