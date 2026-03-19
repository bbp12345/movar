import asyncio
import json
import time
import os
import certifi
import redis.asyncio as aioredis
from typing import Callable, Awaitable
from dotenv import load_dotenv
from core.message import Message, AgentID, MessageType, Priority

load_dotenv()

STREAM_KEY = "movar:bus"
AUDIT_KEY = "movar:audit"
STATE_KEY = "movar:state"
DEAD_LETTER_KEY = "movar:dead_letter"
ACK_PREFIX = "movar:ack:"


class MessageBus:
    def __init__(self):
        self.redis: aioredis.Redis = None
        self._handlers: dict[str, list[Callable]] = {}
        self._agent_id: AgentID = AgentID.BUS
        self._running = False
        self._kill_switch_active = False

    async def connect(self):
        url = os.getenv("REDIS_URL") or (
            f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
        )
        kwargs = dict(
            password=os.getenv("REDIS_PASSWORD") or None,
            db=int(os.getenv("REDIS_DB", 0)),
            decode_responses=True,
        )
        if url.startswith("rediss://"):
            kwargs["ssl_ca_certs"] = certifi.where()
        self.redis = await aioredis.from_url(url, **kwargs)
        await self.redis.ping()
        print("[BUS] Connected to Redis")

    async def disconnect(self):
        self._running = False
        if self.redis:
            await self.redis.aclose()

    async def publish(self, message: Message) -> str:
        if self._kill_switch_active and message.msg_type != MessageType.KILL_SWITCH:
            if message.sender not in (AgentID.HUMAN, AgentID.CRO, AgentID.RISK_GATE):
                await self._dead_letter(message, reason="kill_switch_active")
                return None

        entry = message.to_redis()
        entry["payload"] = json.dumps(message.payload)

        msg_id = await self.redis.xadd(STREAM_KEY, entry)
        await self._write_audit(message, msg_id)

        if message.msg_type == MessageType.KILL_SWITCH:
            self._kill_switch_active = True
            await self.redis.set("movar:kill_switch", "1")
            print(f"[BUS] ⚠️  KILL SWITCH ACTIVATED by {message.sender}")

        return msg_id

    async def subscribe(self, agent_id: AgentID, handler: Callable[[Message], Awaitable[None]]):
        group = f"group:{agent_id.value if hasattr(agent_id, 'value') else agent_id}"
        consumer = str(agent_id.value if hasattr(agent_id, 'value') else agent_id)

        try:
            await self.redis.xgroup_create(STREAM_KEY, group, id="0", mkstream=True)
        except Exception:
            pass

        self._running = True
        print(f"[BUS] Agent {consumer} subscribed")

        while self._running:
            try:
                entries = await self.redis.xreadgroup(
                    groupname=group,
                    consumername=consumer,
                    streams={STREAM_KEY: ">"},
                    count=10,
                    block=100,
                )

                if not entries:
                    await asyncio.sleep(0.01)
                    continue

                for _, messages in entries:
                    for msg_id, data in messages:
                        try:
                            msg = Message.from_redis(data)

                            if msg.recipient not in (
                                agent_id,
                                AgentID.BUS,
                                "broadcast",
                            ):
                                await self.redis.xack(STREAM_KEY, group, msg_id)
                                continue

                            await handler(msg)
                            await self.redis.xack(STREAM_KEY, group, msg_id)

                            if msg.requires_ack:
                                await self.redis.set(
                                    f"{ACK_PREFIX}{msg.id}",
                                    "acked",
                                    ex=300,
                                )
                        except Exception as e:
                            print(f"[BUS] Handler error for {msg_id}: {e}")
                            await self.redis.xack(STREAM_KEY, group, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[BUS] Subscription error: {e}")
                await asyncio.sleep(1)

    async def get_state(self, key: str):
        val = await self.redis.hget(STATE_KEY, key)
        if val:
            try:
                return json.loads(val)
            except Exception:
                return val
        return None

    async def set_state(self, key: str, value):
        await self.redis.hset(STATE_KEY, key, json.dumps(value))

    async def get_audit_log(self, count: int = 100) -> list[dict]:
        entries = await self.redis.xrevrange(AUDIT_KEY, count=count)
        result = []
        for entry_id, data in entries:
            data["_redis_id"] = entry_id
            result.append(data)
        return result

    async def _write_audit(self, message: Message, redis_id: str):
        audit_entry = {
            "msg_id": message.id,
            "redis_id": redis_id,
            "sender": str(message.sender.value if hasattr(message.sender, 'value') else message.sender),
            "recipient": str(message.recipient.value if hasattr(message.recipient, 'value') else message.recipient),
            "msg_type": str(message.msg_type.value if hasattr(message.msg_type, 'value') else message.msg_type),
            "priority": str(message.priority),
            "timestamp": str(message.timestamp),
            "payload_keys": json.dumps(list(message.payload.keys())),
        }
        await self.redis.xadd(AUDIT_KEY, audit_entry)

    async def _dead_letter(self, message: Message, reason: str):
        entry = message.to_redis()
        entry["dead_reason"] = reason
        entry["payload"] = json.dumps(message.payload)
        await self.redis.xadd(DEAD_LETTER_KEY, entry)
        print(f"[BUS] Dead letter: {message.id} — {reason}")

    async def health_check(self) -> dict:
        try:
            await self.redis.ping()
            stream_len = await self.redis.xlen(STREAM_KEY)
            audit_len = await self.redis.xlen(AUDIT_KEY)
            kill_switch = await self.redis.get("movar:kill_switch")
            return {
                "status": "ok",
                "stream_length": stream_len,
                "audit_length": audit_len,
                "kill_switch_active": kill_switch == "1",
                "timestamp": time.time(),
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}


bus = MessageBus()
