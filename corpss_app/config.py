"""
CORPSEE Application — Centralised Configuration
All ARNs, model IDs, and resource identifiers for ap-southeast-2 (Sydney).

7-Pillar CORPSEE Framework:
  C – GENCOST  · Cost Optimisation
  O – GENOPS   · Operational Excellence
  R – GENREL   · Reliability
  P – GENPERF  · Performance Efficiency
  S – GENSEC   · Security
  E – GENEVAL  · Evaluation & Trust        ← NEW
  E – GENSUST  · Environmental Sustainability
"""
import os

# ── Region ──────────────────────────────────────────────────────────────────
AWS_REGION   = "ap-southeast-2"
ACCOUNT_ID   = os.environ.get("AWS_ACCOUNT_ID", "123456789012")
S3_BUCKET    = os.environ.get("CORPSS_S3_BUCKET", "rackspace-sydney-vault")

# ── C · GENCOST: Batch Inference + Prompt Caching ────────────────────────────
BATCH_ROLE_ARN    = f"arn:aws:iam::{ACCOUNT_ID}:role/BedrockBatchProcessingRole"
BATCH_INPUT_S3    = f"s3://{S3_BUCKET}/batch-inputs/pending_loans.jsonl"
BATCH_OUTPUT_S3   = f"s3://{S3_BUCKET}/batch-outputs/"
BATCH_MODEL_ID    = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

# ── O · GENOPS: Prompt Management + OTEL Observability ───────────────────────
PROMPT_ALIAS_ARN  = (
    f"arn:aws:bedrock:{AWS_REGION}:{ACCOUNT_ID}:prompt/LOAN_ROUTER/aliases/PROD-ACTIVE"
)

# ── R · GENREL: Fan-Out Messaging + Circuit Breaker ──────────────────────────
SNS_TOPIC_ARN              = f"arn:aws:sns:{AWS_REGION}:{ACCOUNT_ID}:AgentTransactionStream"
SQS_FRAUD_QUEUE_URL        = f"https://sqs.{AWS_REGION}.amazonaws.com/{ACCOUNT_ID}/corpss-fraud-check-queue"
SQS_COMPLIANCE_QUEUE_URL   = f"https://sqs.{AWS_REGION}.amazonaws.com/{ACCOUNT_ID}/corpss-compliance-check-queue"

# ── P · GENPERF: AgentCore Harness + Provisioned Throughput ──────────────────
AGENT_ID          = os.environ.get("BEDROCK_AGENT_ID", "SYDNEY-PROD-AGENT-ID")
AGENT_ALIAS_ID    = os.environ.get("BEDROCK_AGENT_ALIAS_ID", "PROD-ACTIVE")
PROVISIONED_PT_ARN = (
    f"arn:aws:bedrock:{AWS_REGION}:{ACCOUNT_ID}:provisioned-model/sydney-prod-fast-lane"
)

# ── S · GENSEC: Guardrails + microVM Session Isolation ───────────────────────
GUARDRAIL_ID      = "gdr-sydney-perimeter-01"
GUARDRAIL_VERSION = "DRAFT"

# ── E · GENEVAL: Evaluation & Trust ──────────────────────────────────────────
EVAL_ROLE_ARN       = f"arn:aws:iam::{ACCOUNT_ID}:role/BedrockEvalRole"
EVAL_INPUT_S3       = f"s3://{S3_BUCKET}/eval/ground-truth.jsonl"
EVAL_OUTPUT_S3      = f"s3://{S3_BUCKET}/eval/output/"
EVAL_MODEL_ID       = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"

# ── E · GENSUST: Model Tiers ──────────────────────────────────────────────────
MODEL_LIGHTWEIGHT = "amazon.nova-micro-v1:0"                        # low-power routing
MODEL_FRONTIER    = "us.anthropic.claude-3-5-sonnet-20241022-v2:0"  # deep reasoning
