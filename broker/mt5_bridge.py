import asyncio
import os
import time
from dataclasses import dataclass
from typing import Optional

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    MT5_AVAILABLE = False
    print("[BROKER] MetaTrader5 not installed — running in mock mode")

from dotenv import load_dotenv

load_dotenv()


@dataclass
class BrokerOrder:
    symbol: str
    action: str
    volume: float
    price: float
    stop_loss: float
    take_profit: float
    comment: str = ""
    magic: int = 0
    order_type: str = "MARKET"


@dataclass
class BrokerResult:
    success: bool
    ticket: Optional[int]
    error_code: Optional[int]
    error_message: Optional[str]
    executed_price: Optional[float]
    executed_volume: Optional[float]
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()


class MT5Bridge:
    def __init__(self):
        self._connected = False
        self._mock_mode = not MT5_AVAILABLE
        self._mock_ticket_counter = 1000

    async def connect(self) -> bool:
        if self._mock_mode:
            print("[BROKER] Mock mode: MT5 not available")
            self._connected = True
            return True

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, self._connect_sync)
        self._connected = result
        return result

    def _connect_sync(self) -> bool:
        if not mt5.initialize(
            login=int(os.getenv("MT5_LOGIN", 0)),
            password=os.getenv("MT5_PASSWORD", ""),
            server=os.getenv("MT5_SERVER", "FusionMarkets-Demo"),
        ):
            print(f"[BROKER] MT5 init failed: {mt5.last_error()}")
            return False
        print("[BROKER] MT5 connected to Fusion Markets")
        return True

    async def disconnect(self):
        if not self._mock_mode and self._connected:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, mt5.shutdown)
        self._connected = False

    async def send_order(self, order: BrokerOrder) -> BrokerResult:
        if not self._connected:
            return BrokerResult(
                success=False, ticket=None,
                error_code=-1, error_message="not_connected",
                executed_price=None, executed_volume=None,
            )

        if self._mock_mode:
            return await self._mock_order(order)

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._send_order_sync, order)

    def _send_order_sync(self, order: BrokerOrder) -> BrokerResult:
        action_map = {
            "BUY": mt5.ORDER_TYPE_BUY,
            "SELL": mt5.ORDER_TYPE_SELL,
            "BUY_LIMIT": mt5.ORDER_TYPE_BUY_LIMIT,
            "SELL_LIMIT": mt5.ORDER_TYPE_SELL_LIMIT,
            "BUY_STOP": mt5.ORDER_TYPE_BUY_STOP,
            "SELL_STOP": mt5.ORDER_TYPE_SELL_STOP,
        }

        order_action = (
            mt5.TRADE_ACTION_DEAL
            if order.order_type == "MARKET"
            else mt5.TRADE_ACTION_PENDING
        )

        symbol_info = mt5.symbol_info(order.symbol)
        if symbol_info is None:
            return BrokerResult(
                success=False, ticket=None,
                error_code=-2, error_message=f"symbol_not_found:{order.symbol}",
                executed_price=None, executed_volume=None,
            )

        if not symbol_info.visible:
            mt5.symbol_select(order.symbol, True)

        price = (
            mt5.symbol_info_tick(order.symbol).ask
            if order.action == "BUY"
            else mt5.symbol_info_tick(order.symbol).bid
        ) if order.order_type == "MARKET" else order.price

        request = {
            "action": order_action,
            "symbol": order.symbol,
            "volume": order.volume,
            "type": action_map[order.action],
            "price": price,
            "sl": order.stop_loss,
            "tp": order.take_profit,
            "deviation": 10,
            "magic": order.magic,
            "comment": order.comment[:31],
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return BrokerResult(
                success=True,
                ticket=result.order,
                error_code=None,
                error_message=None,
                executed_price=result.price,
                executed_volume=result.volume,
            )
        else:
            return BrokerResult(
                success=False,
                ticket=None,
                error_code=result.retcode,
                error_message=result.comment,
                executed_price=None,
                executed_volume=None,
            )

    async def _mock_order(self, order: BrokerOrder) -> BrokerResult:
        await asyncio.sleep(0.05)
        self._mock_ticket_counter += 1
        print(f"[BROKER MOCK] Order: {order.action} {order.volume} {order.symbol} @ {order.price}")
        return BrokerResult(
            success=True,
            ticket=self._mock_ticket_counter,
            error_code=None,
            error_message=None,
            executed_price=order.price,
            executed_volume=order.volume,
        )

    async def get_account_info(self) -> Optional[dict]:
        if self._mock_mode:
            return {
                "balance": 10000.0,
                "equity": 9950.0,
                "margin": 200.0,
                "free_margin": 9750.0,
                "margin_level": 4975.0,
                "profit": -50.0,
            }

        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, mt5.account_info)
        if info is None:
            return None
        return info._asdict()

    async def get_open_positions(self) -> list[dict]:
        if self._mock_mode:
            return []

        loop = asyncio.get_event_loop()
        positions = await loop.run_in_executor(None, mt5.positions_get)
        if positions is None:
            return []
        return [p._asdict() for p in positions]

    async def close_position(self, ticket: int) -> BrokerResult:
        if self._mock_mode:
            print(f"[BROKER MOCK] Close position ticket: {ticket}")
            return BrokerResult(
                success=True, ticket=ticket,
                error_code=None, error_message=None,
                executed_price=0.0, executed_volume=0.0,
            )

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._close_position_sync, ticket)

    def _close_position_sync(self, ticket: int) -> BrokerResult:
        position = mt5.positions_get(ticket=ticket)
        if not position:
            return BrokerResult(
                success=False, ticket=ticket,
                error_code=-3, error_message="position_not_found",
                executed_price=None, executed_volume=None,
            )

        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY
        tick = mt5.symbol_info_tick(pos.symbol)
        price = tick.bid if close_type == mt5.ORDER_TYPE_SELL else tick.ask

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": pos.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": 10,
            "magic": pos.magic,
            "comment": "close",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)

        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return BrokerResult(
                success=True, ticket=result.order,
                error_code=None, error_message=None,
                executed_price=result.price, executed_volume=result.volume,
            )
        else:
            return BrokerResult(
                success=False, ticket=None,
                error_code=result.retcode, error_message=result.comment,
                executed_price=None, executed_volume=None,
            )


broker = MT5Bridge()
