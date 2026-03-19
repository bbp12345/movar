from enum import Enum
from typing import Any
from pydantic import BaseModel, field_validator
import uuid
import time
import json


class Priority(int, Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3


class MessageType(str, Enum):
    COMMAND = "COMMAND"
    SIGNAL = "SIGNAL"
    ALERT = "ALERT"
    REPORT = "REPORT"
    ORDER_REQUEST = "ORDER_REQUEST"
    ORDER_VALIDATED = "ORDER_VALIDATED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXECUTED = "ORDER_EXECUTED"
    RISK_BREACH = "RISK_BREACH"
    KILL_SWITCH = "KILL_SWITCH"
    HEARTBEAT = "HEARTBEAT"


class AgentID(str, Enum):
    CEO = "ceo"
    CIO = "cio"
    CRO = "cro"
    CTO = "cto"
    CFO = "cfo"
    PM_EQUITIES = "pm_equities"
    PM_CRYPTO = "pm_crypto"
    PM_FOREX = "pm_forex"
    PM_COMMODITIES = "pm_commodities"
    PM_DERIVATIVES = "pm_derivatives"
    HEAD_RESEARCH = "head_research"
    QUANT_ANALYST = "quant_analyst"
    FUNDAMENTAL_ANALYST = "fundamental_analyst"
    SENTIMENT_ANALYST = "sentiment_analyst"
    ALT_DATA_ANALYST = "alt_data_analyst"
    HEAD_TRADER = "head_trader"
    TRADER_EQUITIES = "trader_equities"
    TRADER_CRYPTO = "trader_crypto"
    TRADER_FOREX = "trader_forex"
    TRADER_DERIVATIVES = "trader_derivatives"
    MARKET_RISK = "market_risk"
    LIQUIDITY_RISK = "liquidity_risk"
    COUNTERPARTY_RISK = "counterparty_risk"
    DRAWDOWN_MONITOR = "drawdown_monitor"
    HEAD_QUANT = "head_quant"
    STAT_ARB_TRADER = "stat_arb_trader"
    HFT_DEVELOPER = "hft_developer"
    ML_ENGINEER = "ml_engineer"
    BACKTEST_ENGINEER = "backtest_engineer"
    HEAD_OPERATIONS = "head_operations"
    TRADE_OPS = "trade_ops"
    COMPLIANCE = "compliance"
    TAX_ACCOUNTING = "tax_accounting"
    DATA_ENGINEER = "data_engineer"
    MACRO_INTELLIGENCE = "macro_intelligence"
    MICROSTRUCTURE = "microstructure"
    COMPETITOR_INTEL = "competitor_intel"
    EARNINGS_MONITOR = "earnings_monitor"
    RISK_GATE = "risk_gate"
    BUS = "bus"
    HUMAN = "human"


AUTHORITY_HIERARCHY = {
    AgentID.HUMAN: 0,
    AgentID.CRO: 1,
    AgentID.CEO: 2,
    AgentID.CIO: 2,
    AgentID.CTO: 2,
    AgentID.CFO: 2,
    AgentID.RISK_GATE: 3,
    AgentID.HEAD_TRADER: 4,
    AgentID.HEAD_RESEARCH: 4,
    AgentID.HEAD_QUANT: 4,
    AgentID.HEAD_OPERATIONS: 4,
}


class Message(BaseModel):
    id: str | None = None
    sender: AgentID
    recipient: AgentID
    msg_type: MessageType
    priority: Priority = Priority.NORMAL
    payload: dict[str, Any] = {}
    timestamp: float | None = None
    correlation_id: str | None = None
    requires_ack: bool = False

    model_config = {"use_enum_values": True}

    def model_post_init(self, __context):
        if self.id is None:
            self.id = str(uuid.uuid4())
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_redis(self) -> dict:
        # mode="json" forces all enum fields to their raw primitive values
        # so Priority.NORMAL → 2, not "Priority.NORMAL"
        return {k: str(v) for k, v in self.model_dump(mode="json").items()}

    @classmethod
    def from_redis(cls, data: dict) -> "Message":
        parsed = {}
        for k, v in data.items():
            if k == "payload":
                try:
                    parsed[k] = json.loads(v)
                except Exception:
                    parsed[k] = {}
            elif k == "priority":
                try:
                    parsed[k] = int(v)
                except ValueError:
                    # Handle legacy "Priority.NORMAL" format
                    parsed[k] = Priority[v.split(".")[-1]]
            elif k == "requires_ack":
                parsed[k] = v == "True"
            elif k == "timestamp":
                parsed[k] = float(v)
            else:
                parsed[k] = v
        return cls(**parsed)
