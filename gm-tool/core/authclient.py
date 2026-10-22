"""GM 工具调用鉴权服务的客户端。

用于「看到谁在撞库 → 一键封禁」这条链路：
脚本扫描 /events 与 /ip-summary，管理员确认后调 /rate-limit/reset 或直接封 IP。

鉴权服务的地址与密钥存在 GM_Tool/config.json 的 auth_* 字段，
未配置时相关界面只提示、不报错——工具本身不依赖鉴权服务也能用。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class AuthAdminError(Exception):
    pass


class AuthAdmin:
    def __init__(self, base_url: str, api_key: str, timeout: float = 8.0) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _request(self, path: str, method: str = "GET",
                 payload: dict | None = None) -> dict:
        if not self.configured:
            raise AuthAdminError("未配置鉴权服务地址（GM_Tool/config.json 的 auth_base_url）")
        url = f"{self.base_url}{path}"
        data = None
        headers = {"X-Api-Key": self.api_key}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            try:
                body = json.loads(e.read().decode("utf-8"))
                detail = body.get("detail") or body.get("message") or f"HTTP {e.code}"
            except Exception:
                detail = "密钥无效或服务拒绝" if e.code == 401 else f"HTTP {e.code}"
            raise AuthAdminError(detail)
        except urllib.error.URLError as e:
            raise AuthAdminError(f"无法连接鉴权服务：{getattr(e, 'reason', e)}")
        except Exception as e:
            raise AuthAdminError(str(e))

    # ---- 查询 ----
    def health(self) -> dict:
        return self._request("/health")

    def events(self, limit: int = 200, kind: str = "", ip: str = "",
               username: str = "") -> list[dict]:
        q = [f"limit={int(limit)}"]
        if kind:
            q.append(f"kind={urllib.parse.quote(kind)}")
        if ip:
            q.append(f"ip={urllib.parse.quote(ip)}")
        if username:
            q.append(f"username={urllib.parse.quote(username)}")
        return self._request("/events?" + "&".join(q)).get("items", [])

    def ip_summary(self, limit: int = 100) -> list[dict]:
        return self._request(f"/events/ip-summary?limit={int(limit)}").get("items", [])

    def stats(self) -> dict:
        return self._request("/events/stats")

    # ---- 操作 ----
    def reset_rate_limit(self, ip: str = "", username: str = "") -> dict:
        return self._request("/rate-limit/reset", "POST",
                             {"ip": ip, "username": username})

    def kick(self, user_id: int) -> dict:
        return self._request("/kick", "POST", {"user_id": int(user_id)})


__all__ = ["AuthAdmin", "AuthAdminError"]
