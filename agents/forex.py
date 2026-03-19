import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


PM_FOREX_SYSTEM = """You are the Portfolio Manager for Forex at MOVAR CAPITAL LLC.

Your responsibilities:
- Manage currency pairs and macro FX trades
- Analyze macro trends, central bank policy, and currency fundamentals
- Generate trade ideas with clear entry, stop loss, and take profit levels
- Monitor open FX positions and P&L
- Coordinate with the Head Trader for execution

When generating a trade signal, always respond in JSON with keys:
symbol, action (BUY/SELL), entry_price, stop_loss, take_profit, volume_lots, rationale, confidence (0-1), timeframe"""

TRADER_FOREX_SYSTEM = """You are the Forex Execution Trader at MOVAR CAPITAL LLC.

Your responsibilities:
- Execute FX spot and forward trades with optimal timing
- Minimize slippage on entry and exit
- Manage order types (market, limit, stop)
- Monitor execution quality and report fills

When you receive a validated order, confirm execution parameters in JSON with keys:
order_type (MARKET/LIMIT/STOP), symbol, action, volume, price, stop_loss, take_profit, comment"""


class PMForexAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.PM_FOREX, PM_FOREX_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.SIGNAL:
            await self._process_signal(message)

        elif message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "generate_trade_idea":
                await self._generate_trade_idea(message)
            elif command == "adjust_risk":
                await self._handle_risk_adjustment(message)

        elif message.msg_type == MessageType.REPORT:
            if message.payload.get("report_type") == "market_data":
                await self._analyze_market(message)

    async def _generate_trade_idea(self, message: Message):
        context = message.payload.get("context", "")
        prompt = f"""Generate a forex trade idea based on current market context.
Context provided: {context}

Provide a specific, actionable trade setup with clear risk parameters."""

        response_text = await self.think_structured(prompt)

        try:
            trade = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if trade.get("confidence", 0) < 0.6:
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
                "comment": f"PM_FOREX: {trade.get('rationale', '')[:50]}",
                "magic": 1001,
            },
            priority=Priority.HIGH,
        )

    async def _process_signal(self, message: Message):
        prompt = f"""Evaluate this trading signal and decide whether to act on it:
Signal: {json.dumps(message.payload, indent=2)}

Should we enter a trade? If yes, provide the trade parameters. If no, explain why."""

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

    async def _handle_risk_adjustment(self, message: Message):
        severity = message.payload.get("severity", "minor")
        if severity in ("moderate", "critical"):
            await self.send(
                recipient=AgentID.HEAD_TRADER,
                msg_type=MessageType.COMMAND,
                payload={
                    "command": "reduce_forex_exposure",
                    "severity": severity,
                    "reason": message.payload.get("action"),
                },
                priority=Priority.HIGH,
            )

    async def _analyze_market(self, message: Message):
        prompt = f"""Analyze this market data and identify opportunities or risks:
Data: {json.dumps(message.payload, indent=2)}

Provide a brief analysis and any immediate action required."""

        analysis = await self.think(prompt, max_tokens=500)

        await self.send(
            recipient=AgentID.HEAD_RESEARCH,
            msg_type=MessageType.REPORT,
            payload={
                "report_type": "forex_analysis",
                "analysis": analysis,
                "source_data": message.payload,
            },
            priority=Priority.NORMAL,
        )


class TraderForexAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.TRADER_FOREX, TRADER_FOREX_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ORDER_VALIDATED:
            await self._execute_order(message)

        elif message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "close_position":
                await self._close_position(message)
            elif command == "reduce_forex_exposure":
                await self._reduce_exposure(message)

    async def _execute_order(self, message: Message):
        payload = message.payload
        prompt = f"""Validated order received for execution:
{json.dumps(payload, indent=2)}

Determine optimal execution parameters. Should we use MARKET or LIMIT order?
Consider current spread and liquidity for {payload.get('symbol')}."""

        response_text = await self.think_structured(prompt)

        try:
            exec_params = json.loads(response_text)
        except json.JSONDecodeError:
            exec_params = {
                "order_type": "MARKET",
                "symbol": payload["symbol"],
                "action": payload["action"],
                "volume": payload["volume"],
                "price": payload["price"],
                "stop_loss": payload["stop_loss"],
                "take_profit": payload["take_profit"],
                "comment": payload.get("comment", ""),
            }

        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "send_to_broker",
                "exec_params": exec_params,
                "correlation_id": message.correlation_id,
            },
            priority=Priority.CRITICAL,
        )

    async def _close_position(self, message: Message):
        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "close_position",
                "symbol": message.payload.get("symbol"),
                "reason": message.payload.get("reason"),
            },
            priority=Priority.HIGH,
        )

    async def _reduce_exposure(self, message: Message):
        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "reduce_all_forex",
                "severity": message.payload.get("severity"),
            },
            priority=Priority.HIGH,
        )
