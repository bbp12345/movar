import asyncio
import json
import os
import time
import certifi
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import redis.asyncio as aioredis
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, StreamingResponse

load_dotenv(Path(__file__).parent.parent / ".env", override=True)

STREAM_KEY = "movar:bus"
AUDIT_KEY = "movar:audit"
STATE_KEY = "movar:state"

AGENT_IDS = [
    "ceo", "cio", "cro", "cto", "cfo",
    "pm_equities", "pm_crypto", "pm_forex", "pm_commodities", "pm_derivatives",
    "head_research", "quant_analyst", "fundamental_analyst", "sentiment_analyst", "alt_data_analyst",
    "head_trader", "trader_equities", "trader_crypto", "trader_forex", "trader_derivatives",
    "market_risk", "liquidity_risk", "counterparty_risk", "drawdown_monitor",
    "head_quant", "stat_arb_trader", "hft_developer", "ml_engineer", "backtest_engineer",
    "head_operations", "trade_ops", "compliance", "tax_accounting", "data_engineer",
    "macro_intelligence", "microstructure", "competitor_intel", "earnings_monitor",
]

_redis: aioredis.Redis = None


def _redis_url() -> str:
    return os.getenv("REDIS_URL") or (
        f"redis://{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', 6379)}"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    url = _redis_url()
    kwargs = dict(
        password=os.getenv("REDIS_PASSWORD") or None,
        db=int(os.getenv("REDIS_DB", 0)),
        decode_responses=True,
    )
    if url.startswith("rediss://"):
        kwargs["ssl_ca_certs"] = certifi.where()
    _redis = await aioredis.from_url(url, **kwargs)
    yield
    await _redis.aclose()


app = FastAPI(title="MOVAR CAPITAL Dashboard", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/status")
async def get_status():
    try:
        await _redis.ping()
        stream_len = await _redis.xlen(STREAM_KEY)
        audit_len = await _redis.xlen(AUDIT_KEY)
        kill_switch = await _redis.get("movar:kill_switch")
        return {
            "redis": "ok",
            "stream_length": stream_len,
            "audit_length": audit_len,
            "kill_switch_active": kill_switch == "1",
            "timestamp": time.time(),
        }
    except Exception as e:
        return {"redis": "error", "error": str(e)}


@app.get("/api/agents")
async def get_agents():
    now = time.time()
    agents = []
    for agent_id in AGENT_IDS:
        last_beat_raw = await _redis.get(f"movar:heartbeat:{agent_id}")
        last_beat = float(last_beat_raw) if last_beat_raw else None
        lag = now - last_beat if last_beat else None

        if last_beat is None:
            status = "unknown"
        elif lag < 45:
            status = "alive"
        elif lag < 120:
            status = "slow"
        else:
            status = "dead"

        alert_raw = await _redis.get(f"movar:agent_alert:{agent_id}")

        agents.append({
            "id": agent_id,
            "status": status,
            "last_heartbeat": last_beat,
            "lag_seconds": round(lag, 1) if lag else None,
            "alert": alert_raw,
        })
    return agents


@app.get("/api/account")
async def get_account():
    raw = await _redis.hgetall(STATE_KEY)
    account_raw = raw.get("account_update")
    if account_raw:
        try:
            return json.loads(account_raw)
        except Exception:
            pass
    return {
        "equity": 0, "balance": 0,
        "open_positions": 0, "daily_pnl": 0,
        "timestamp": None,
    }


@app.get("/api/positions")
async def get_positions():
    raw = await _redis.get("movar:positions")
    if raw:
        return json.loads(raw)
    return []


@app.get("/api/audit")
async def get_audit(limit: int = 50):
    entries = await _redis.xrevrange(AUDIT_KEY, count=limit)
    result = []
    for entry_id, data in entries:
        result.append({
            "id": entry_id,
            "sender": data.get("sender", ""),
            "recipient": data.get("recipient", ""),
            "msg_type": data.get("msg_type", ""),
            "priority": data.get("priority", ""),
            "timestamp": data.get("timestamp", ""),
            "payload_keys": data.get("payload_keys", "[]"),
        })
    return result


@app.get("/api/risk")
async def get_risk():
    kill_switch = await _redis.get("movar:kill_switch")
    dead_letter_len = await _redis.xlen("movar:dead_letter") if await _redis.exists("movar:dead_letter") else 0
    rejected = await _redis.get("movar:risk_gate:rejected_today")
    validated = await _redis.get("movar:risk_gate:validated_today")
    drawdown = await _redis.get("movar:drawdown_pct")
    daily_loss = await _redis.get("movar:daily_loss")
    return {
        "kill_switch_active": kill_switch == "1",
        "dead_letter_count": dead_letter_len,
        "orders_rejected_today": int(rejected or 0),
        "orders_validated_today": int(validated or 0),
        "current_drawdown_pct": float(drawdown or 0),
        "daily_loss_usd": float(daily_loss or 0),
    }


@app.get("/api/thoughts")
async def get_thoughts(limit: int = 50):
    entries = await _redis.xrevrange("movar:thoughts", count=limit)
    result = []
    for entry_id, data in entries:
        result.append({
            "id": entry_id,
            "agent": data.get("agent", ""),
            "prompt": data.get("prompt", ""),
            "response": data.get("response", ""),
            "duration_ms": int(data.get("duration_ms", 0)),
            "ts": float(data.get("ts", 0)),
        })
    return result


@app.get("/api/thinking")
async def get_thinking():
    thinking = []
    for agent_id in AGENT_IDS:
        val = await _redis.get(f"movar:thinking:{agent_id}")
        if val:
            thinking.append(agent_id)
    return thinking


@app.post("/api/kill_switch/activate")
async def activate_kill_switch():
    await _redis.set("movar:kill_switch", "1")
    await _redis.xadd(STREAM_KEY, {
        "id": f"manual-{int(time.time())}",
        "sender": "human",
        "recipient": "risk_gate",
        "msg_type": "KILL_SWITCH",
        "priority": "0",
        "payload": json.dumps({"reason": "manual_dashboard_activation"}),
        "timestamp": str(time.time()),
        "requires_ack": "False",
        "correlation_id": "",
    })
    return {"status": "kill_switch_activated"}


@app.post("/api/kill_switch/deactivate")
async def deactivate_kill_switch():
    await _redis.delete("movar:kill_switch")
    return {"status": "kill_switch_deactivated"}


async def sse_generator() -> AsyncGenerator[str, None]:
    while True:
        try:
            now = time.time()

            kill_switch = await _redis.get("movar:kill_switch")
            audit_len = await _redis.xlen(AUDIT_KEY)
            stream_len = await _redis.xlen(STREAM_KEY)

            account_raw = await _redis.hget(STATE_KEY, "account_update")
            account = {}
            if account_raw:
                try:
                    account = json.loads(account_raw)
                except Exception:
                    pass

            entries = await _redis.xrevrange(AUDIT_KEY, count=5)
            recent = []
            for entry_id, data in entries:
                recent.append({
                    "sender": data.get("sender", ""),
                    "recipient": data.get("recipient", ""),
                    "msg_type": data.get("msg_type", ""),
                    "timestamp": data.get("timestamp", ""),
                })

            agents_alive = agents_slow = agents_dead = 0
            thinking_agents = []
            for agent_id in AGENT_IDS:
                last_beat_raw = await _redis.get(f"movar:heartbeat:{agent_id}")
                if last_beat_raw:
                    lag = now - float(last_beat_raw)
                    if lag < 45:
                        agents_alive += 1
                    elif lag < 120:
                        agents_slow += 1
                    else:
                        agents_dead += 1
                else:
                    agents_dead += 1
                if await _redis.get(f"movar:thinking:{agent_id}"):
                    thinking_agents.append(agent_id)

            # Latest thought for live feed
            latest_thoughts = []
            thought_entries = await _redis.xrevrange("movar:thoughts", count=3)
            for _, data in thought_entries:
                latest_thoughts.append({
                    "agent": data.get("agent", ""),
                    "prompt": data.get("prompt", ""),
                    "response": data.get("response", ""),
                    "duration_ms": int(data.get("duration_ms", 0)),
                    "ts": float(data.get("ts", 0)),
                })

            payload = {
                "kill_switch": kill_switch == "1",
                "audit_len": audit_len,
                "stream_len": stream_len,
                "account": account,
                "recent_messages": recent,
                "agent_counts": {
                    "alive": agents_alive,
                    "slow": agents_slow,
                    "dead": agents_dead,
                    "total": len(AGENT_IDS),
                },
                "thinking_agents": thinking_agents,
                "latest_thoughts": latest_thoughts,
                "ts": now,
            }

            yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        await asyncio.sleep(2)


@app.get("/api/stream")
async def stream():
    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/", response_class=HTMLResponse)
async def root():
    html_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(html_path) as f:
        return HTMLResponse(f.read())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("dashboard.server:app", host="0.0.0.0", port=8000, reload=False)
