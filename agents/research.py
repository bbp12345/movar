import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


HEAD_RESEARCH_SYSTEM = """You are the Head of Research at MOVAR CAPITAL LLC.
Prioritize the research agenda, validate analyst outputs, synthesize insights into actionable signals.
Coordinate Quant, Fundamental, Sentiment, and Alt Data analysts.
Respond in JSON with keys: research_priority, validated_signals (list), synthesis, recommended_actions"""

QUANT_SYSTEM = """You are the Quantitative Analyst at MOVAR CAPITAL LLC.
Build and backtest systematic strategies. Identify statistical edges.
Focus on: mean-reversion, momentum, cross-asset correlations, factor models.
Respond in JSON with keys: strategy_name, edge_type, expected_sharpe, win_rate, max_drawdown, signals, confidence"""

FUNDAMENTAL_SYSTEM = """You are the Fundamental Analyst at MOVAR CAPITAL LLC.
Evaluate macro trends, earnings, central bank policy, and asset fundamentals.
Respond in JSON with keys: asset, fundamental_view (bullish/bearish/neutral), key_drivers (list),
price_target, time_horizon, conviction (0-1), risks"""

SENTIMENT_SYSTEM = """You are the Sentiment Analyst at MOVAR CAPITAL LLC.
Monitor news, social signals, and market narrative shifts.
Track: fear/greed, positioning extremes, narrative momentum, options sentiment.
Respond in JSON with keys: overall_sentiment, asset_sentiments (dict), contrarian_signals (list),
narrative_shift (bool), recommended_fade_or_follow"""

ALT_DATA_SYSTEM = """You are the Alternative Data Analyst at MOVAR CAPITAL LLC.
Process non-traditional data: on-chain metrics, satellite imagery signals, web scraping trends.
Respond in JSON with keys: data_source, signal_type, asset, signal_direction, confidence (0-1),
alpha_decay_days, supporting_data_points"""


class HeadResearchAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.HEAD_RESEARCH, HEAD_RESEARCH_SYSTEM)
        self._pending_reports: list[dict] = []

    async def handle(self, message: Message):
        if message.msg_type == MessageType.REPORT:
            await self._collect_report(message)
        elif message.msg_type == MessageType.COMMAND:
            command = message.payload.get("command")
            if command == "generate_research_brief":
                await self._generate_brief(message)
            elif command == "dispatch_research":
                await self._dispatch_to_analysts(message)

    async def _collect_report(self, message: Message):
        self._pending_reports.append(message.payload)
        if len(self._pending_reports) >= 3:
            await self._synthesize_reports()

    async def _synthesize_reports(self):
        prompt = f"""Synthesize these analyst reports into actionable signals:
{json.dumps(self._pending_reports, indent=2)}
Validate consistency and identify the highest-conviction opportunities."""

        response_text = await self.think_structured(prompt, max_tokens=1000)
        try:
            synthesis = json.loads(response_text)
        except json.JSONDecodeError:
            self._pending_reports.clear()
            return

        for signal in synthesis.get("validated_signals", []):
            if signal.get("confidence", 0) >= 0.7:
                await self.send(
                    recipient=AgentID.CIO,
                    msg_type=MessageType.SIGNAL,
                    payload={"signal": signal, "synthesis": synthesis.get("synthesis")},
                    priority=Priority.NORMAL,
                )

        self._pending_reports.clear()

    async def _generate_brief(self, message: Message):
        await self._dispatch_to_analysts(message)

    async def _dispatch_to_analysts(self, message: Message):
        context = message.payload.get("context", "")
        for analyst in [
            AgentID.QUANT_ANALYST, AgentID.FUNDAMENTAL_ANALYST,
            AgentID.SENTIMENT_ANALYST, AgentID.ALT_DATA_ANALYST,
        ]:
            await self.send(
                recipient=analyst,
                msg_type=MessageType.COMMAND,
                payload={"command": "run_analysis", "context": context},
                priority=Priority.NORMAL,
            )


class QuantAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.QUANT_ANALYST, QUANT_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_analysis", "backtest"):
                await self._run_analysis(message)

    async def _run_analysis(self, message: Message):
        context = message.payload.get("context", "current market")
        prompt = f"""Run quantitative analysis for: {context}
Identify systematic edges with statistical backing.
Focus on strategies deployable in the next 1-5 trading days."""

        response_text = await self.think_structured(prompt, max_tokens=800)
        try:
            analysis = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_RESEARCH,
                msg_type=MessageType.REPORT,
                payload={**analysis, "report_type": "quant_analysis", "analyst": "quant"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class FundamentalAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.FUNDAMENTAL_ANALYST, FUNDAMENTAL_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_analysis":
                await self._run_analysis(message)

    async def _run_analysis(self, message: Message):
        context = message.payload.get("context", "current macro environment")
        prompt = f"""Perform fundamental analysis for: {context}
Evaluate macro trends, central bank policy, and key asset fundamentals.
Provide conviction-rated views."""

        response_text = await self.think_structured(prompt, max_tokens=800)
        try:
            analysis = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_RESEARCH,
                msg_type=MessageType.REPORT,
                payload={**analysis, "report_type": "fundamental_analysis", "analyst": "fundamental"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class SentimentAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.SENTIMENT_ANALYST, SENTIMENT_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_analysis":
                await self._run_analysis(message)

    async def _run_analysis(self, message: Message):
        context = message.payload.get("context", "current market sentiment")
        prompt = f"""Analyze market sentiment for: {context}
Evaluate news flow, social signals, positioning, and narrative momentum.
Identify contrarian opportunities or momentum confirms."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            analysis = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_RESEARCH,
                msg_type=MessageType.REPORT,
                payload={**analysis, "report_type": "sentiment_analysis", "analyst": "sentiment"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass


class AltDataAnalystAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.ALT_DATA_ANALYST, ALT_DATA_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_analysis":
                await self._run_analysis(message)

    async def _run_analysis(self, message: Message):
        context = message.payload.get("context", "")
        prompt = f"""Process alternative data signals for: {context}
Evaluate on-chain metrics, web trends, and non-traditional data sources.
Identify signals with alpha before they appear in traditional data."""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            analysis = json.loads(response_text)
            await self.send(
                recipient=AgentID.HEAD_RESEARCH,
                msg_type=MessageType.REPORT,
                payload={**analysis, "report_type": "alt_data_analysis", "analyst": "alt_data"},
                priority=Priority.NORMAL,
            )
        except json.JSONDecodeError:
            pass
