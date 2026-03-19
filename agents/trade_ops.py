import json
import time
from agents.base import BaseAgent
from broker.mt5_bridge import broker, BrokerOrder
from core.message import Message, AgentID, MessageType, Priority


class TradeOpsAgent(BaseAgent):
    def __init__(self):
        super().__init__(
            AgentID.TRADE_OPS,
            "You are the Trade Operations Analyst at MOVAR CAPITAL LLC. You confirm, settle, and reconcile all trades."
        )
        self._pending_orders: dict[str, dict] = {}

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "send_to_broker":
                await self._send_to_broker(message)
            elif command == "close_position":
                await self._close_position(message)
            elif command == "reduce_all_forex":
                await self._reduce_all_forex(message)
            elif command == "reconcile":
                await self._reconcile(message)

    async def _send_to_broker(self, message: Message):
        exec_params = message.payload.get("exec_params", {})
        correlation_id = message.payload.get("correlation_id")

        try:
            order = BrokerOrder(
                symbol=exec_params["symbol"],
                action=exec_params["action"],
                volume=float(exec_params["volume"]),
                price=float(exec_params["price"]),
                stop_loss=float(exec_params["stop_loss"]),
                take_profit=float(exec_params["take_profit"]),
                comment=exec_params.get("comment", "")[:31],
                magic=int(exec_params.get("magic", 0)),
                order_type=exec_params.get("order_type", "MARKET"),
            )
        except (KeyError, ValueError) as e:
            await self._report_execution_failure(
                message, f"invalid_exec_params:{e}", correlation_id
            )
            return

        result = await broker.send_order(order)

        if result.success:
            self._pending_orders[str(result.ticket)] = {
                "ticket": result.ticket,
                "symbol": order.symbol,
                "action": order.action,
                "volume": result.executed_volume,
                "price": result.executed_price,
                "timestamp": result.timestamp,
                "correlation_id": correlation_id,
            }

            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.REPORT,
                payload={
                    "report_type": "order_executed",
                    "ticket": result.ticket,
                    "symbol": order.symbol,
                    "action": order.action,
                    "volume": result.executed_volume,
                    "price": result.executed_price,
                    "correlation_id": correlation_id,
                    "timestamp": result.timestamp,
                },
                priority=Priority.HIGH,
            )

            await self.send(
                recipient=AgentID.CFO,
                msg_type=MessageType.REPORT,
                payload={
                    "report_type": "trade_confirmed",
                    "ticket": result.ticket,
                    "symbol": order.symbol,
                    "action": order.action,
                    "volume": result.executed_volume,
                    "price": result.executed_price,
                },
                priority=Priority.NORMAL,
            )

        else:
            await self._report_execution_failure(
                message,
                f"broker_error:{result.error_code}:{result.error_message}",
                correlation_id,
            )

    async def _close_position(self, message: Message):
        symbol = message.payload.get("symbol")
        ticket = message.payload.get("ticket")

        if ticket:
            result = await broker.close_position(int(ticket))
            if result.success:
                await self.send(
                    recipient=AgentID.CRO,
                    msg_type=MessageType.REPORT,
                    payload={
                        "report_type": "position_closed",
                        "ticket": ticket,
                        "symbol": symbol,
                        "reason": message.payload.get("reason"),
                        "timestamp": time.time(),
                    },
                    priority=Priority.HIGH,
                )

    async def _reduce_all_forex(self, message: Message):
        positions = await broker.get_open_positions()
        forex_pairs = {"EURUSD", "GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD", "NZDUSD"}

        for pos in positions:
            if pos.get("symbol") in forex_pairs:
                result = await broker.close_position(pos["ticket"])
                if result.success:
                    await self.send(
                        recipient=AgentID.CRO,
                        msg_type=MessageType.REPORT,
                        payload={
                            "report_type": "position_closed",
                            "ticket": pos["ticket"],
                            "symbol": pos["symbol"],
                            "reason": f"risk_reduction_{message.payload.get('severity')}",
                        },
                        priority=Priority.HIGH,
                    )

    async def _reconcile(self, message: Message):
        account = await broker.get_account_info()
        positions = await broker.get_open_positions()

        if account:
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.COMMAND,
                payload={
                    "command": "update_account",
                    "equity": account.get("equity", 0),
                    "balance": account.get("balance", 0),
                    "open_positions": len(positions),
                    "daily_pnl": account.get("profit", 0),
                },
                priority=Priority.NORMAL,
            )

    async def _report_execution_failure(self, message: Message, reason: str, correlation_id: str):
        await self.send(
            recipient=AgentID.HEAD_TRADER,
            msg_type=MessageType.ALERT,
            payload={
                "alert_type": "execution_failure",
                "reason": reason,
                "original_payload": message.payload,
                "correlation_id": correlation_id,
            },
            priority=Priority.HIGH,
        )
