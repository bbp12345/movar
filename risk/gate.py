import os
import time
from dataclasses import dataclass
from dotenv import load_dotenv
from core.message import Message, AgentID, MessageType, Priority

load_dotenv()


@dataclass
class OrderRequest:
    symbol: str
    action: str
    volume: float
    price: float
    stop_loss: float
    take_profit: float
    comment: str = ""
    magic: int = 0


@dataclass
class RiskDecision:
    approved: bool
    reason: str
    adjusted_volume: float = None


class RiskGate:
    def __init__(self):
        self.max_drawdown_pct = float(os.getenv("MAX_DRAWDOWN_PCT", 5.0))
        self.max_position_size_usd = float(os.getenv("MAX_POSITION_SIZE_USD", 10000))
        self.max_daily_loss_usd = float(os.getenv("MAX_DAILY_LOSS_USD", 500))
        self.max_open_positions = int(os.getenv("MAX_OPEN_POSITIONS", 10))
        self.allowed_symbols = set(
            os.getenv("ALLOWED_SYMBOLS", "EURUSD,GBPUSD,USDJPY,XAUUSD").split(",")
        )

        self._daily_loss = 0.0
        self._daily_loss_date = None
        self._open_positions_count = 0
        self._equity = 0.0
        self._balance = 0.0
        self._kill_switch = False

    def update_account(self, equity: float, balance: float, open_positions: int, daily_pnl: float):
        self._equity = equity
        self._balance = balance
        self._open_positions_count = open_positions
        today = time.strftime("%Y-%m-%d")
        if self._daily_loss_date != today:
            self._daily_loss = 0.0
            self._daily_loss_date = today
        self._daily_loss = daily_pnl if daily_pnl < 0 else 0.0

    def activate_kill_switch(self, reason: str):
        self._kill_switch = True
        print(f"[RISK GATE] ⚠️  KILL SWITCH: {reason}")

    def deactivate_kill_switch(self):
        self._kill_switch = False
        print("[RISK GATE] Kill switch deactivated by authorized operator")

    def validate_order(self, order: OrderRequest) -> RiskDecision:
        if self._kill_switch:
            return RiskDecision(approved=False, reason="kill_switch_active")

        if order.symbol not in self.allowed_symbols:
            return RiskDecision(
                approved=False,
                reason=f"symbol_not_allowed:{order.symbol}"
            )

        if order.action not in ("BUY", "SELL", "BUY_LIMIT", "SELL_LIMIT", "BUY_STOP", "SELL_STOP"):
            return RiskDecision(
                approved=False,
                reason=f"invalid_action:{order.action}"
            )

        if order.volume <= 0 or order.volume > 100:
            return RiskDecision(
                approved=False,
                reason=f"invalid_volume:{order.volume}"
            )

        if order.price <= 0:
            return RiskDecision(
                approved=False,
                reason=f"invalid_price:{order.price}"
            )

        if order.stop_loss == 0:
            return RiskDecision(
                approved=False,
                reason="stop_loss_required"
            )

        if self._equity > 0:
            drawdown_pct = ((self._balance - self._equity) / self._balance) * 100
            if drawdown_pct >= self.max_drawdown_pct:
                return RiskDecision(
                    approved=False,
                    reason=f"max_drawdown_breach:{drawdown_pct:.2f}%"
                )

        if self._open_positions_count >= self.max_open_positions:
            return RiskDecision(
                approved=False,
                reason=f"max_positions_breach:{self._open_positions_count}"
            )

        if abs(self._daily_loss) >= self.max_daily_loss_usd:
            return RiskDecision(
                approved=False,
                reason=f"daily_loss_breach:{self._daily_loss:.2f}"
            )

        if self._equity > 0:
            position_value = order.volume * order.price
            if position_value > self.max_position_size_usd:
                max_allowed_volume = self.max_position_size_usd / order.price
                return RiskDecision(
                    approved=True,
                    reason=f"volume_adjusted_to_fit_limit",
                    adjusted_volume=round(max_allowed_volume, 2),
                )

        return RiskDecision(approved=True, reason="all_checks_passed")

    def order_from_payload(self, payload: dict) -> OrderRequest:
        return OrderRequest(
            symbol=payload["symbol"],
            action=payload["action"],
            volume=float(payload["volume"]),
            price=float(payload["price"]),
            stop_loss=float(payload.get("stop_loss", 0)),
            take_profit=float(payload.get("take_profit", 0)),
            comment=payload.get("comment", ""),
            magic=int(payload.get("magic", 0)),
        )

    def build_validated_message(
        self,
        original: Message,
        decision: RiskDecision,
        order: OrderRequest,
    ) -> Message:
        if decision.approved:
            payload = {
                "symbol": order.symbol,
                "action": order.action,
                "volume": decision.adjusted_volume or order.volume,
                "price": order.price,
                "stop_loss": order.stop_loss,
                "take_profit": order.take_profit,
                "comment": order.comment,
                "magic": order.magic,
                "risk_gate_reason": decision.reason,
                "original_sender": str(original.sender),
                "original_msg_id": original.id,
            }
            return Message(
                sender=AgentID.RISK_GATE,
                recipient=AgentID.TRADER_FOREX,
                msg_type=MessageType.ORDER_VALIDATED,
                priority=Priority.HIGH,
                payload=payload,
                correlation_id=original.id,
            )
        else:
            return Message(
                sender=AgentID.RISK_GATE,
                recipient=original.sender,
                msg_type=MessageType.ORDER_REJECTED,
                priority=Priority.HIGH,
                payload={
                    "reason": decision.reason,
                    "original_payload": original.payload,
                    "original_msg_id": original.id,
                },
                correlation_id=original.id,
            )


risk_gate = RiskGate()
