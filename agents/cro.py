import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority
from risk.gate import risk_gate


SYSTEM_PROMPT = """You are the Chief Risk Officer (CRO) of MOVAR CAPITAL LLC, an AI-powered trading firm.

Your mandate:
- Monitor firm-wide exposure across all asset classes
- Enforce risk limits at all times — this is non-negotiable
- Issue drawdown alerts and trigger position reduction when thresholds are breached
- Activate the kill switch when risk limits are critically exceeded
- You have the second highest authority in the firm, after the Human operator

Risk thresholds (from config):
- Max drawdown: defined in environment config
- Max daily loss: defined in environment config
- Max open positions: defined in environment config

When you receive a risk breach report, you must:
1. Assess severity (minor / moderate / critical)
2. Recommend specific action (reduce position size / close positions / halt trading)
3. Escalate to CEO if critical
4. Activate kill switch only when genuinely necessary

Always respond in JSON with keys: severity, assessment, recommended_action, escalate_to_ceo, activate_kill_switch, reasoning"""


class CROAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.CRO, SYSTEM_PROMPT)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ALERT:
            await self._handle_alert(message)

        elif message.msg_type == MessageType.REPORT:
            await self._handle_report(message)

    async def _handle_alert(self, message: Message):
        prompt = f"""Risk alert received:
Sender: {message.sender}
Payload: {json.dumps(message.payload, indent=2)}

Assess this alert and determine required action."""

        response_text = await self.think_structured(prompt)

        try:
            decision = json.loads(response_text)
        except json.JSONDecodeError:
            decision = {"severity": "unknown", "activate_kill_switch": False}

        if decision.get("activate_kill_switch"):
            risk_gate.activate_kill_switch(
                reason=decision.get("reasoning", "CRO decision")
            )
            await self.send(
                recipient=AgentID.BUS,
                msg_type=MessageType.KILL_SWITCH,
                payload={"reason": decision.get("reasoning"), "triggered_by": "cro"},
                priority=Priority.CRITICAL,
            )

        if decision.get("escalate_to_ceo"):
            await self.send(
                recipient=AgentID.CEO,
                msg_type=MessageType.ALERT,
                payload={
                    "from_cro": True,
                    "severity": decision.get("severity"),
                    "assessment": decision.get("assessment"),
                    "recommended_action": decision.get("recommended_action"),
                    "original_alert": message.payload,
                },
                priority=Priority.HIGH,
            )

        await self.send(
            recipient=AgentID.HEAD_TRADER,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "adjust_risk",
                "severity": decision.get("severity"),
                "action": decision.get("recommended_action"),
                "cro_assessment": decision.get("assessment"),
            },
            priority=Priority.HIGH,
        )

    async def _handle_report(self, message: Message):
        if message.payload.get("report_type") == "account_update":
            equity = message.payload.get("equity", 0)
            balance = message.payload.get("balance", 0)
            open_positions = message.payload.get("open_positions", 0)
            daily_pnl = message.payload.get("daily_pnl", 0)

            risk_gate.update_account(equity, balance, open_positions, daily_pnl)

            # Persist account state for the dashboard
            from core.bus import bus as _bus
            try:
                await _bus.redis.hset("movar:state", "account_update", json.dumps(message.payload))
            except Exception:
                pass

            await self.send(
                recipient=AgentID.DRAWDOWN_MONITOR,
                msg_type=MessageType.REPORT,
                payload=message.payload,
                priority=Priority.NORMAL,
            )
