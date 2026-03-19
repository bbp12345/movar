import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority

PM_BASE_PROMPT = """You are a Portfolio Manager at MOVAR CAPITAL LLC.
When generating trade signals respond in JSON with keys:
symbol, action (BUY/SELL), entry_price, stop_loss, take_profit, volume_lots,
rationale, confidence (0-1), timeframe, asset_class"""

PM_EQUITIES_SYSTEM = f"""{PM_BASE_PROMPT}
You manage the long/short equity book. Focus on: individual stocks, ETFs, sector rotation,
earnings plays, momentum and mean-reversion setups. Asset class: EQUITIES."""

PM_CRYPTO_SYSTEM = f"""{PM_BASE_PROMPT}
You manage the spot and derivatives crypto book. Focus on: BTC, ETH, major altcoins,
on-chain signals, funding rates, crypto market structure. Asset class: CRYPTO."""

PM_COMMODITIES_SYSTEM = f"""{PM_BASE_PROMPT}
You manage energy, metals, and agricultural positions. Focus on: Gold (XAUUSD), Oil (USOIL),
Silver (XAGUSD), supply/demand fundamentals, seasonality. Asset class: COMMODITIES."""

PM_DERIVATIVES_SYSTEM = f"""{PM_BASE_PROMPT}
You manage options and futures strategies across all assets. Focus on: volatility plays,
spreads, hedging, Greeks management, term structure. Asset class: DERIVATIVES."""


class PMBaseAgent(BaseAgent):
    def __init__(self, agent_id: AgentID, system_prompt: str, magic_number: int):
        super().__init__(agent_id, system_prompt)
        self.magic_number = magic_number
        self._thesis = {}
        self._risk_appetite = "medium"

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "generate_trade_idea":
                await self._generate_trade_idea(message)
            elif command == "update_thesis":
                self._thesis = message.payload.get("thesis", {})
                self._risk_appetite = message.payload.get("risk_appetite", "medium")
            elif command == "adjust_risk":
                await self._handle_risk_adjustment(message)
        elif message.msg_type == MessageType.SIGNAL:
            await self._evaluate_signal(message)
        elif message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") == "market_data":
                await self._analyze_market(message)

    async def _generate_trade_idea(self, message: Message):
        context = message.payload.get("context", "")
        prompt = f"""Generate a trade idea.
Current thesis: {json.dumps(self._thesis)}
Risk appetite: {self._risk_appetite}
Context: {context}
Provide a specific, actionable trade with clear risk parameters."""

        response_text = await self.think_structured(prompt)
        try:
            trade = json.loads(response_text)
        except json.JSONDecodeError:
            return

        min_confidence = {"low": 0.5, "medium": 0.65, "high": 0.7}.get(self._risk_appetite, 0.65)
        if trade.get("confidence", 0) < min_confidence:
            return

        await self.send(
            recipient=AgentID.RISK_GATE,
            msg_type=MessageType.ORDER_REQUEST,
            payload={
                "symbol": trade["symbol"],
                "action": trade["action"],
                "volume": trade["volume_lots"],
                "price": trade["entry_price"],
                "stop_loss": trade["stop_loss"],
                "take_profit": trade["take_profit"],
                "comment": f"{str(self.agent_id)[:10]}: {trade.get('rationale', '')[:40]}",
                "magic": self.magic_number,
            },
            priority=Priority.HIGH,
        )

    async def _evaluate_signal(self, message: Message):
        prompt = f"""Evaluate this signal against current thesis:
Signal: {json.dumps(message.payload, indent=2)}
Current thesis: {json.dumps(self._thesis)}
Should we act on this signal?"""

        response_text = await self.think_structured(prompt)
        try:
            decision = json.loads(response_text)
            if decision.get("enter_trade") and decision.get("confidence", 0) >= 0.65:
                await self._generate_trade_idea(
                    Message(
                        sender=self.agent_id,
                        recipient=self.agent_id,
                        msg_type=MessageType.COMMAND,
                        payload={"context": json.dumps(decision)},
                    )
                )
        except json.JSONDecodeError:
            pass

    async def _analyze_market(self, message: Message):
        prompt = f"""Analyze market data for trading opportunities:
{json.dumps(message.payload, indent=2)}"""
        analysis = await self.think(prompt, max_tokens=400)
        await self.send(
            recipient=AgentID.HEAD_RESEARCH,
            msg_type=MessageType.REPORT,
            payload={"report_type": "pm_analysis", "agent": str(self.agent_id), "analysis": analysis},
            priority=Priority.LOW,
        )

    async def _handle_risk_adjustment(self, message: Message):
        severity = message.payload.get("severity", "minor")
        if severity in ("moderate", "critical"):
            await self.send(
                recipient=AgentID.HEAD_TRADER,
                msg_type=MessageType.COMMAND,
                payload={
                    "command": "reduce_exposure",
                    "asset_class": str(self.agent_id),
                    "severity": severity,
                },
                priority=Priority.HIGH,
            )


class PMEquitiesAgent(PMBaseAgent):
    def __init__(self):
        super().__init__(AgentID.PM_EQUITIES, PM_EQUITIES_SYSTEM, magic_number=1002)


class PMCryptoAgent(PMBaseAgent):
    def __init__(self):
        super().__init__(AgentID.PM_CRYPTO, PM_CRYPTO_SYSTEM, magic_number=1003)


class PMCommoditiesAgent(PMBaseAgent):
    def __init__(self):
        super().__init__(AgentID.PM_COMMODITIES, PM_COMMODITIES_SYSTEM, magic_number=1004)


class PMDerivativesAgent(PMBaseAgent):
    def __init__(self):
        super().__init__(AgentID.PM_DERIVATIVES, PM_DERIVATIVES_SYSTEM, magic_number=1005)
