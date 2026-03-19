import json
import time
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority
from broker.mt5_bridge import broker


CTO_SYSTEM = """You are the Chief Technology Officer (CTO) of MOVAR CAPITAL LLC.

Your mandate:
- Manage all trading infrastructure, data pipelines, and agent systems
- Monitor system health and latency
- Escalate infrastructure failures immediately
- Coordinate with the Data Engineer and ML Engineer on pipeline integrity

Respond in JSON with keys: assessment, action_required, affected_components, severity, resolution_steps"""

CFO_SYSTEM = """You are the Chief Financial Officer (CFO) of MOVAR CAPITAL LLC.

Your mandate:
- Track P&L, cash positions, fees, and financial reporting
- Monitor daily/weekly/monthly performance metrics
- Flag unusual fee patterns or accounting discrepancies
- Report to CEO on financial health

When generating reports, respond in JSON with keys:
report_type, period, gross_pnl, net_pnl, fees, win_rate, sharpe_estimate, risk_adjusted_return, commentary, flags"""


class CTOAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.CTO, CTO_SYSTEM)
        self._last_health_check = 0.0

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ALERT:
            await self._handle_infra_alert(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "health_check":
                await self._run_health_check()
        elif message.msg_type == MessageType.HEARTBEAT:
            await self._process_heartbeat(message)

    async def _run_health_check(self):
        from core.bus import bus
        health = await bus.health_check()
        broker_account = await broker.get_account_info()

        status = {
            "redis": health.get("status"),
            "broker_connected": broker_account is not None,
            "kill_switch": health.get("kill_switch_active"),
            "audit_entries": health.get("audit_length"),
            "timestamp": time.time(),
        }

        if health.get("status") != "ok" or broker_account is None:
            await self.send(
                recipient=AgentID.CEO,
                msg_type=MessageType.ALERT,
                payload={"alert_type": "infrastructure_failure", "status": status},
                priority=Priority.CRITICAL,
            )

        self._last_health_check = time.time()

    async def _handle_infra_alert(self, message: Message):
        prompt = f"""Infrastructure alert:
{json.dumps(message.payload, indent=2)}

Assess severity and provide resolution steps."""

        response_text = await self.think_structured(prompt)
        try:
            assessment = json.loads(response_text)
            if assessment.get("severity") in ("critical", "high"):
                await self.send(
                    recipient=AgentID.CEO,
                    msg_type=MessageType.ALERT,
                    payload={"from_cto": True, "assessment": assessment},
                    priority=Priority.HIGH,
                )
        except json.JSONDecodeError:
            pass

    async def _process_heartbeat(self, message: Message):
        agent = message.payload.get("agent")
        ts = float(message.payload.get("timestamp", 0))
        lag = time.time() - ts
        if lag > 60:
            await self.send(
                recipient=AgentID.CEO,
                msg_type=MessageType.ALERT,
                payload={"alert_type": "agent_lag", "agent": agent, "lag_seconds": lag},
                priority=Priority.NORMAL,
            )


class CFOAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.CFO, CFO_SYSTEM)
        self._trades: list[dict] = []
        self._total_fees = 0.0
        self._total_pnl = 0.0

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            report_type = message.payload.get("report_type")
            if report_type == "trade_confirmed":
                await self._record_trade(message)
            elif report_type == "generate_daily":
                await self._generate_daily_report()

    async def _record_trade(self, message: Message):
        self._trades.append({
            "ticket": message.payload.get("ticket"),
            "symbol": message.payload.get("symbol"),
            "action": message.payload.get("action"),
            "volume": message.payload.get("volume"),
            "price": message.payload.get("price"),
            "timestamp": time.time(),
        })

    async def _generate_daily_report(self):
        account = await broker.get_account_info()
        if not account:
            return

        prompt = f"""Generate a daily P&L report from this data:
Account: {json.dumps(account, indent=2)}
Trades today: {len(self._trades)}
Total trades recorded: {json.dumps(self._trades[-10:], indent=2)}

Compute key metrics and flag any anomalies."""

        response_text = await self.think_structured(prompt, max_tokens=800)
        try:
            report = json.loads(response_text)
            await self.send(
                recipient=AgentID.CEO,
                msg_type=MessageType.REPORT,
                payload={**report, "report_type": "daily_pnl"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass
