"""DeskCal 同步服务 —— 桌面待办日历的后端存储

- 存储：SQLite（/home/deskcal/data/deskcal.db）
- 接口：GET  /state   拉取全量状态
        PUT  /state   推送本地状态，服务端合并后回传权威状态
        GET  /health  健康检查
- 合并策略：按条目 updatedAt 取新；客户端已删除的条目服务端同步删除
"""
import hmac
import json
import os
import sqlite3
import sys
import threading
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

DB_PATH = os.environ.get("DESKCAL_DB", "/home/deskcal/data/deskcal.db")
MAX_TODOS = 5000
MAX_CATS = 100
MAX_TITLE = 200

# 访问令牌。留空则接口不鉴权——只应在自己机器上用。
# 部署到公网必须设置：DESKCAL_TOKEN=<一串随机字符>
API_TOKEN = os.environ.get("DESKCAL_TOKEN", "").strip()

# 允许的跨域来源，逗号分隔。留空表示不放行任何跨域请求。
# 组件与接口同源（都走 nginx 的 /deskcal/ 前缀），正常情况下不需要跨域。
ALLOW_ORIGINS = [o.strip() for o in os.environ.get("DESKCAL_ORIGINS", "").split(",") if o.strip()]

os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
_lock = threading.Lock()

app = FastAPI(title="DeskCal Sync", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["GET", "PUT", "OPTIONS"],
    allow_headers=["*"],
)


def require_token(request: Request) -> None:
    if not API_TOKEN:
        return
    got = request.headers.get("x-deskcal-token") or request.query_params.get("token") or ""
    if not hmac.compare_digest(got, API_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


def now_ms() -> int:
    return int(time.time() * 1000)


def _connect():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.execute(
        "CREATE TABLE IF NOT EXISTS state ("
        " id INTEGER PRIMARY KEY CHECK(id=1),"
        " data TEXT NOT NULL,"
        " version INTEGER NOT NULL,"
        " updated_at INTEGER NOT NULL)"
    )
    return c


def load_state():
    c = _connect()
    try:
        row = c.execute("SELECT data, version, updated_at FROM state WHERE id=1").fetchone()
    finally:
        c.close()
    if not row:
        return {"version": 0, "updatedAt": 0, "data": {"todos": [], "cats": [], "settings": {}}}
    try:
        data = json.loads(row[0])
    except Exception:
        data = {"todos": [], "cats": [], "settings": {}}
    return {"version": row[1], "updatedAt": row[2], "data": data}


def save_state(data, version, updated_at):
    c = _connect()
    try:
        c.execute(
            "INSERT INTO state (id, data, version, updated_at) VALUES (1, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data=excluded.data, version=excluded.version, "
            "updated_at=excluded.updated_at",
            (json.dumps(data, ensure_ascii=False), version, updated_at),
        )
        c.commit()
    finally:
        c.close()


def ts(obj) -> int:
    try:
        return int(obj.get("updatedAt") or 0)
    except Exception:
        return 0


def clean_todo(t):
    if not isinstance(t, dict):
        return None
    title = str(t.get("title") or "").strip()[:MAX_TITLE]
    if not title:
        return None
    date = str(t.get("date") or "")
    if len(date) != 10:
        return None
    return {
        "id": str(t.get("id") or ""),
        "title": title,
        "date": date,
        "time": str(t.get("time") or "")[:5],
        "cat": str(t.get("cat") or ""),
        "done": bool(t.get("done")),
        "updatedAt": ts(t) or now_ms(),
    }


def clean_cat(c):
    if not isinstance(c, dict):
        return None
    name = str(c.get("name") or "").strip()[:20]
    if not name:
        return None
    return {
        "id": str(c.get("id") or ""),
        "name": name,
        "color": str(c.get("color") or "#888888")[:9],
        "updatedAt": ts(c) or now_ms(),
    }


def merge_list(stored, incoming, cleaner):
    idx = {}
    for it in stored or []:
        it = cleaner(it)
        if it and it["id"]:
            idx[it["id"]] = it

    # incoming 为 None 表示客户端这次没有提交这个字段（比如只改了设置）。
    # 这时保留服务端已有数据。若当成空列表处理，任何不带 todos 的 PUT 都会把全部待办删光。
    if incoming is None:
        return list(idx.values())

    incoming_ids = set()
    for raw in incoming:
        it = cleaner(raw)
        if not it or not it["id"]:
            continue
        incoming_ids.add(it["id"])
        cur = idx.get(it["id"])
        if cur is None or it["updatedAt"] >= cur["updatedAt"]:
            idx[it["id"]] = it
    # 客户端显式提交了列表，则以它为准：不在列表里的条目视为已删除
    return [v for k, v in idx.items() if k in incoming_ids]


def merge_state(stored_data, incoming_data):
    stored_data = stored_data or {}
    incoming_data = incoming_data or {}

    todos_raw = incoming_data.get("todos")
    cats_raw = incoming_data.get("cats")

    todos = merge_list(
        stored_data.get("todos"),
        None if todos_raw is None else todos_raw[:MAX_TODOS],
        clean_todo,
    )
    cats = merge_list(
        stored_data.get("cats"),
        None if cats_raw is None else cats_raw[:MAX_CATS],
        clean_cat,
    )

    s_set = stored_data.get("settings") or {}
    i_set = incoming_data.get("settings") or {}
    settings = dict(i_set) if ts(i_set) >= ts(s_set) else dict(s_set)

    return {"todos": todos, "cats": cats, "settings": settings}


@app.get("/health")
def health():
    st = load_state()
    return {"ok": True, "version": st["version"], "todos": len(st["data"].get("todos") or [])}


@app.get("/state")
def get_state(request: Request):
    require_token(request)
    return load_state()


@app.put("/state")
async def put_state(request: Request):
    require_token(request)
    body = await request.json()
    incoming = (body or {}).get("data") or {}
    with _lock:
        stored = load_state()
        merged = merge_state(stored["data"], incoming)
        version = stored["version"] + 1
        updated_at = now_ms()
        save_state(merged, version, updated_at)
    return {"version": version, "updatedAt": updated_at, "data": merged}


@app.exception_handler(Exception)
async def on_error(request: Request, exc: Exception):
    # 异常详情只写服务端日志，不回传给客户端，避免泄漏内部路径
    print(f"[deskcal] error on {request.url.path}: {exc!r}", file=sys.stderr)
    return JSONResponse(status_code=500, content={"error": "internal error"})
