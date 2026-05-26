"""
CORPSEE Orchestrator — 7-Pillar GenAI Well-Architected Framework
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Ties all 7 CORPSEE pillars into a single, coherent request pipeline.

                    ┌─────────────────────────────────────────────────┐
                    │              CORPSEE PIPELINE                    │
                    │                                                  │
     User Query ──► │  [S·GENSEC]   Guardrail input scan              │
                    │       ↓                                          │
                    │  [E·GENSUST]  Intent classification              │
                    │       ↓ SIMPLE ──────────────────────────────►  │
                    │       ↓ COMPLEX                                  │
                    │  [O·GENOPS]   Fetch versioned prompt alias       │
                    │       ↓                                          │
                    │  [R·GENREL]   Circuit breaker inference          │
                    │       ↓                                          │
                    │  [P·GENPERF]  AgentCore Harness / stream        │
                    │       ↓                                          │
                    │  [R·GENREL]   Fan-out event to worker queues     │
                    │       ↓                                          │
                    │  [E·GENEVAL]  Runtime trace evaluation           │
                    │       ↓                                          │
     Response  ◄──  │  Final payload                                   │
                    │                                                  │
     Batch Mode ──► │  [C·GENCOST]  Async batch + prompt caching      │
     Eval Mode  ──► │  [E·GENEVAL]  Offline evaluation job            │
                    └─────────────────────────────────────────────────┘

Pillar map (CORPSEE):
  C – GENCOST  · Cost Optimisation     (batch, prompt caching, 1% trace)
  O – GENOPS   · Operational Excel.    (version-locked prompt aliases, OTEL)
  R – GENREL   · Reliability           (fan-out, circuit breaker failover)
  P – GENPERF  · Performance           (AgentCore Harness, WebSocket stream)
  S – GENSEC   · Security              (dual-sided guardrails, microVM isolation)
  E – GENEVAL  · Evaluation & Trust    ← NEW (5-step eval loop, trace scoring)
  E – GENSUST  · Sustainability        (right-sized model routing)
"""
import logging

from pillars import (
    GENCOSTBatchProcessor,
    GENOPSPromptManager,
    GENRELFanOutPublisher,
    GENRELCircuitBreaker,
    GENPERFStreamHandler,
    GENSECGuardrailPerimeter,
    GENEVALEvaluationEngine,
    GENSUSTIntentRouter,
)
from pillars.gensec import GuardrailIntervened

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)


class CORPSEEOrchestrator:
    """
    Single entry-point for all CORPSEE-compliant workloads.

    Usage:
        orc = CORPSEEOrchestrator()

        # Real-time interactive query
        result = orc.handle_query(user_query="...", account_id="ACC-001")

        # Background nightly bulk audit (GENCOST)
        job_arn = orc.submit_batch_audit()

        # Offline evaluation job (GENEVAL)
        eval_arn = orc.submit_evaluation_job()
    """

    def __init__(self) -> None:
        self.cost      = GENCOSTBatchProcessor()        # C
        self.ops       = GENOPSPromptManager()          # O
        self.rel_pub   = GENRELFanOutPublisher()        # R — fan-out
        self.rel_cb    = GENRELCircuitBreaker()         # R — circuit breaker
        self.perf      = GENPERFStreamHandler()         # P
        self.sec       = GENSECGuardrailPerimeter()     # S
        self.eval      = GENEVALEvaluationEngine()      # E (Evaluation)
        self.sust      = GENSUSTIntentRouter()          # E (Sustainability)

    # ────────────────────────────────────────────────────────────────────────
    # Primary pipeline — real-time interactive query
    # ────────────────────────────────────────────────────────────────────────

    def handle_query(
        self,
        user_query:        str,
        account_id:        str  = "ACC-UNKNOWN",
        session_id:        str  = "SESSION-DEFAULT",
        broadcast_event:   bool = True,
        run_eval:          bool = False,
    ) -> dict:
        """
        Full CORPSEE pipeline for a real-time user query.

        Steps:
          1. GENSEC  — scan untrusted input through guardrail perimeter.
          2. GENSUST — classify SIMPLE / COMPLEX to pick the energy tier.
          3. GENOPS  — hydrate the version-locked managed prompt template.
          4. GENREL  — circuit breaker inference (PT primary → serverless fallback).
          5. GENREL  — broadcast transaction event to fan-out worker queues.
          6. GENEVAL — (optional) invoke agent with tracing for runtime evaluation.
        """
        logger.info("═" * 62)
        logger.info("CORPSEE pipeline START  account=%s session=%s", account_id, session_id)
        logger.info("═" * 62)

        # ── Step 1 · S · GENSEC ───────────────────────────────────────────────
        logger.info("Step 1 · GENSEC — dual-sided guardrail input scan")
        try:
            self.sec.safe_execute(user_query)
        except GuardrailIntervened:
            logger.warning("GENSEC blocked input. Aborting pipeline.")
            return {
                "status":  "BLOCKED",
                "reason":  "Input failed Bedrock Guardrail check (prompt injection / PII).",
                "account": account_id,
            }

        # ── Step 2 · E · GENSUST ─────────────────────────────────────────────
        logger.info("Step 2 · GENSUST — intent classification and energy-tier routing")
        sust_result = self.sust.route(user_query)
        intent      = sust_result["intent"]
        logger.info("  → intent=%s  model=%s", intent, sust_result["model_used"])

        if intent == "SIMPLE":
            logger.info("SIMPLE path — staying on low-power compute track.")
            return {
                "status":   "OK",
                "intent":   "SIMPLE",
                "model":    sust_result["model_used"],
                "account":  account_id,
                "session":  session_id,
                "response": sust_result["response"],
            }

        # ── Step 3 · O · GENOPS ───────────────────────────────────────────────
        logger.info("Step 3 · GENOPS — fetching PROD-ACTIVE prompt alias")
        prompt_meta = self.ops.get_prompt_metadata()
        genops_response = self.ops.execute_with_managed_prompt(
            user_query=user_query,
            template_variables={"account_id": account_id},
            trace_context={"trace_id": session_id},
        )
        logger.info("  → prompt=%s version=%s", prompt_meta.get("prompt_name"), prompt_meta.get("prompt_version"))

        # ── Step 4 · R · GENREL — Circuit Breaker Inference ──────────────────
        logger.info("Step 4 · GENREL — circuit breaker inference (PT → serverless fallback)")
        cb_result      = self.rel_cb.reliable_inference(genops_response)
        final_response = cb_result["response"]
        logger.info("  → path=%s  model=%s", cb_result["path"], cb_result["model_used"])

        # ── Step 5 · R · GENREL — Fan-Out Broadcast ──────────────────────────
        if broadcast_event:
            logger.info("Step 5 · GENREL — broadcasting to fan-out worker queues")
            self.rel_pub.broadcast_transaction(
                account_id=account_id,
                payload_summary=user_query[:200],
            )

        # ── Step 6 · E · GENEVAL — Runtime Evaluation (optional) ─────────────
        eval_result = None
        if run_eval:
            logger.info("Step 6 · GENEVAL — runtime trace evaluation")
            try:
                score      = self.eval.invoke_and_evaluate(user_query, session_id)
                eval_result = score.to_dict()
                logger.info(
                    "  → faithfulness=%s  rag_sources=%d  tool_calls=%d",
                    score.faithfulness_flag(),
                    len(score.rag_sources),
                    len(score.tool_calls),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("GENEVAL trace evaluation skipped: %s", exc)
                eval_result = {"status": "skipped", "reason": str(exc)}

        logger.info("═" * 62)
        logger.info("CORPSEE pipeline END  ✅")
        logger.info("═" * 62)

        return {
            "status":      "OK",
            "intent":      intent,
            "model":       cb_result["model_used"],
            "path":        cb_result["path"],
            "account":     account_id,
            "session":     session_id,
            "response":    final_response,
            "eval":        eval_result,
            "prompt_meta": prompt_meta,
        }

    # ────────────────────────────────────────────────────────────────────────
    # Batch pipeline — C · GENCOST
    # ────────────────────────────────────────────────────────────────────────

    def submit_batch_audit(self, job_name: str = "Nightly_Compliance_Bulk_Audit") -> dict:
        """Submit a nightly bulk compliance audit as an async Bedrock Batch job (50% cheaper)."""
        logger.info("[GENCOST] Submitting batch audit: %s", job_name)
        job_arn = self.cost.submit_batch_job(job_name=job_name)
        return {"status": "SUBMITTED", "jobArn": job_arn}

    def check_batch_status(self, job_arn: str) -> dict:
        return self.cost.get_job_status(job_arn)

    # ────────────────────────────────────────────────────────────────────────
    # Evaluation pipeline — E · GENEVAL
    # ────────────────────────────────────────────────────────────────────────

    def submit_evaluation_job(self, job_name: str = "CORPSEE_Offline_Eval") -> dict:
        """
        Submit a Bedrock offline Model Evaluation job against the S3 ground-truth dataset.
        Measures Faithfulness, Helpfulness, and Coherence automatically.
        """
        logger.info("[GENEVAL] Submitting offline evaluation job: %s", job_name)
        job_arn = self.eval.submit_model_evaluation_job(job_name=job_name)
        return {"status": "SUBMITTED", "jobArn": job_arn}


# ── CLI demo ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json

    orc = CORPSEEOrchestrator()

    print("\n" + "▓" * 64)
    print("  CORPSEE DEMO — Real-time SIMPLE query")
    print("▓" * 64)
    result = orc.handle_query(
        user_query="What is the current RBA cash rate?",
        account_id="ACC-001",
        session_id="SESSION-001",
    )
    print(json.dumps(result, indent=2))

    print("\n" + "▓" * 64)
    print("  CORPSEE DEMO — Real-time COMPLEX query with GENEVAL")
    print("▓" * 64)
    result = orc.handle_query(
        user_query=(
            "Analyse the risk profile of this commercial loan application for a $4.2M "
            "mixed-use property in Sydney CBD, considering current RBA rate environment, "
            "tenant concentration risk, and APRA prudential standards CPS 220."
        ),
        account_id="ACC-002",
        session_id="SESSION-002",
        run_eval=True,
    )
    print(json.dumps(result, indent=2))

    print("\n" + "▓" * 64)
    print("  CORPSEE DEMO — Offline evaluation job (GENEVAL)")
    print("▓" * 64)
    eval_job = orc.submit_evaluation_job()
    print(json.dumps(eval_job, indent=2))
