"""
C · GENCOST — Cost Optimisation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  • W-S-C-I Context Engineering: Write clean prompts, Select context
    vectors, Compress summaries, Isolate per-agent context — controls
    token bloat before it hits the billing meter.
  • Bedrock Prompt Caching: mark large, repeated reference documents
    with cache_control → ephemeral to bypass ~80% of processing fees
    on subsequent calls within the 5-minute cache TTL.
  • Async Batch Inference: flat 50% discount vs On-Demand for
    non-time-sensitive workloads (nightly compliance audits, bulk scans).
  • 1% CloudWatch trace-indexing to suppress runaway logging costs.
"""
import logging
import boto3

from config import (
    AWS_REGION,
    BATCH_ROLE_ARN,
    BATCH_INPUT_S3,
    BATCH_OUTPUT_S3,
    BATCH_MODEL_ID,
    MODEL_FRONTIER,
)

logger = logging.getLogger(__name__)


class GENCOSTBatchProcessor:
    """
    Cost-optimised inference via two mechanisms:
      1. Prompt Caching  — eliminates re-processing of large static contexts.
      2. Batch Inference — 50% discount for asynchronous bulk workloads.
    """

    def __init__(self) -> None:
        self._bedrock    = boto3.client("bedrock",         region_name=AWS_REGION)
        self._bedrock_rt = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    # ── Public API ────────────────────────────────────────────────────────────

    def converse_with_cache(
        self,
        user_message: str,
        large_context: str,
        model_id: str = MODEL_FRONTIER,
    ) -> str:
        """
        Invoke Bedrock with explicit prompt cache markers on the large context block.

        The first call processes the full context; subsequent calls within the
        5-minute cache TTL bypass ~80% of the input-token processing cost.
        Ideal for: multi-turn conversations over the same reference document,
        repeated policy/compliance evaluations, or RAG enrichment passes.
        """
        logger.info("[GENCOST] Invoking with prompt cache marker on context block.")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        # Large static block marked for caching
                        "text":          large_context,
                        "cacheControl":  {"type": "ephemeral"},
                    },
                    {
                        # Dynamic user query — never cached
                        "text": f"Evaluate the following against our architecture: {user_message}",
                    },
                ],
            }
        ]

        response = self._bedrock_rt.converse(
            modelId=model_id,
            messages=messages,
        )

        usage = response.get("usage", {})
        cache_hits = usage.get("cacheReadInputTokens", 0)
        if cache_hits:
            logger.info("[GENCOST] 💰 Cache HIT — %d tokens served from cache.", cache_hits)
        else:
            logger.info("[GENCOST] Cache MISS — context written to cache for next call.")

        return response["output"]["message"]["content"][0]["text"]

    def submit_batch_job(
        self,
        job_name: str = "Nightly_Compliance_Bulk_Audit",
        input_s3: str = BATCH_INPUT_S3,
        output_s3: str = BATCH_OUTPUT_S3,
    ) -> str:
        """
        Submit a Bedrock Model Invocation Batch job (50% cheaper than On-Demand).
        Returns the JobArn for status polling.
        """
        logger.info("[GENCOST] Submitting async batch job: %s", job_name)

        response = self._bedrock.create_model_invocation_job(
            jobName=job_name,
            modelId=BATCH_MODEL_ID,
            roleArn=BATCH_ROLE_ARN,
            inputDataConfig={"s3InputDataConfig": {"s3Uri": input_s3}},
            outputDataConfig={"s3OutputDataConfig": {"s3Uri": output_s3}},
        )

        job_arn = response["jobArn"]
        logger.info("[GENCOST] ✅ Batch job created. ARN: %s", job_arn)
        return job_arn

    def get_job_status(self, job_arn: str) -> dict:
        """Poll the status of a running batch job."""
        response = self._bedrock.get_model_invocation_job(jobIdentifier=job_arn)
        status   = response.get("status", "UNKNOWN")
        logger.info("[GENCOST] Batch job status: %s", status)
        return {"jobArn": job_arn, "status": status}
