"""CSNZ 登录器鉴权服务。

部署在云服务器上，与 CSNZ 服务端同机运行（直接读 UserDatabase.db3）。
登录器通过 HTTPS 调这些接口，验证通过后才带账号密码启动游戏。

安全要点：
1. 所有接口都要求 X-Api-Key 头，密钥写在 config.json，登录器里内置同一把。
   这不是强认证（客户端可被逆向），但能挡住随手扫端口的脚本。
2. 生产环境务必开 HTTPS：账号密码是明文传输的（服务端用明文比对，
   无法改成哈希，见 core/accounts.py 说明）。
3. 登录接口不会返回密码，只返回「是否放行」。真正的登录由游戏客户端
   用 -username/-password 完成。
"""
from __future__ import annotations

import hmac
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.accounts import AccountStore, AuthError
from core.events import (EventStore, KICKED, LOGIN_FAIL, LOGIN_OK, RATE_BLOCKED,
                         REGISTER_FAIL, REGISTER_OK)
from core.ratelimit import RateLimiter

BASE = Path(__file__).resolve().parent
CFG = json.loads((BASE / "config.json").read_text(encoding="utf-8"))

SERVER_ROOT = (BASE / CFG.get("server_root", "..")).resolve()
DB_PATH = SERVER_ROOT / "UserDatabase.db3"
SERVER_CONFIG = SERVER_ROOT / "ServerConfig.json"

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(BASE / "auth.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("auth")

API_KEY = CFG.get("api_key", "")
DEFAULT_USER: dict[str, Any] = {}
if SERVER_CONFIG.exists():
    try:
        DEFAULT_USER = json.loads(
            SERVER_CONFIG.read_text(encoding="utf-8-sig")
        ).get("DefaultUser", {})
    except Exception:
        pass

store = AccountStore(
    DB_PATH, DEFAULT_USER,
    int(CFG.get("max_registrations_per_ip", 3)),
)
events = EventStore(BASE / "auth_events.db3", int(CFG.get("event_keep_days", 30)))

# 限频：默认 10 分钟内失败 5 次锁 10 分钟，可配置
RL_CFG = CFG.get("rate_limit", {}) or {}
limiter = RateLimiter(
    max_fails=int(RL_CFG.get("max_fails", 5)),
    window=float(RL_CFG.get("window_seconds", 600)),
    cooldown=float(RL_CFG.get("cooldown_seconds", 600)),
)


# 默认阈值 30：按「10 分钟内错 5 次」的限频算，正常人要连续撞库 6 轮才会触发，
# 而真正在爆破的脚本几分钟就到。共享 IP（网吧/学校）建议调到 100 以上。
AUTO_BAN_CFG = CFG.get("auto_ban", {}) or {}
AUTO_BAN_FAILS = int(AUTO_BAN_CFG.get("threshold", 30))
AUTO_BAN_ENABLED = bool(AUTO_BAN_CFG.get("enabled", True))


def maybe_auto_ban(ip: str) -> bool:
    """累计失败超过阈值就自动封 IP。

    为什么用「累计」而不是「单窗口」：单窗口在冷却结束后会清零，
    攻击者只要每 10 分钟试 4 次就能永远绕过。累计值不清零（进程内），
    真正体现「这个 IP 一直在撞库」。

    ⚠ 重要限制：IPBanList 表只有 ip 一列（服务端定义，不能加列），
    因此自动封禁是**永久**的，没有自动解封。这意味着阈值必须设得保守，
    否则网吧/校园网这类共享 IP 上一个坏人会把整片人封掉。
    默认阈值 30 次，且命中时会同时写事件，管理员可在 GM 工具「安全日志」
    页看到并手动解封。
    """
    if not AUTO_BAN_ENABLED or not ip:
        return False
    if limiter.total_fails(f"ip:{ip}") < AUTO_BAN_FAILS:
        return False
    if store.is_ip_banned(ip):
        return False
    try:
        store.ban_ip(ip)
    except Exception as e:
        log.error("auto-ban %s failed: %s", ip, e)
        return False
    events.add(RATE_BLOCKED, "", ip, detail=f"自动封禁(累计{AUTO_BAN_FAILS}次)")
    log.warning("AUTO-BANNED ip=%s after %d fails", ip, AUTO_BAN_FAILS)
    return True


def too_many(retry: float) -> JSONResponse:
    mins = max(1, int(retry // 60))
    return JSONResponse(
        {"ok": False, "code": "RATE_LIMITED",
         "message": f"尝试次数过多，请 {mins} 分钟后再试",
         "retry_after": int(retry)},
        status_code=429,
        headers={"Retry-After": str(int(retry))},
    )

app = FastAPI(title="CSNZ Auth Service", docs_url=None, redoc_url=None)


# ---------- 通用 ----------
def check_key(api_key: str | None) -> None:
    if not API_KEY:
        return
    if not api_key or not hmac.compare_digest(api_key, API_KEY):
        raise HTTPException(status_code=401, detail="API key 无效")


def client_ip(request: Request) -> str:
    """取真实客户端 IP。放在反代后面时优先用 X-Forwarded-For 首段。"""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "0.0.0.0"


# ---------- 模型 ----------
class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=15)
    password: str = Field(min_length=1, max_length=15)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=15)
    password: str = Field(min_length=1, max_length=15)
    kick_existing: bool = False


# ---------- 接口 ----------
@app.get("/health")
def health() -> dict:
    return {"ok": True, "db": DB_PATH.exists()}


@app.post("/register")
async def register(body: RegisterIn, request: Request,
                   x_api_key: str | None = Header(default=None)) -> JSONResponse:
    check_key(x_api_key)
    ip = client_ip(request)

    # 注册也限频：防批量建号
    key = f"reg:{ip}"
    retry = limiter.check(key)
    if retry:
        events.add(RATE_BLOCKED, body.username, ip, detail="register")
        return too_many(retry)

    try:
        uid = store.register(body.username, body.password, ip)
    except AuthError as e:
        waited = limiter.fail(key)
        events.add(REGISTER_FAIL, body.username, ip, detail=e.code)
        log.warning("register fail %s ip=%s code=%s", body.username, ip, e.code)
        if waited:
            events.add(RATE_BLOCKED, body.username, ip, detail="register")
            return too_many(waited)
        return JSONResponse({"ok": False, "code": e.code, "message": e.message},
                            status_code=400)
    limiter.success(key)
    events.add(REGISTER_OK, body.username, ip, user_id=uid)
    log.info("register ok %s uid=%d ip=%s", body.username, uid, ip)
    return JSONResponse({"ok": True, "user_id": uid,
                         "message": "注册成功，请在游戏内创建角色"})


@app.post("/login")
async def login(body: LoginIn, request: Request,
                x_api_key: str | None = Header(default=None)) -> JSONResponse:
    check_key(x_api_key)
    ip = client_ip(request)

    if store.is_ip_banned(ip):
        log.warning("login deny banned-ip %s", ip)
        events.add(LOGIN_FAIL, body.username, ip, detail="ip_banned")
        return JSONResponse({"ok": False, "code": "IP_BANNED",
                             "message": "该 IP 已被封禁"}, status_code=403)

    # 两个维度分别限频：同一 IP 撞库、同一账号被撞
    ip_key, user_key = f"ip:{ip}", f"user:{body.username}"
    for key in (ip_key, user_key):
        retry = limiter.check(key)
        if retry:
            # 被限频仍在尝试，同样是撞库信号：计入累计，否则自动封禁永远不触发
            limiter.fail(ip_key)
            events.add(RATE_BLOCKED, body.username, ip)
            log.warning("login rate-limited key=%s", key)
            if maybe_auto_ban(ip):
                return JSONResponse(
                    {"ok": False, "code": "IP_BANNED",
                     "message": "尝试次数过多，该 IP 已被封禁"},
                    status_code=403,
                )
            return too_many(retry)

    try:
        uid = store.verify_password(body.username, body.password)
    except AuthError as e:
        waited = max(limiter.fail(ip_key), limiter.fail(user_key))
        events.add(LOGIN_FAIL, body.username, ip, detail=e.code)
        log.warning("login fail %s ip=%s", body.username, ip)
        if maybe_auto_ban(ip):
            return JSONResponse(
                {"ok": False, "code": "IP_BANNED",
                 "message": "尝试次数过多，该 IP 已被临时封禁"},
                status_code=403,
            )
        if waited:
            events.add(RATE_BLOCKED, body.username, ip)
            return too_many(waited)
        left = limiter.remaining_fails(user_key)
        return JSONResponse(
            {"ok": False, "code": e.code,
             "message": f"{e.message}（还可尝试 {left} 次）"},
            status_code=401,
        )

    banned, reason = store.is_banned(uid)
    if banned:
        log.warning("login deny banned-user uid=%d", uid)
        events.add(LOGIN_FAIL, body.username, ip, user_id=uid, detail="user_banned")
        return JSONResponse({"ok": False, "code": "USER_BANNED",
                             "message": reason}, status_code=403)

    if store.is_online(uid):
        if not CFG.get("allow_multi_login", False) and not body.kick_existing:
            return JSONResponse(
                {"ok": False, "code": "ALREADY_ONLINE",
                 "message": "该账号已在游戏中，是否踢下线后重登？",
                 "can_kick": True},
                status_code=409,
            )
        store.kick_session(uid)
        events.add(KICKED, body.username, ip, user_id=uid, detail="顶号")
        log.info("kick existing session uid=%d", uid)

    limiter.success(ip_key)
    limiter.success(user_key)
    events.add(LOGIN_OK, body.username, ip, user_id=uid)
    account = store.get_account(uid) or {}
    log.info("login ok %s uid=%d ip=%s", body.username, uid, ip)
    return JSONResponse({
        "ok": True,
        "user_id": uid,
        "has_character": bool(account.get("gameName")),
        "game_name": account.get("gameName") or "",
        "message": "登录成功",
    })


@app.post("/kick")
async def kick(body: dict, x_api_key: str | None = Header(default=None)) -> JSONResponse:
    check_key(x_api_key)
    uid = int(body.get("user_id", 0))
    if not uid:
        raise HTTPException(status_code=400, detail="缺少 user_id")
    removed = store.kick_session(uid)
    events.add(KICKED, "", "", user_id=uid, detail="管理员踢出")
    log.info("kick uid=%d removed=%s", uid, removed)
    return JSONResponse({"ok": True, "removed": removed})


@app.get("/status")
async def status(user_id: int, x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    account = store.get_account(user_id)
    if not account:
        raise HTTPException(status_code=404, detail="用户不存在")
    banned, reason = store.is_banned(user_id)
    return {
        "ok": True,
        "user_id": user_id,
        "username": account["userName"],
        "game_name": account.get("gameName") or "",
        "level": account.get("level", 0),
        "online": store.is_online(user_id),
        "banned": banned,
        "ban_reason": reason,
    }


# ---------- 运维接口（供 GM 工具调用）----------
@app.get("/events")
async def list_events(limit: int = 200, kind: str = "", ip: str = "",
                      username: str = "",
                      x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    return {"ok": True, "items": events.recent(limit, kind, ip, username)}


@app.get("/events/ip-summary")
async def ip_summary(limit: int = 100,
                     x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    return {"ok": True, "items": events.ip_summary(limit)}


@app.get("/events/stats")
async def event_stats(x_api_key: str | None = Header(default=None)) -> dict:
    check_key(x_api_key)
    return {"ok": True, "stats": events.stats(),
            "rate_limited": limiter.snapshot()}


@app.post("/rate-limit/reset")
async def reset_rate_limit(body: dict,
                           x_api_key: str | None = Header(default=None)) -> dict:
    """解除某个 IP / 账号的限频。管理员误封玩家时用。"""
    check_key(x_api_key)
    ip = body.get("ip", "")
    username = body.get("username", "")
    cleared = []
    if ip:
        limiter.success(f"ip:{ip}")
        limiter.success(f"reg:{ip}")
        cleared.append(f"ip:{ip}")
    if username:
        limiter.success(f"user:{username}")
        cleared.append(f"user:{username}")
    log.info("rate-limit reset %s", cleared)
    return {"ok": True, "cleared": cleared}


def main() -> None:
    import uvicorn

    host = CFG.get("listen_host", "0.0.0.0")
    port = int(CFG.get("listen_port", 8080))
    use_https = CFG.get("use_https", False)
    kwargs: dict[str, Any] = {}
    if use_https:
        cert = CFG.get("cert_file", "")
        key = CFG.get("key_file", "")
        if cert and key:
            kwargs = {"ssl_certfile": str(BASE / cert), "ssl_keyfile": str(BASE / key)}

    log.info("starting on %s:%d https=%s db=%s", host, port, use_https, DB_PATH)
    uvicorn.run(app, host=host, port=port, **kwargs)


if __name__ == "__main__":
    main()
