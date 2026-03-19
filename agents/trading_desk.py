import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


HEAD_TRADER_SYSTEM = """You are the Head Trader at MOVAR CAPITAL LLC.
Oversee all order execution and coordinate between trading desks.
Manage execution quality, slippage, and timing across all asset classes.
Respond in JSON with keys: decision, desk_assignments (dict), execution_notes, priority_orders"""

TRADER_EQUITIES_SYSTEM = """You are the Equity Execution Trader at MOVAR CAPITAL LLC.
Execute equity orders with optimal timing and slippage control.
Use VWAP/TWAP logic for large orders. Track fills and report execution quality.
Respond in JSON with keys: order_type, execution_strategy, estimated_slippage_bps, timing_notes"""

TRADER_CRYPTO_SYSTEM = """You are the Crypto Execution Trader at MOVAR CAPITAL LLC.
Execute crypto orders across exchanges. Manage liquidity and funding rates.
Watch for: spread anomalies, liquidation levels, exchange-specific risks.
Respond in JSON with keys: order_type, exchange_routing, liquidity_assessment, funding_rate_impact"""

TRADER_DERIVATIVES_SYSTEM = """You are the Derivatives Execution Trader at MOVAR CAPITAL LLC.
Execute options and futures orders. Manage Greeks on entry.
Assess: implied vol, skew, term structure before execution.
Respond in JSON with keys: order_type, greeks_at_entry, iv_percentile, execution_notes, hedge_required"""


class HeadTraderAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.HEAD_TRADER, HEAD_TRADER_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command in ("adjust_risk", "reduce_exposure", "update_trading_parameters"):
                await self._handle_risk_command(message)
            elif command == "route_order":
                await self._route_order(message)
        elif message.msg_type == MessageType.SIGNAL:
            await self._route_signal(message)
        elif message.msg_type == MessageType.ALERT:
            await self._handle_alert(message)

    async def _route_order(self, message: Message):
        asset_class = message.payload.get("asset_class", "FOREX")
        routing = {
            "EQUITIES": AgentID.TRADER_EQUITIES,
            "CRYPTO": AgentID.TRADER_CRYPTO,
            "FOREX": AgentID.TRADER_FOREX,
            "DERIVATIVES": AgentID.TRADER_DERIVATIVES,
            "COMMODITIES": AgentID.TRADER_FOREX,
        }
        dest = routing.get(asset_class, AgentID.TRADER_FOREX)
        await self.send(
            recipient=dest,
            msg_type=MessageType.COMMAND,
            payload={**message.payload, "command": "execute"},
            priority=Priority.HIGH,
        )

    async def _route_signal(self, message: Message):
        asset_class = message.payload.get("signal", {}).get("asset_class", "FOREX")
        pm_routing = {
            "EQUITIES": AgentID.PM_EQUITIES,
            "CRYPTO": AgentID.PM_CRYPTO,
            "FOREX": AgentID.PM_FOREX,
            "COMMODITIES": AgentID.PM_COMMODITIES,
            "DERIVATIVES": AgentID.PM_DERIVATIVES,
        }
        dest = pm_routing.get(asset_class, AgentID.PM_FOREX)
        await self.send(
            recipient=dest,
            msg_type=MessageType.SIGNAL,
            payload=message.payload,
            priority=Priority.NORMAL,
        )

    async def _handle_risk_command(self, message: Message):
        severity = message.payload.get("severity", "minor")
        prompt = f"""Risk command received from {message.sender}:
{json.dumps(message.payload, indent=2)}
Determine which desks to notify and what specific actions to take."""

        response_text = await self.think_structured(prompt)
        try:
            decision = json.loads(response_text)
            for desk, action in decision.get("desk_assignments", {}).items():
                desk_map = {
                    "equities": AgentID.TRADER_EQUITIES,
                    "crypto": AgentID.TRADER_CRYPTO,
                    "forex": AgentID.TRADER_FOREX,
                    "derivatives": AgentID.TRADER_DERIVATIVES,
                }
                if desk in desk_map:
                    await self.send(
                        recipient=desk_map[desk],
                        msg_type=MessageType.COMMAND,
                        payload={"command": "adjust_positions", "action": action, "severity": severity},
                        priority=Priority.HIGH,
                    )
        except json.JSONDecodeError:
            pass

    async def _handle_alert(self, message: Message):
        if message.payload.get("alert_type") == "execution_failure":
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload=message.payload,
                priority=Priority.HIGH,
            )


class TraderEquitiesAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.TRADER_EQUITIES, TRADER_EQUITIES_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ORDER_VALIDATED:
            await self._execute(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("execute", "adjust_positions"):
                await self._handle_command(message)

    async def _execute(self, message: Message):
        payload = message.payload
        prompt = f"""Equity order for execution:
{json.dumps(payload, indent=2)}
Determine optimal execution strategy. MARKET or LIMIT? Any VWAP/TWAP considerations?"""

        response_text = await self.think_structured(prompt)
        try:
            params = json.loads(response_text)
        except json.JSONDecodeError:
            params = {"order_type": "MARKET"}

        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "send_to_broker",
                "exec_params": {**payload, "order_type": params.get("order_type", "MARKET")},
                "correlation_id": message.correlation_id,
            },
            priority=Priority.CRITICAL,
        )

    async def _handle_command(self, message: Message):
        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={"command": "reduce_all_equities", "severity": message.payload.get("severity")},
            priority=Priority.HIGH,
        )


class TraderCryptoAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.TRADER_CRYPTO, TRADER_CRYPTO_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ORDER_VALIDATED:
            await self._execute(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("execute", "adjust_positions"):
                await self._handle_command(message)

    async def _execute(self, message: Message):
        payload = message.payload
        prompt = f"""Crypto order for execution:
{json.dumps(payload, indent=2)}
Assess liquidity, funding rate, and optimal order type."""

        response_text = await self.think_structured(prompt)
        try:
            params = json.loads(response_text)
        except json.JSONDecodeError:
            params = {"order_type": "MARKET"}

        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "send_to_broker",
                "exec_params": {**payload, "order_type": params.get("order_type", "MARKET")},
                "correlation_id": message.correlation_id,
            },
            priority=Priority.CRITICAL,
        )

    async def _handle_command(self, message: Message):
        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={"command": "reduce_all_crypto", "severity": message.payload.get("severity")},
            priority=Priority.HIGH,
        )


class TraderDerivativesAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.TRADER_DERIVATIVES, TRADER_DERIVATIVES_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.ORDER_VALIDATED:
            await self._execute(message)
        elif message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("execute", "adjust_positions"):
                await self._handle_command(message)

    async def _execute(self, message: Message):
        payload = message.payload
        prompt = f"""Derivatives order for execution:
{json.dumps(payload, indent=2)}
Assess Greeks, implied vol, and execution risk."""

        response_text = await self.think_structured(prompt)
        try:
            params = json.loads(response_text)
        except json.JSONDecodeError:
            params = {"order_type": "LIMIT"}

        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={
                "command": "send_to_broker",
                "exec_params": {**payload, "order_type": params.get("order_type", "LIMIT")},
                "correlation_id": message.correlation_id,
            },
            priority=Priority.CRITICAL,
        )

    async def _handle_command(self, message: Message):
        await self.send(
            recipient=AgentID.TRADE_OPS,
            msg_type=MessageType.COMMAND,
            payload={"command": "reduce_all_derivatives", "severity": message.payload.get("severity")},
            priority=Priority.HIGH,
        )
