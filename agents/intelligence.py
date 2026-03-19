import json
from agents.base import BaseAgent
from core.message import Message, AgentID, MessageType, Priority


MACRO_INTEL_SYSTEM = """You are the Macro Intelligence Analyst at MOVAR CAPITAL LLC.
Track central bank policy, geopolitical events, and economic data releases.
Monitor: Fed/ECB/BOJ decisions, CPI/NFP/GDP releases, geopolitical risk, yield curves.
Respond in JSON with keys: macro_regime (risk_on/risk_off/neutral), key_events (list),
central_bank_bias (dict by bank), yield_curve_signal, actionable_themes (list)"""

MICROSTRUCTURE_SYSTEM = """You are the Market Microstructure Analyst at MOVAR CAPITAL LLC.
Monitor order flow, bid-ask spreads, and market depth.
Track: dark pool prints, block trades, order flow imbalance, toxic flow signals.
Respond in JSON with keys: order_flow_signal (buy_heavy/sell_heavy/balanced),
spread_environment (tight/normal/wide), depth_quality (good/thin/poor),
microstructure_alerts (list), short_term_direction_bias"""

COMPETITOR_INTEL_SYSTEM = """You are the Competitor Intelligence Analyst at MOVAR CAPITAL LLC.
Track positioning and behavior of major market participants.
Monitor: COT reports, large trader positioning, hedge fund 13F filings, smart money flow.
Respond in JSON with keys: institutional_bias (dict by asset), crowded_trades (list),
contrarian_opportunity (bool), smart_money_flows (list), positioning_extremes"""

EARNINGS_MONITOR_SYSTEM = """You are the Earnings & Events Monitor at MOVAR CAPITAL LLC.
Track scheduled catalysts across all asset classes.
Monitor: earnings calendars, economic data releases, central bank meetings, geopolitical events.
Respond in JSON with keys: upcoming_events (list with date/asset/expected_impact),
high_impact_next_48h (list), recommended_position_adjustments (list),
events_to_fade (list), events_to_follow (list)"""


class MacroIntelAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.MACRO_INTELLIGENCE, MACRO_INTEL_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_scan", "macro_update"):
                await self._run_macro_scan(message)

    async def _run_macro_scan(self, message: Message):
        prompt = f"""Analyze current macro environment:
Context: {json.dumps(message.payload, indent=2)}
What is the macro regime and what are the highest-conviction themes?"""

        response_text = await self.think_structured(prompt, max_tokens=700)
        try:
            analysis = json.loads(response_text)
        except json.JSONDecodeError:
            return

        await self.send(
            recipient=AgentID.HEAD_RESEARCH,
            msg_type=MessageType.REPORT,
            payload={**analysis, "report_type": "macro_intelligence"},
            priority=Priority.NORMAL,
        )

        if analysis.get("macro_regime") == "risk_off":
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={
                    "alert_type": "macro_risk_off_signal",
                    "regime": analysis.get("macro_regime"),
                    "key_events": analysis.get("key_events", []),
                },
                priority=Priority.HIGH,
            )


class MicrostructureAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.MICROSTRUCTURE, MICROSTRUCTURE_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_scan":
                await self._run_scan(message)

    async def _run_scan(self, message: Message):
        prompt = f"""Analyze market microstructure:
Context: {json.dumps(message.payload, indent=2)}
What does order flow and market depth signal about short-term direction?"""

        response_text = await self.think_structured(prompt, max_tokens=500)
        try:
            analysis = json.loads(response_text)
        except json.JSONDecodeError:
            return

        await self.send(
            recipient=AgentID.HEAD_TRADER,
            msg_type=MessageType.REPORT,
            payload={**analysis, "report_type": "microstructure_signal"},
            priority=Priority.NORMAL,
        )


class CompetitorIntelAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.COMPETITOR_INTEL, COMPETITOR_INTEL_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") == "run_scan":
                await self._run_scan(message)

    async def _run_scan(self, message: Message):
        prompt = f"""Analyze institutional positioning and smart money flow:
Context: {json.dumps(message.payload, indent=2)}
Where is smart money positioned? Are there crowded trades to fade?"""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            analysis = json.loads(response_text)
        except json.JSONDecodeError:
            return

        await self.send(
            recipient=AgentID.HEAD_RESEARCH,
            msg_type=MessageType.REPORT,
            payload={**analysis, "report_type": "competitor_intelligence"},
            priority=Priority.NORMAL,
        )

        if analysis.get("contrarian_opportunity"):
            await self.send(
                recipient=AgentID.CIO,
                msg_type=MessageType.SIGNAL,
                payload={
                    "signal_type": "contrarian_opportunity",
                    "crowded_trades": analysis.get("crowded_trades", []),
                    "positioning_extremes": analysis.get("positioning_extremes"),
                },
                priority=Priority.NORMAL,
            )


class EarningsMonitorAgent(BaseAgent):
    def __init__(self):
        super().__init__(AgentID.EARNINGS_MONITOR, EARNINGS_MONITOR_SYSTEM)

    async def handle(self, message: Message):
        if message.msg_type == MessageType.COMMAND:
            if message.payload.get("command") in ("run_scan", "check_calendar"):
                await self._check_calendar(message)

    async def _check_calendar(self, message: Message):
        prompt = f"""Review upcoming market catalysts and events:
Context: {json.dumps(message.payload, indent=2)}
What high-impact events are coming in the next 48 hours that require position adjustments?"""

        response_text = await self.think_structured(prompt, max_tokens=600)
        try:
            calendar = json.loads(response_text)
        except json.JSONDecodeError:
            return

        await self.send(
            recipient=AgentID.HEAD_RESEARCH,
            msg_type=MessageType.REPORT,
            payload={**calendar, "report_type": "events_calendar"},
            priority=Priority.NORMAL,
        )

        if calendar.get("high_impact_next_48h"):
            await self.send(
                recipient=AgentID.CRO,
                msg_type=MessageType.ALERT,
                payload={
                    "alert_type": "high_impact_events_upcoming",
                    "events": calendar.get("high_impact_next_48h"),
                    "recommended_adjustments": calendar.get("recommended_position_adjustments"),
                },
                priority=Priority.NORMAL,
            )
