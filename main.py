import asyncio
import os
import signal
import time
from pathlib import Path
from dotenv import load_dotenv

# Load .env before any project modules read os.getenv()
load_dotenv(Path(__file__).parent / ".env", override=True)

from core.bus import bus
from core.message import AgentID, MessageType, Priority, Message
from broker.mt5_bridge import broker

from agents.cro import CROAgent
from agents.forex import PMForexAgent, TraderForexAgent
from agents.risk_gate_agent import RiskGateAgent
from agents.trade_ops import TradeOpsAgent
from agents.executive import CEOAgent, CIOAgent
from agents.executive_ops import CTOAgent, CFOAgent
from agents.portfolio import PMEquitiesAgent, PMCryptoAgent, PMCommoditiesAgent, PMDerivativesAgent
from agents.research import (
    HeadResearchAgent, QuantAnalystAgent, FundamentalAnalystAgent,
    SentimentAnalystAgent, AltDataAnalystAgent,
)
from agents.trading_desk import (
    HeadTraderAgent, TraderEquitiesAgent, TraderCryptoAgent, TraderDerivativesAgent,
)
from agents.risk_management import (
    MarketRiskAgent, LiquidityRiskAgent, CounterpartyRiskAgent, DrawdownMonitorAgent,
)
from agents.quant_strategies import (
    HeadQuantAgent, StatArbTraderAgent, HFTDeveloperAgent,
    MLEngineerAgent, BacktestEngineerAgent,
)
from agents.operations import (
    HeadOperationsAgent, ComplianceAgent, TaxAccountingAgent, DataEngineerAgent,
)
from agents.intelligence import (
    MacroIntelAgent, MicrostructureAgent, CompetitorIntelAgent, EarningsMonitorAgent,
)

class MOVAR:
    def __init__(self):
        self.agents: dict[str, object] = {}
        self._shutdown_event = asyncio.Event()

    def register(self, agent):
        self.agents[str(agent.agent_id)] = agent
        return agent

    async def boot(self):
        print("\n" + "=" * 60)
        print("  MOVAR CAPITAL — Agent Framework Booting")
        print("=" * 60)

        print("[BOOT] Connecting to Redis...")
        await bus.connect()
        print("[BOOT] Redis connected ✓")

        print("[BOOT] Connecting to broker...")
        connected = await broker.connect()
        print(f"[BOOT] Broker {'connected ✓' if connected else 'in mock mode ⚠️'}")

        self._register_all_agents()
        print(f"[BOOT] {len(self.agents)} agents registered")
        print("[BOOT] Starting agent loops...\n")

        tasks = [asyncio.create_task(agent.start()) for agent in self.agents.values()]
        tasks += [
            asyncio.create_task(self._health_monitor()),
            asyncio.create_task(self._account_sync_loop()),
            asyncio.create_task(self._intelligence_cycle()),
            asyncio.create_task(self._ops_cycle()),
        ]

        await self._shutdown_event.wait()

        print("\n[SHUTDOWN] Graceful shutdown initiated...")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await broker.disconnect()
        await bus.disconnect()
        print("[SHUTDOWN] Done.")

    def _register_all_agents(self):
        for agent in [
            RiskGateAgent(),
            CEOAgent(), CIOAgent(), CROAgent(), CTOAgent(), CFOAgent(),
            PMForexAgent(), PMEquitiesAgent(), PMCryptoAgent(),
            PMCommoditiesAgent(), PMDerivativesAgent(),
            HeadResearchAgent(), QuantAnalystAgent(), FundamentalAnalystAgent(),
            SentimentAnalystAgent(), AltDataAnalystAgent(),
            HeadTraderAgent(), TraderForexAgent(), TraderEquitiesAgent(),
            TraderCryptoAgent(), TraderDerivativesAgent(),
            MarketRiskAgent(), LiquidityRiskAgent(), CounterpartyRiskAgent(),
            DrawdownMonitorAgent(),
            HeadQuantAgent(), StatArbTraderAgent(), HFTDeveloperAgent(),
            MLEngineerAgent(), BacktestEngineerAgent(),
            HeadOperationsAgent(), TradeOpsAgent(), ComplianceAgent(),
            TaxAccountingAgent(), DataEngineerAgent(),
            MacroIntelAgent(), MicrostructureAgent(),
            CompetitorIntelAgent(), EarningsMonitorAgent(),
        ]:
            self.register(agent)

    async def _health_monitor(self):
        while True:
            await asyncio.sleep(60)
            health = await bus.health_check()
            kill = health.get("kill_switch_active", False)
            print(
                f"[HEALTH] Bus: {health.get('status')} | "
                f"Kill: {kill} | "
                f"Audit: {health.get('audit_length', 0)} entries"
            )
            if kill:
                print("[HEALTH] ⚠️  Kill switch active — trading halted")

    async def _account_sync_loop(self):
        while True:
            await asyncio.sleep(30)
            account = await broker.get_account_info()
            positions = await broker.get_open_positions()
            if account:
                msg = Message(
                    sender=AgentID.BUS,
                    recipient=AgentID.CRO,
                    msg_type=MessageType.REPORT,
                    payload={
                        "report_type": "account_update",
                        "equity": account.get("equity", 0),
                        "balance": account.get("balance", 0),
                        "open_positions": len(positions),
                        "daily_pnl": account.get("profit", 0),
                        "timestamp": time.time(),
                    },
                )
                await bus.publish(msg)

    async def _intelligence_cycle(self):
        await asyncio.sleep(10)
        while True:
            for agent_id in [
                AgentID.MACRO_INTELLIGENCE,
                AgentID.EARNINGS_MONITOR,
                AgentID.COMPETITOR_INTEL,
                AgentID.MICROSTRUCTURE,
                AgentID.QUANT_ANALYST,
                AgentID.ML_ENGINEER,
            ]:
                msg = Message(
                    sender=AgentID.BUS,
                    recipient=agent_id,
                    msg_type=MessageType.COMMAND,
                    payload={"command": "run_scan", "context": "current market"},
                )
                await bus.publish(msg)
                await asyncio.sleep(2)
            await asyncio.sleep(3600)

    async def _ops_cycle(self):
        await asyncio.sleep(15)
        while True:
            msg = Message(
                sender=AgentID.BUS,
                recipient=AgentID.HEAD_OPERATIONS,
                msg_type=MessageType.COMMAND,
                payload={"command": "daily_ops_check"},
            )
            await bus.publish(msg)
            await asyncio.sleep(86400)

    def shutdown(self):
        print("\n[SIGNAL] Shutdown requested")
        self._shutdown_event.set()


async def main():
    firm = MOVAR()
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, firm.shutdown)
    loop.add_signal_handler(signal.SIGTERM, firm.shutdown)
    await firm.boot()


if __name__ == "__main__":
    asyncio.run(main())
