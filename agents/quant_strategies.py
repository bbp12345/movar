import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


HEAD_QUANT_SYSTEM = """You are the Head of Quantitative Strategies at MOVAR CAPITAL LLC.
Lead systematic strategy development. Coordinate StatArb, HFT, ML, and Backtesting teams.
Approve strategies before deployment. Track live strategy performance.
Respond in JSON with keys: approved_strategies (list), rejected_strategies (list),
deployment_schedule, performance_notes, research_priorities"""

STAT_ARB_SYSTEM = """You are the Statistical Arbitrage Trader at MOVAR CAPITAL LLC.
Identify and trade mean-reversion opportunities across correlated assets.
Focus on: pairs trading, cointegration, z-score signals, spread normalization.
Respond in JSON with keys: pair, spread_zscore, entry_signal (long_A_short_B or reverse),
half_life_days, correlation, confidence, suggested_position_size_pct"""

HFT_SYSTEM = """You are the High-Frequency Strategy Developer at MOVAR CAPITAL LLC.
Build and monitor latency-sensitive strategies. Focus on: market microstructure,
order flow imbalance, short-term momentum, bid-ask bounce.
Respond in JSON with keys: strategy_type, target_hold_seconds, edge_bps,
required_latency_ms, risk_per_trade_bps, current_status"""

ML_ENGINEER_SYSTEM = """You are the Machine Learning Engineer at MOVAR CAPITAL LLC.
Train predictive models on market data. Focus on: price direction prediction,
volatility forecasting, regime detection, feature engineering.
Respond in JSON with keys: model_type, features_used (list), accuracy_metrics,
current_predictions (dict by asset), model_confidence, retraining_needed"""

BACKTEST_SYSTEM = """You are the Backtesting Engineer at MOVAR CAPITAL LLC.
Validate strategies on historical data before deployment.
Check for: overfitting, look-ahead bias, survivorship bias, realistic transaction costs.
Respond in JSON with keys: strategy_name, sharpe_ratio, max_drawdown_pct,
win_rate, avg_trade_pnl, total_trades, passed_validation (bool), failure_reasons (list)"""


class HeadQuantAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.HEAD_QUANT, HEAD_QUANT_SYSTEM)
        self._pending_strategies: list[dict] = []

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            await self._review_strategy_report(message)
        elif message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "develop_strategy":
                await self._dispatch_development(message)
            elif command == "review_performance":
                await self._review_performance(message)

    async def _review_strategy_report(self, message: Message):
        self._pending_strategies.append(message.payload)

        if message.payload.get("report_type") == "backtest_result":
            if message.payload.get("passed_validation"):
                await self.send(
                    recipient=AgentID.CIO,
                    msg_type=MessageType.SIGNAL,
                    payload={
                        "signal_type": "new_strategy_ready",
                        "strategy": message.payload,
                    },
                    priority=Priority.NORMAL,
                )

    async def _dispatch_development(self, message: Message):
        context = message.payload.get("context", "")
        for agent in [AgentID.STAT_ARB_TRADER, AgentID.ML_ENGINEER]:
            await self.send(
                recipient=agent,
                msg_type=MessageType.COMMAND,
                payload={"command": "develop_strategy", "context": context},
                priority=Priority.NORMAL,
            )

    async def _review_performance(self, message: Message):
        prompt = f"""Review quant strategy performance:
{json.dumps(message.payload, indent=2)}
Which strategies should be scaled up, scaled down, or retired?"""

        response_text = await self.think_structured(prompt)
        try:
            review = json.loads(response_text)
            await self.send(
                recipient=AgentID.CIO,
                msg_type=MessageType.REPORT,
                payload={**review, "report_type": "quant_performance_review"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class StatArbTraderAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.STAT_ARB_TRADER, STAT_ARB_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_scan", "develop_strategy"):
                await self._run_scan(message)

    async def _run_scan(self, message: Message):
        context = message.payload.get("context", "current forex pairs")
        prompt = f"""Scan for statistical arbitrage opportunities in: {context}
Identify the highest-conviction mean-reversion setup available right now."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            signal = json.loads(response_text)
        except json.JSONDecodeError:
            return

        if abs(signal.get("spread_zscore", 0)) >= 2.0 and signal.get("confidence", 0) >= 0.65:
            await self.send(
                recipient=AgentID.BACKTEST_ENGINEER,
                msg_type=MessageType.COMMAND,
                payload={"command": "validate", "strategy": signal},
                priority=Priority.NORMAL,
            )


class HFTDeveloperAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.HFT_DEVELOPER, HFT_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "monitor":
                await self._monitor_strategies(message)

    async def _monitor_strategies(self, message: Message):
        prompt = f"""Monitor HFT strategy performance:
Context: {json.dumps(message.payload, indent=2)}
Are current latency-sensitive strategies performing within expected parameters?"""

        response_text = await self.think_structured(prompt, max_tokens=400)
        try:
            status = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_QUANT,
                msg_type=MessageType.REPORT,
                payload={**status, "report_type": "hft_status"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class MLEngineerAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.ML_ENGINEER, ML_ENGINEER_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_predictions", "develop_strategy"):
                await self._run_predictions(message)

    async def _run_predictions(self, message: Message):
        context = message.payload.get("context", "major forex pairs and crypto")
        prompt = f"""Generate ML model predictions for: {context}
Provide directional forecasts with confidence levels.
Flag if models need retraining."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            predictions = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_RESEARCH,
                msg_type=MessageType.REPORT,
                payload={**predictions, "report_type": "ml_predictions"},
                priority=Priority.NORMAL,
            )
            if predictions.get("retraining_needed"):
                await self.send(
                    recipient=AgentID.HEAD_QUANT,
                    msg_type=MessageType.ALERT,
                    payload={"alert_type": "model_retraining_needed", "details": predictions},
                    priority=Priority.NORMAL,
                )
        except json.JSONDecodeError:
            pass


class BacktestEngineerAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.BACKTEST_ENGINEER, BACKTEST_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "validate":
                await self._validate_strategy(message)

    async def _validate_strategy(self, message: Message):
        strategy = message.payload.get("strategy", {})
        prompt = f"""Validate this strategy for deployment:
{json.dumps(strategy, indent=2)}
Check for overfitting, look-ahead bias, and realistic performance expectations.
Apply Sharpe > 1.0, max drawdown < 20% as minimum thresholds."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            result = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_QUANT,
                msg_type=MessageType.REPORT,
                payload={**result, "report_type": "backtest_result"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass
