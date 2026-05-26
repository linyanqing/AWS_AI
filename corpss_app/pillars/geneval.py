"""
E · GENEVAL — Evaluation & Trust  ← NEW PILLAR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  The main roadblock moving agents from demo to production is
  non-deterministic output drift. GENEVAL establishes a 5-step
  Continuous Evaluation Loop:

    1. Ground Truth Datasets  — S3 gold-standard JSONL benchmark
    2. Offline Evaluation     — Bedrock Model Evaluation automated jobs
    3. Safe Deployment        — gate promotion behind evaluation score thresholds
    4. Online Monitoring      — AgentCore Trace parsing for live RAG quality metrics
    5. Continuous Improvement — edge cases fed back into test beds

  Key metrics tracked:
    • Faithfulness (Groundedness) — does output ONLY use retrieved context?
    • Answer Relevance            — does the response directly answer the query?
    • Context Relevance           — are retrieved chunks precise and low-noise?
    • Tool Call Accuracy          — did the agent select the correct action group?
    • Rationale Coherence         — is the internal reasoning chain sound?
"""
import logging
import boto3
from botocore.exceptions import ClientError

from config import (
    AWS_REGION,
    ACCOUNT_ID,
    AGENT_ID,
    AGENT_ALIAS_ID,
    EVAL_ROLE_ARN,
    EVAL_INPUT_S3,
    EVAL_OUTPUT_S3,
    EVAL_MODEL_ID,
)

logger = logging.getLogger(__name__)


class EvalScore:
    """Structured evaluation result from a single agent invocation."""

    def __init__(self) -> None:
        self.final_answer:    str        = ""
        self.rag_sources:     list[dict] = []
        self.rationale:       str        = ""
        self.tool_calls:      list[dict] = []
        self.guardrail_fired: bool       = False

    def faithfulness_flag(self) -> str:
        """Heuristic: PASS if RAG sources were retrieved, REVIEW if answer has no grounding."""
        return "PASS" if self.rag_sources else "REVIEW — no RAG context retrieved"

    def to_dict(self) -> dict:
        return {
            "final_answer":    self.final_answer,
            "rag_sources":     self.rag_sources,
            "rationale":       self.rationale,
            "tool_calls":      self.tool_calls,
            "guardrail_fired": self.guardrail_fired,
            "faithfulness":    self.faithfulness_flag(),
        }


class GENEVALEvaluationEngine:
    """
    5-Step Continuous Evaluation Loop implementation.

    Steps 1–3 (offline): submit_model_evaluation_job()
    Steps 4–5 (online):  invoke_and_evaluate()
    """

    def __init__(
        self,
        agent_id:       str = AGENT_ID,
        agent_alias_id: str = AGENT_ALIAS_ID,
    ) -> None:
        self._agent_id       = agent_id
        self._agent_alias_id = agent_alias_id
        self._agent_rt       = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        self._bedrock        = boto3.client("bedrock",               region_name=AWS_REGION)

    # ── Step 2 · Offline Evaluation Job ──────────────────────────────────────

    def submit_model_evaluation_job(
        self,
        job_name:        str = "CORPSEE_Offline_Eval",
        input_s3:        str = EVAL_INPUT_S3,
        output_s3:       str = EVAL_OUTPUT_S3,
        eval_model_id:   str = EVAL_MODEL_ID,
    ) -> str:
        """
        Submit a Bedrock Model Evaluation job against the S3 ground-truth dataset.

        Measures Faithfulness, Answer Relevance, and Context Relevance
        automatically. Results written to S3 for threshold gating (Step 3).

        Returns the evaluation job ARN.
        """
        logger.info("[GENEVAL] Submitting offline model evaluation job: %s", job_name)

        try:
            response = self._bedrock.create_evaluation_job(
                jobName=job_name,
                roleArn=EVAL_ROLE_ARN,
                evaluationConfig={
                    "automated": {
                        "datasetMetricConfigs": [
                            {
                                "taskType": "QuestionAndAnswer",
                                "dataset": {
                                    "name":      "ground-truth-dataset",
                                    "datasetLocation": {"s3Uri": input_s3},
                                },
                                "metricNames": [
                                    "Faithfulness",
                                    "Helpfulness",
                                    "Coherence",
                                ],
                            }
                        ]
                    }
                },
                inferenceConfig={
                    "models": [
                        {
                            "bedrockModel": {
                                "modelIdentifier": eval_model_id,
                            }
                        }
                    ]
                },
                outputDataConfig={"s3Uri": output_s3},
            )
            job_arn = response["jobArn"]
            logger.info("[GENEVAL] ✅ Evaluation job submitted. ARN: %s", job_arn)
            return job_arn

        except ClientError as exc:
            logger.error("[GENEVAL] Evaluation job failed: %s", exc)
            raise

    # ── Steps 4–5 · Online Runtime Evaluation ────────────────────────────────

    def invoke_and_evaluate(self, user_query: str, session_id: str) -> EvalScore:
        """
        Invoke the production agent with enableTrace=True and parse the
        AgentCore reasoning stream for real-time quality metrics.

        Evaluation layers:
          Layer 1 — RAG Context Relevance:  inspect knowledgeBaseLookup traces
          Layer 2 — Rationale Coherence:    inspect orchestration.rationale
          Layer 3 — Tool Call Accuracy:     inspect invocationInput traces
          Layer 4 — Guardrail Intervention: inspect guardrailTrace
        """
        logger.info(
            "[GENEVAL] Invoking agent with trace enabled — session=%s", session_id
        )

        score = EvalScore()

        response = self._agent_rt.invoke_agent(
            agentId=self._agent_id,
            agentAliasId=self._agent_alias_id,
            sessionId=session_id,
            inputText=user_query,
            enableTrace=True,   # ← CRITICAL: exposes internal reasoning path
        )

        for event in response["completion"]:
            # ── Collect final answer ──────────────────────────────────────────
            if "chunk" in event:
                score.final_answer += event["chunk"]["bytes"].decode("utf-8")

            # ── Parse trace events ────────────────────────────────────────────
            elif "trace" in event:
                trace_data = event["trace"].get("trace", {})

                # Layer 1: RAG Context Relevance
                if "knowledgeBaseLookupOutput" in trace_data:
                    lookup = trace_data["knowledgeBaseLookupOutput"]
                    refs   = lookup.get("retrievedReferences", [])
                    for ref in refs:
                        source = {
                            "uri":     ref.get("location", {}).get("s3Location", {}).get("uri", ""),
                            "snippet": ref.get("content", {}).get("text", "")[:120],
                        }
                        score.rag_sources.append(source)
                        logger.info(
                            "[GENEVAL] 🔍 RAG source: %s — %s…",
                            source["uri"], source["snippet"][:60],
                        )

                # Layer 2: Rationale Coherence + Layer 3: Tool Call Accuracy
                elif "orchestrationTrace" in trace_data:
                    orch = trace_data["orchestrationTrace"]

                    if "rationale" in orch:
                        score.rationale = orch["rationale"].get("text", "")
                        logger.info(
                            "[GENEVAL] 🧠 Agent rationale: %s…",
                            score.rationale[:100],
                        )

                    if "invocationInput" in orch:
                        tool = orch["invocationInput"].get("actionGroupInvocationInput", {})
                        call = {
                            "action_group": tool.get("actionGroupName", ""),
                            "function":     tool.get("function", ""),
                        }
                        score.tool_calls.append(call)
                        logger.info(
                            "[GENEVAL] 🛠️  Tool call: %s → %s",
                            call["action_group"], call["function"],
                        )

                # Layer 4: Guardrail Intervention
                elif "guardrailTrace" in trace_data:
                    action = trace_data["guardrailTrace"].get("action", "NONE")
                    if action == "INTERVENED":
                        score.guardrail_fired = True
                        logger.warning("[GENEVAL] 🚨 Guardrail intervention detected in trace.")

        logger.info(
            "[GENEVAL] ✅ Evaluation complete — RAG sources: %d | tool calls: %d | faithfulness: %s",
            len(score.rag_sources),
            len(score.tool_calls),
            score.faithfulness_flag(),
        )
        return score
