import json
import time
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority
from broker.mt5_bridge import broker


MARKET_RISK_SYSTEM = """You are the Market Risk Analyst at MOVAR CAPITAL LLC.
Monitor real-time price risk across all positions.
Track: VaR, Greeks exposure, correlation risk, tail risk events.
Respond in JSON with keys: risk_level (low/medium/high/critical), var_estimate,
largest_exposures (list), correlation_alerts (list), recommended_hedges"""

LIQUIDITY_RISK_SYSTEM = """You are the Liquidity Risk Analyst at MOVAR CAPITAL LLC.
Track ability to enter/exit positions without adverse market impact.
Monitor: bid-ask spreads, market depth, volume patterns, liquidity crises.
Respond in JSON with keys: liquidity_score (0-10), illiquid_positions (list),
exit_cost_estimate_bps, liquidity_alerts (list)"""

COUNTERPARTY_RISK_SYSTEM = """You are the Counterparty Risk Analyst at MOVAR CAPITAL LLC.
Evaluate exchange and broker exposure. Monitor for: broker solvency signals,
exchange outages, margin call risks, settlement failures.
Respond in JSON with keys: broker_risk_score (0-10), exchange_alerts (list),
margin_utilization_pct, counterparty_flags (list)"""

DRAWDOWN_MONITOR_SYSTEM = """You are the Drawdown Monitor at MOVAR CAPITAL LLC.
Trigger alerts and position reduction at defined loss thresholds.
You have automatic authority to escalate to CRO when thresholds are breached.
Respond in JSON with keys: current_drawdown_pct, daily_loss_usd, threshold_breached (bool),
breach_level (warning/alert/critical), recommended_action"""


class MarketRiskAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.MARKET_RISK, MARKET_RISK_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") in ("account_update", "position_update"):
                await self._assess_risk(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_risk_assessment":
                await self._assess_risk(message)

    async def _assess_risk(self, message: Message):
        positions = await broker.get_open_positions()
        account = await broker.get_account_info()

        prompt = f"""Assess current market risk:
Account: {json.dumps(account, indent=2) if account else 'unavailable'}
Open positions: {json.dumps(positions[:10], indent=2)}
Trigger data: {json.dumps(message.payload, indent=2)}
Identify any immediate risk concerns."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            assessment = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if assessment.get("risk_level") in ("high", "critical"):
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={
                    "alert_type": "market_risk_elevated",
                    "assessment": assessment,
                    "timestamp": time.time(),
                },
                priority=Priority.HIGH,
            )


class LiquidityRiskAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.LIQUIDITY_RISK, LIQUIDITY_RISK_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "assess_liquidity":
                await self._assess_liquidity(message)
        elif message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") == "account_update":
                await self._assess_liquidity(message)

    async def _assess_liquidity(self, message: Message):
        positions = await broker.get_open_positions()

        prompt = f"""Assess liquidity risk for current positions:
Positions: {json.dumps(positions[:10], indent=2)}
Context: {json.dumps(message.payload, indent=2)}
Can we exit all positions within acceptable cost?"""

        response_text = await self.think_structured(prompt, max_tokens=500)
        try:
            assessment = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if assessment.get("liquidity_score", 10) < 4:
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={
                    "alert_type": "liquidity_risk_elevated",
                    "assessment": assessment,
                },
                priority=Priority.HIGH,
            )


class CounterpartyRiskAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.COUNTERPARTY_RISK, COUNTERPARTY_RISK_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "assess_counterparty":
                await self._assess_counterparty(message)

    async def _assess_counterparty(self, message: Message):
        account = await broker.get_account_info()

        prompt = f"""Assess counterparty risk with Fusion Markets:
Account data: {json.dumps(account, indent=2) if account else 'unavailable'}
Context: {json.dumps(message.payload, indent=2)}
Are there any broker or exchange risk signals?"""

        response_text = await self.think_structured(prompt, max_tokens=500)
        try:
            assessment = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if assessment.get("broker_risk_score", 0) >= 7:
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={"alert_type": "counterparty_risk_elevated", "assessment": assessment},
                priority=Priority.HIGH,
            )


class DrawdownMonitorAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.DRAWDOWN_MONITOR, DRAWDOWN_MONITOR_SYSTEM)
        self._peak_equity = 0.0

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") == "account_update":
                await self._monitor_drawdown(message)

    async def _monitor_drawdown(self, message: Message):
        equity = float(message.payload.get("equity", 0))
        balance = float(message.payload.get("balance", 0))
        daily_pnl = float(message.payload.get("daily_pnl", 0))

        if equity > self._peak_equity:
            self._peak_equity = equity

        drawdown_pct = 0.0
        if self._peak_equity > 0:
            drawdown_pct = ((self._peak_equity - equity) / self._peak_equity) * 100

        prompt = f"""Evaluate drawdown status:
Current equity: {equity}
Peak equity: {self._peak_equity}
Drawdown: {drawdown_pct:.2f}%
Daily P&L: {daily_pnl}
Balance: {balance}
Are any thresholds breached?"""

        response_text = await self.think_structured(prompt, max_tokens=400)
        try:
            status = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if status.get("threshold_breached"):
            breach_level = status.get("breach_level", "warning")
            priority = Priority.CRITICAL if breach_level == "critical" else Priority.HIGH

            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={
                    "alert_type": "drawdown_threshold_breached",
                    "drawdown_pct": drawdown_pct,
                    "daily_loss_usd": abs(daily_pnl),
                    "breach_level": breach_level,
                    "recommended_action": status.get("recommended_action"),
                },
                priority=priority,
            )
