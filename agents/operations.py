import json
import time
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority
from broker.mt5_bridge import broker


HEAD_OPS_SYSTEM = """You are the Head of Operations at MOVAR CAPITAL LLC.
Ensure smooth daily firm operations. Coordinate Trade Ops, Compliance, Tax, and Data teams.
Respond in JSON with keys: operational_status, issues_flagged (list), actions_taken, escalations"""

COMPLIANCE_SYSTEM = """You are the Compliance Officer at MOVAR CAPITAL LLC.
Monitor regulatory requirements and flag violations.
Track: position limits, wash trading, pattern day trader rules, reporting obligations.
Respond in JSON with keys: compliance_status (clean/warning/violation), violations (list),
required_reports (list), regulatory_flags, immediate_actions"""

TAX_SYSTEM = """You are the Tax & Accounting Analyst at MOVAR CAPITAL LLC.
Track tax obligations, mark-to-market elections, and Form 5472 requirements.
Monitor: realized/unrealized PnL, wash sale rules, short vs long term gains.
Respond in JSON with keys: realized_pnl_ytd, unrealized_pnl, estimated_tax_liability,
wash_sale_flags (list), form_5472_required, accounting_notes"""

DATA_ENGINEER_SYSTEM = """You are the Data Engineer at MOVAR CAPITAL LLC.
Manage market data feeds, storage, and pipeline integrity.
Monitor: data quality, feed latency, missing bars, anomalous prices.
Respond in JSON with keys: feed_status (dict), data_quality_score (0-10),
anomalies_detected (list), pipeline_alerts, recommended_actions"""


class HeadOperationsAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.HEAD_OPERATIONS, HEAD_OPS_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ALERT:
            await self._handle_ops_alert(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "daily_ops_check":
                await self._daily_check()

    async def _daily_check(self):
        for agent in [AgentID.COMPLIANCE, AgentID.DATA_ENGINEER, AgentID.TAX_ACCOUNTING]:
            await self.send(
                recipient=agent,
                msg_type=MessageType.COMMAND,
                payload={"command": "run_daily_check"},
                priority=Priority.NORMAL,
            )

    async def _handle_ops_alert(self, message: Message):
        prompt = f"""Operational alert received:
{json.dumps(message.payload, indent=2)}
What immediate operational actions are required?"""

        response_text = await self.think_structured(prompt, max_tokens=400)
        try:
            response = json.loads(response_text)
            if response.get("escalations"):
                await self.send(
                    recipient=AgentID.CTO,
                    msg_type=MessageType.ALERT,
                    payload={"from_head_ops": True, "assessment": response},
                    priority=Priority.HIGH,
                )
        except json.JSONDecodeError:
            pass


class ComplianceAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.COMPLIANCE, COMPLIANCE_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type in (MessageType.REPORT, MessageType.COMMAND):
            if message.payload.get("report_type") in ("trade_confirmed", "order_executed") \
                    or message.payload.get("command") == "run_daily_check":
                await self._check_compliance(message)

    async def _check_compliance(self, message: Message):
        positions = await broker.get_open_positions()
        account = await broker.get_account_info()

        prompt = f"""Run compliance check:
Recent activity: {json.dumps(message.payload, indent=2)}
Open positions: {len(positions)}
Account: {json.dumps(account, indent=2) if account else 'unavailable'}
Are there any regulatory concerns?"""

        response_text = await self.think_structured(prompt, max_tokens=500)
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if result.get("compliance_status") in ("warning", "violation"):
            await self.send(
                recipient=AgentID.HEAD_OPERATIONS,
                msg_type=MessageType.ALERT,
                payload={"alert_type": "compliance_issue", "result": result},
                priority=Priority.HIGH,
            )
            if result.get("compliance_status") == "violation":
                await self.send(
                    recipient=AgentID.CRO,
                    msg_type=MessageType.ALERT,
                    payload={"alert_type": "compliance_violation", "result": result},
                    priority=Priority.CRITICAL,
                )


class TaxAccountingAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.TAX_ACCOUNTING, TAX_SYSTEM)
        self._realized_pnl = 0.0
        self._trades_log: list[dict] = []

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") in ("trade_confirmed", "position_closed"):
                await self._record_for_tax(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_daily_check":
                await self._generate_tax_report()

    async def _record_for_tax(self, message: Message):
        self._trades_log.append({
            **message.payload,
            "recorded_at": time.time(),
        })

    async def _generate_tax_report(self):
        prompt = f"""Generate tax accounting summary:
Trades recorded: {len(self._trades_log)}
Recent trades: {json.dumps(self._trades_log[-5:], indent=2)}
Estimate tax obligations and flag any wash sale or reporting issues."""

        response_text = await self.think_structured(prompt, max_tokens=500)
        try:
            report = json.loads(response_text)
            await self.send(
                recipient=AgentID.CFO,
                msg_type=MessageType.REPORT,
                payload={**report, "report_type": "tax_summary"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class DataEngineerAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.DATA_ENGINEER, DATA_ENGINEER_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_daily_check", "check_feeds"):
                await self._check_data_feeds(message)

    async def _check_data_feeds(self, message: Message):
        account = await broker.get_account_info()
        broker_ok = account is not None

        prompt = f"""Check data pipeline integrity:
Broker connection: {'OK' if broker_ok else 'FAILED'}
Context: {json.dumps(message.payload, indent=2)}
Assess data feed quality and flag any anomalies."""

        response_text = await self.think_structured(prompt, max_tokens=400)
        try:
            result = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if not broker_ok or result.get("data_quality_score", 10) < 6:
            await self.send(
                recipient=AgentID.CTO,
                msg_type=MessageType.ALERT,
                payload={"alert_type": "data_feed_issue", "result": result, "broker_ok": broker_ok},
                priority=Priority.HIGH,
            )
