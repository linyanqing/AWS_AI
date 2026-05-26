"""
P · GENPERF — Performance Efficiency
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Strategy:
  • AgentCore Harness execution: deploy workloads on the managed
    AgentCore Runtime for guaranteed low-latency, long-lived sessions
    (up to 8 hours) without Lambda's 15-minute constraint.
  • Managed Agent Memory (short/long-term): agents natively persist
    user-namespaced context inside the cloud runtime boundary — avoids
    slow vector index fetches for core preferences.
  • API Gateway WebSocket + converse_stream: bi-directional token
    streaming for sub-200 ms time-to-first-token perceived by the user.
  • Provisioned Throughput: dedicated Model Units (MU) eliminate
    noisy-neighbour latency surges on the shared On-Demand fleet.
"""
import json
import logging
import boto3

from config import AWS_REGION, AGENT_ID, AGENT_ALIAS_ID, PROVISIONED_PT_ARN

logger = logging.getLogger(__name__)


class GENPERFStreamHandler:
    """
    Two streaming modes:
      1. AgentCore Harness  — invoke_agent with managed memory + WebSocket push.
      2. Direct stream      — converse_stream on Provisioned Throughput (no agent).
    """

    def __init__(
        self,
        agent_id:       str = AGENT_ID,
        agent_alias_id: str = AGENT_ALIAS_ID,
        provisioned_arn: str = PROVISIONED_PT_ARN,
    ) -> None:
        self._agent_id        = agent_id
        self._agent_alias_id  = agent_alias_id
        self._provisioned_arn = provisioned_arn
        self._agent_rt        = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        self._bedrock_rt      = boto3.client("bedrock-runtime",       region_name=AWS_REGION)

    # ── Mode 1: AgentCore Harness ─────────────────────────────────────────────

    def stream_via_agentcore(
        self,
        connection_id: str,
        domain_name:   str,
        stage:         str,
        user_prompt:   str,
        session_id:    str,
    ) -> int:
        """
        Stream tokens from AgentCore Harness to a WebSocket client.

        AgentCore automatically re-injects short/long-term user preferences
        from Managed Memory into the session — no explicit fetch needed.
        Returns total token chunks pushed.
        """
        gateway_api = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=f"https://{domain_name}/{stage}",
            region_name=AWS_REGION,
        )

        logger.info(
            "[GENPERF] Opening AgentCore Harness stream — session=%s connection=%s",
            session_id, connection_id,
        )

        stream_response = self._agent_rt.invoke_agent(
            agentId=self._agent_id,
            agentAliasId=self._agent_alias_id,
            sessionId=session_id,   # Managed Memory re-injected automatically
            inputText=user_prompt,
            enableTrace=False,      # Trace disabled for performance mode
        )

        token_count = 0
        for event in stream_response["completion"]:
            if "chunk" in event:
                live_token = event["chunk"]["bytes"].decode("utf-8")
                gateway_api.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps({"token": live_token}),
                )
                token_count += 1

        gateway_api.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"done": True, "total_chunks": token_count}),
        )
        logger.info("[GENPERF] ✅ AgentCore stream complete. Chunks pushed: %d", token_count)
        return token_count

    # ── Mode 2: Direct Provisioned Throughput stream ──────────────────────────

    def stream_to_websocket(
        self,
        connection_id: str,
        domain_name:   str,
        stage:         str,
        user_prompt:   str,
    ) -> int:
        """
        Stream Bedrock converse_stream tokens directly to a WebSocket connection.
        Uses Provisioned Throughput for dedicated SLA — no noisy-neighbour risk.
        Returns total tokens pushed.
        """
        gateway_api = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=f"https://{domain_name}/{stage}",
            region_name=AWS_REGION,
        )

        logger.info(
            "[GENPERF] Opening Provisioned Throughput stream — connection=%s", connection_id
        )

        stream_response = self._bedrock_rt.converse_stream(
            modelId=self._provisioned_arn,
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        )

        token_count = 0
        for chunk in stream_response["stream"]:
            if "contentBlockDelta" in chunk:
                live_token = chunk["contentBlockDelta"]["delta"]["text"]
                gateway_api.post_to_connection(
                    ConnectionId=connection_id,
                    Data=json.dumps({"token": live_token}),
                )
                token_count += 1

        gateway_api.post_to_connection(
            ConnectionId=connection_id,
            Data=json.dumps({"done": True, "total_tokens": token_count}),
        )
        logger.info("[GENPERF] ✅ Stream complete. Tokens pushed: %d", token_count)
        return token_count

    def converse_sync(self, user_prompt: str) -> str:
        """Synchronous fallback when no WebSocket connection is available."""
        response = self._bedrock_rt.converse(
            modelId=self._provisioned_arn,
            messages=[{"role": "user", "content": [{"text": user_prompt}]}],
        )
        return response["output"]["message"]["content"][0]["text"]
