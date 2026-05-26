# CORPSEE Application — AWS GenAI Well-Architected Framework

A production-ready Python application covering all **7 CORPSEE pillars** for enterprise GenAI on AWS (ap-southeast-2 Sydney).

```
corpss_app/
├── config.py                          ← Centralised ARNs & model IDs
├── orchestrator.py                    ← Main pipeline entry-point (CORPSEEOrchestrator)
├── demo.py                            ← Live AWS demo runner (setup / run / teardown)
├── requirements.txt
├── pillars/
│   ├── gencost.py   C · Cost Optimisation    Prompt Caching + Bedrock Batch (50% cheaper)
│   ├── genops.py    O · Operational Excel.   Bedrock Prompt Aliases + OTEL Observability
│   ├── genrel.py    R · Reliability          Circuit Breaker Failover + SNS/SQS Fan-Out
│   ├── genperf.py   P · Performance Eff.     AgentCore Harness + WebSocket Streaming
│   ├── gensec.py    S · Security             microVM Session Isolation + Bedrock Guardrails
│   ├── geneval.py   E · Evaluation & Trust   5-Step Eval Loop + AgentCore Trace Scoring  ← NEW
│   └── gensust.py   E · Sustainability       Right-sized Model Routing (Nova Micro → Sonnet)
└── lambda_handlers/
    ├── websocket_handler.py           ← GENPERF: API GW WebSocket Lambda
    └── worker_handler.py              ← GENREL: SQS consumer Lambda (fraud / compliance)
```

---

## Pillar Summary

| # | Pillar | Module | AWS Service | Key Technique |
|---|--------|--------|-------------|---------------|
| C | Cost Optimisation | `gencost.py` | Bedrock Batch + Prompt Caching | `cache_control: ephemeral` (80% token saving) + async batch (50% cheaper) |
| O | Operational Excellence | `genops.py` | Bedrock Prompt Management | Version-locked PROD-ACTIVE alias, OTEL trace context propagation |
| R | Reliability | `genrel.py` | SNS + SQS + Provisioned Throughput | Circuit breaker (PT → serverless fallback) + fan-out blast isolation |
| P | Performance Efficiency | `genperf.py` | AgentCore Harness + API GW WebSocket | `invoke_agent` with Managed Memory + `converse_stream` token push |
| S | Security | `gensec.py` | Bedrock Guardrails + AgentCore Runtime | Ephemeral microVM session isolation + dual-sided guardrail perimeter |
| E | Evaluation & Trust | `geneval.py` | Bedrock Model Evaluation + AgentCore Traces | 5-step eval loop: faithfulness · relevance · tool call accuracy |
| E | Sustainability | `gensust.py` | Amazon Nova Micro + Claude 3.5 Sonnet | Right-size: low-power Nova Micro for SIMPLE, frontier for COMPLEX |

---

## Pipeline Flow (Real-Time Query)

```
User Query
   │
   ▼
[S · GENSEC]    Guardrail input scan — blocks prompt injection & PII
   │  PASS
   ▼
[S · GENSUST]   Nova Micro classifies intent → SIMPLE or COMPLEX
   │
   ├─ SIMPLE ──► Nova Micro answers directly (low-power track) ──► Response
   │
   └─ COMPLEX
        │
        ▼
   [O · GENOPS]   Fetch PROD prompt alias, hydrate {{variables}}
        │
        ▼
   [P · GENPERF]  AgentCore Harness invoke_agent + WebSocket converse_stream
        │          Managed Memory re-injects user context automatically
        ▼
   [R · GENREL]   SNS fan-out → fraud-check-queue + compliance-check-queue
        │         (parallel Lambda workers — independent failure domains)
        ▼
   [E · GENEVAL]  AgentCore trace scoring (optional)
        │          → RAG faithfulness · rationale coherence · tool call accuracy
        ▼
       Response
```

## Batch & Evaluation Pipelines

```
[C · GENCOST]   submit_batch_audit()
                → Bedrock Batch job on S3 JSONL manifest
                → 50% cheaper than synchronous On-Demand
                → Prompt caching on repeated reference docs (80% token saving)

[E · GENEVAL]   submit_evaluation_job()
                → Bedrock Model Evaluation automated job
                → S3 ground-truth JSONL → Faithfulness / Helpfulness / Coherence
                → Results gated before PROD promotion (Step 3 of 5-step loop)
```

---

## Quick Start

```bash
pip install -r requirements.txt
export AWS_ACCOUNT_ID=123456789012
python orchestrator.py
```

> **Pre-requisites:** Update `config.py` with your actual ARNs before running against live AWS resources.

---

## AWS Console Setup Checklist

| Pillar | Console Path | Action |
|--------|-------------|--------|
| GENCOST | Bedrock → Batch inference | Create batch job, point to S3 manifest |
| GENCOST | CloudWatch → Application Signals | Set trace indexing to **1%** |
| GENOPS | Bedrock → Prompt Management | Create prompt, add `{{user_query}}` token, publish v1, create `PROD-ACTIVE` alias |
| GENREL | SNS → Topics | Create `AgentTransactionStream` (Standard) |
| GENREL | SQS → Queues | Create `fraud-check-queue`, `compliance-check-queue`, subscribe to SNS |
| GENPERF | Bedrock → Agents | Create agent on AgentCore Harness, enable Managed Memory (30-day TTL) |
| GENPERF | Bedrock → Provisioned throughput | Purchase MU, copy ARN to `config.py` |
| GENSEC | Bedrock → Guardrails | Create guardrail: Prompt attacks = HIGH, PII (Email/Credit Card/IP) = Block/Mask |
| GENEVAL | Bedrock → Model evaluation | Create automated eval job, upload ground-truth JSONL to S3 |
| GENEVAL | Bedrock → Agents | Enable `enableTrace=True` on agent invocations for runtime scoring |
| GENSUST | Bedrock → Model catalog | Nova Micro for baseline, Claude 3.5 Sonnet for escalation |
