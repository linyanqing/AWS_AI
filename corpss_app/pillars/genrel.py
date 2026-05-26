"""
R · GENREL — Reliability
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  • Blast Radius Isolation via SNS + SQS Fan-Out: a single transaction
    event fans out to N independent SQS worker queues. If one queue or
    consumer crashes, all others continue completely unaffected.
  • Strands Agents design: multi-agent communication networks with
    predictable, structured orchestration patterns.
  • Circuit Breaker Failover: inference first targets Provisioned
    Throughput (dedicated SLA). On ThrottlingException or 503, the
    circuit breaker trips and automatically re-routes to On-Demand
    serverless — zero manual intervention.
  • AWS Step Functions Stage Gates: rigid macro workflow with native
    Catch blocks for Bedrock API faults.
"""
import json
import logging
import boto3
from botocore.exceptions import ClientError

from config import (
    AWS_REGION,
    SNS_TOPIC_ARN,
    PROVISIONED_PT_ARN,
    MODEL_FRONTIER,
)

logger = logging.getLogger(__name__)

# Fault classes that trigger the circuit breaker
_CIRCUIT_BREAKER_FAULTS = {"ThrottlingException", "ServiceUnavailableException", "ModelTimeoutException"}


class GENRELFanOutPublisher:
    """
    Broadcasts a transaction event to all downstream agent queues via SNS.
    Queues subscribe independently — this class is unaware of how many exist.
    """

    def __init__(self, topic_arn: str = SNS_TOPIC_ARN) -> None:
        self._topic_arn = topic_arn
        self._sns       = boto3.client("sns", region_name=AWS_REGION)

    def broadcast_transaction(
        self,
        account_id: str,
        payload_summary: str,
        tier: str = "HighRisk",
    ) -> str:
        """
        Publish a structured event to AgentTransactionStream.
        All subscribed SQS queues receive an independent copy simultaneously.
        Returns the SNS MessageId.
        """
        message = {
            "account_id":     account_id,
            "summary":        payload_summary,
            "region_context": AWS_REGION,
        }

        logger.info("[GENREL] Broadcasting transaction account=%s tier=%s", account_id, tier)

        response = self._sns.publish(
            TopicArn=self._topic_arn,
            Message=json.dumps(message),
            MessageAttributes={
                "TransactionTier": {"DataType": "String", "StringValue": tier}
            },
        )

        msg_id = response["MessageId"]
        logger.info("[GENREL] ✅ Fan-out complete. MessageId: %s", msg_id)
        return msg_id


class GENRELCircuitBreaker:
    """
    Reliable inference with automatic circuit-breaking failover.

    Primary path  : Bedrock Provisioned Throughput (dedicated SLA, no noisy-neighbour).
    Fallback path : On-Demand Claude 3.5 Sonnet serverless pool.

    The circuit breaker trips on ThrottlingException, ServiceUnavailableException,
    or ModelTimeoutException — covering both capacity and infrastructure faults.
    """

    def __init__(
        self,
        provisioned_arn: str = PROVISIONED_PT_ARN,
        fallback_model:  str = MODEL_FRONTIER,
    ) -> None:
        self._provisioned_arn = provisioned_arn
        self._fallback_model  = fallback_model
        self._bedrock_rt      = boto3.client("bedrock-runtime", region_name=AWS_REGION)

    def reliable_inference(self, user_prompt: str) -> dict:
        """
        Execute inference with circuit-breaking failover.

        Returns:
            {
                "response":   str,
                "path":       "PRIMARY" | "FALLBACK",
                "model_used": str,
            }
        """
        try:
            logger.info("[GENREL] Attempting PRIMARY path (Provisioned Throughput).")
            response = self._bedrock_rt.converse(
                modelId=self._provisioned_arn,
                messages=[{"role": "user", "content": [{"text": user_prompt}]}],
            )
            text = response["output"]["message"]["content"][0]["text"]
            logger.info("[GENREL] ✅ PRIMARY path succeeded.")
            return {"response": text, "path": "PRIMARY", "model_used": self._provisioned_arn}

        except ClientError as exc:
            code = exc.response["Error"]["Code"]
            if code in _CIRCUIT_BREAKER_FAULTS:
                logger.warning(
                    "[GENREL] 🚨 Circuit breaker tripped (%s) — failing over to serverless pool.", code
                )
                backup = self._bedrock_rt.converse(
                    modelId=self._fallback_model,
                    messages=[{"role": "user", "content": [{"text": user_prompt}]}],
                )
                text = backup["output"]["message"]["content"][0]["text"]
                logger.info("[GENREL] ✅ FALLBACK path succeeded.")
                return {"response": text, "path": "FALLBACK", "model_used": self._fallback_model}
            raise
