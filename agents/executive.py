import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


CEO_SYSTEM = """You are the Chief Executive Officer (CEO) of MOVAR CAPITAL LLC, an AI-powered trading firm.

Your mandate:
- Oversee all firm operations and set firm-wide strategy
- Final authority on capital allocation decisions
- Coordinate between all department heads
- Escalate critical decisions to the Human operator when required
- Make high-level decisions based on reports from CIO, CRO, CFO

When making decisions, respond in JSON with keys:
decision, rationale, actions_required (list), escalate_to_human (bool), priority"""

CIO_SYSTEM = """You are the Chief Investment Officer (CIO) of MOVAR CAPITAL LLC.

Your mandate:
- Own the investment thesis for all asset classes
- Approve all portfolio-level decisions
- Coordinate research and portfolio management departments
- Set allocation targets across equities, crypto, forex, commodities, derivatives
- Evaluate market regime and adjust strategy accordingly

When making investment decisions, respond in JSON with keys:
decision, thesis, allocations (dict by asset class), risk_appetite (low/medium/high), actions_required (list), rationale"""


class CEOAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.CEO, CEO_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ALERT:
            await self._handle_alert(message)
        elif message.msg_type == MessageType.REPORT:
            await self._handle_report(message)
        elif message.msg_type == MessageType.COMMAND:
            await self._handle_command(message)

    async def _handle_alert(self, message: Message):
        prompt = f"""Critical alert escalated to CEO:
Sender: {message.sender}
Payload: {json.dumps(message.payload, indent=2)}

What is your decision? Should this be escalated to the Human operator?"""

        response_text = await self.think_structured(prompt)
        try:
            decision = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if decision.get("escalate_to_human"):
            await self.send(
                recipient=AgentID.HUMAN,
                msg_type=MessageType.ALERT,
                payload={
                    "from_ceo": True,
                    "severity": "critical",
                    "decision": decision.get("decision"),
                    "rationale": decision.get("rationale"),
                    "original_alert": message.payload,
                },
                priority=Priority.CRITICAL,
            )

        for action in decision.get("actions_required", []):
            await self.send(
                recipient=AgentID.CIO,
                msg_type=MessageType.COMMAND,
                payload={"command": "execute_ceo_directive", "action": action, "context": decision},
                priority=Priority.HIGH,
            )

    async def _handle_report(self, message: Message):
        if message.payload.get("report_type") in ("daily_pnl", "weekly_summary"):
            prompt = f"""Review this performance report and determine if strategy adjustments are needed:
{json.dumps(message.payload, indent=2)}"""
            response_text = await self.think_structured(prompt, max_tokens=800)
            try:
                decision = json.loads(response_text)
                if decision.get("actions_required"):
                    await self.send(
                        recipient=AgentID.CIO,
                        msg_type=MessageType.COMMAND,
                        payload={"command": "adjust_strategy", "directives": decision},
                        priority=Priority.NORMAL,
                    )
            except json.JSONDecodeError:
                pass

    async def _handle_command(self, message: Message):
        if message.sender == AgentID.HUMAN:
            await self.send(
                recipient=AgentID.CIO,
                msg_type=MessageType.COMMAND,
                payload={"command": "execute_human_directive", "directive": message.payload},
                priority=Priority.CRITICAL,
            )


class CIOAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.CIO, CIO_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            await self._handle_command(message)
        elif message.msg_type == MessageType.REPORT:
            await self._handle_report(message)
        elif message.msg_type == MessageType.SIGNAL:
            await self._handle_signal(message)

    async def _handle_command(self, message: Message):
        command = message.payload.get("command")

        if command in ("adjust_strategy", "execute_ceo_directive", "execute_human_directive"):
            prompt = f"""Directive received:
Command: {command}
Payload: {json.dumps(message.payload, indent=2)}

Define specific portfolio-level actions to implement this directive."""

            response_text = await self.think_structured(prompt, max_tokens=800)
            try:
                decision = json.loads(response_text)
            except json.JSONDecodeError:
                return

            for pm_agent in [
                AgentID.PM_FOREX, AgentID.PM_EQUITIES,
                AgentID.PM_CRYPTO, AgentID.PM_COMMODITIES, AgentID.PM_DERIVATIVES,
            ]:
                await self.send(
                    recipient=pm_agent,
                    msg_type=MessageType.COMMAND,
                    payload={
                        "command": "update_thesis",
                        "thesis": decision.get("thesis"),
                        "risk_appetite": decision.get("risk_appetite", "medium"),
                        "allocations": decision.get("allocations", {}),
                    },
                    priority=Priority.HIGH,
                )

    async def _handle_report(self, message: Message):
        if message.payload.get("report_type") == "research_summary":
            prompt = f"""Research report received. Update investment thesis if warranted:
{json.dumps(message.payload, indent=2)}"""
            response_text = await self.think_structured(prompt)
            try:
                decision = json.loads(response_text)
                if decision.get("actions_required"):
                    await self.send(
                        recipient=AgentID.HEAD_TRADER,
                        msg_type=MessageType.COMMAND,
                        payload={"command": "update_trading_parameters", "cio_decision": decision},
                        priority=Priority.NORMAL,
                    )
            except json.JSONDecodeError:
                pass

    async def _handle_signal(self, message: Message):
        prompt = f"""Investment signal received for CIO review:
{json.dumps(message.payload, indent=2)}

Does this align with current investment thesis? Approve or reject."""

        response_text = await self.think_structured(prompt)
        try:
            decision = json.loads(response_text)
            if decision.get("decision") == "approve":
                await self.send(
                    recipient=AgentID.HEAD_TRADER,
                    msg_type=MessageType.SIGNAL,
                    payload={**message.payload, "cio_approved": True},
                    priority=Priority.HIGH,
                )
        except json.JSONDecodeError:
            pass
