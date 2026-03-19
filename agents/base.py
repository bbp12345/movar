import asyncio
import os
import time
from abc import ABC, abstractmethod
from anthropic import AsyncAnthropic
from core.bus import bus
from core.message import Message, AgentID, MessageType, Priority


class BaseAgent(ABC):
    def __init__(self, agent_id: AgentID, system_prompt: str):
        self.agent_id = agent_id
        self.system_prompt = system_prompt
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self._message_history: list[dict] = []
        self._running = False
        self._last_heartbeat = 0.0
        self.heartbeat_interval = 30

    async def start(self):
        self._running = True
        await asyncio.gather(
            bus.subscribe(self.agent_id, self._handle_message),
            self._heartbeat_loop(),
        )

    async def stop(self):
        self._running = False

    async def send(
        self,
        recipient: AgentID,
        msg_type: MessageType,
        payload: dict,
        priority: Priority = Priority.NORMAL,
        correlation_id: str = None,
        requires_ack: bool = False,
    ):
        msg = Message(
            sender=self.agent_id,
            recipient=recipient,
            msg_type=msg_type,
            priority=priority,
            payload=payload,
            correlation_id=correlation_id,
            requires_ack=requires_ack,
        )
        await bus.publish(msg)
        return msg

    async def _handle_message(self, message: Message):
        if message.msg_type == MessageType.KILL_SWITCH:
            await self._on_kill_switch(message)
            return

        if message.msg_type == MessageType.RISK_BREACH:
            await self._on_risk_breach(message)
            return

        await self.handle(message)

    @abstractmethod
    async def handle(self, message: Message):
        pass

    async def _on_kill_switch(self, message: Message):
        self._running = False
        print(f"[{self.agent_id}] Kill switch received — halting")

    async def _on_risk_breach(self, message: Message):
        print(f"[{self.agent_id}] Risk breach alert: {message.payload}")

    async def think(self, user_content: str, max_tokens: int = 1000) -> str:
        self._message_history.append({"role": "user", "content": user_content})

        if len(self._message_history) > 20:
            self._message_history = self._message_history[-20:]

        agent_str = str(self.agent_id.value if hasattr(self.agent_id, "value") else self.agent_id)
        t0 = time.time()

        # Mark agent as actively thinking (visible in dashboard)
        try:
            await bus.redis.set(f"movar:thinking:{agent_str}", "1", ex=30)
        except Exception:
            pass

        try:
            response = await self.client.messages.create(
                model="claude-sonnet-4-5",
                max_tokens=max_tokens,
                system=self.system_prompt,
                messages=self._message_history,
            )
            reply = response.content[0].text
        finally:
            try:
                await bus.redis.delete(f"movar:thinking:{agent_str}")
            except Exception:
                pass

        duration_ms = int((time.time() - t0) * 1000)
        self._message_history.append({"role": "assistant", "content": reply})

        # Log reasoning to Redis stream for dashboard
        try:
            await bus.redis.xadd(
                "movar:thoughts",
                {
                    "agent": agent_str,
                    "prompt": user_content[:300],
                    "response": reply[:500],
                    "duration_ms": str(duration_ms),
                    "ts": str(time.time()),
                },
                maxlen=200,
            )
        except Exception:
            pass

        return reply

    async def think_structured(self, user_content: str, max_tokens: int = 1000) -> str:
        prompt = f"{user_content}\n\nRespond ONLY with valid JSON. No markdown, no preamble."
        return await self.think(prompt, max_tokens)

    def clear_history(self):
        self._message_history = []

    async def _heartbeat_loop(self):
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            if not self._running:
                break
            now = time.time()
            agent_str = str(self.agent_id.value if hasattr(self.agent_id, "value") else self.agent_id)
            try:
                await bus.redis.set(f"movar:heartbeat:{agent_str}", str(now), ex=120)
            except Exception:
                pass
            await self.send(
                recipient=AgentID.BUS,
                msg_type=MessageType.HEARTBEAT,
                payload={"agent": agent_str, "timestamp": now, "status": "alive"},
                priority=Priority.LOW,
            )
