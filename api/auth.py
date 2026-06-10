"""登入認證與多租戶（Google 登入 → 自家 JWT → tenant）。

流程：前端用 Google Identity Services 拿到 Google ID token → POST /api/auth/google →
這裡向 Google 驗證、簽一張自家 JWT 給前端 → 之後每個 API 帶 `Authorization: Bearer <jwt>`，
由 current_tenant() 認出使用者，並把 tenant 放進 contextvar 供 in-process 工具（RAG 等）讀。

設計：
- **驗 Google token** 用 tokeninfo 端點（簡單、不需金鑰/憑證下載）；檢查 aud == GOOGLE_CLIENT_ID。
- **自家 JWT** 用 HS256 + APP_JWT_SECRET 簽，內含 sub/email/name。
- **tenant key** = "u_" + Google sub（每個 Google 帳號一個獨立工作區）。
- **向後相容**：沒設 GOOGLE_CLIENT_ID（AUTH_ENABLED=False）時不強制登入，一律 tenant="default"，
  既有單人使用照舊。設了就強制登入（未帶有效 JWT 的受保護端點回 401）。
"""

import json
import os
import time
import urllib.parse
import urllib.request

import jwt
from fastapi import Header, HTTPException

from tools.tenant import current_tenant_var  # 跨層共用的租戶 context（低層，api/tools 都能用）

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
APP_JWT_SECRET = os.getenv("APP_JWT_SECRET", "dev-insecure-change-me")
AUTH_ENABLED = bool(GOOGLE_CLIENT_ID)
_ALG = "HS256"
_TTL = 7 * 24 * 3600  # JWT 有效 7 天


def verify_google_id_token(id_token: str) -> dict:
    """向 Google 驗證 ID token，回 {sub,email,name}。失敗丟 401。"""
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode(
        {"id_token": id_token}
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=401, detail="Google 登入驗證失敗，請重試")
    if not GOOGLE_CLIENT_ID or data.get("aud") != GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=401, detail="這個 Google 憑證不屬於本應用")
    if not data.get("sub"):
        raise HTTPException(status_code=401, detail="Google 帳號資訊不完整")
    return {"sub": data["sub"], "email": data.get("email", ""), "name": data.get("name", "")}


def issue_app_jwt(user: dict) -> str:
    """簽一張自家 JWT（前端存著、之後每個 API 帶上）。"""
    payload = {
        "sub": user["sub"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "exp": int(time.time()) + _TTL,
    }
    return jwt.encode(payload, APP_JWT_SECRET, algorithm=_ALG)


def _user_from_bearer(authorization: str | None) -> dict | None:
    """解析 Authorization: Bearer <jwt>，回使用者 dict；無效回 None。"""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return jwt.decode(authorization[7:], APP_JWT_SECRET, algorithms=[_ALG])
    except Exception:
        return None


def tenant_of(user: dict | None) -> str:
    """使用者 → tenant key。沒使用者用 default（向後相容）。"""
    return "u_" + user["sub"] if user else "default"


def current_user(authorization: str | None = Header(default=None)) -> dict | None:
    """FastAPI 依賴：取目前登入使用者。AUTH_ENABLED 時未登入丟 401；否則可為 None。"""
    user = _user_from_bearer(authorization)
    if AUTH_ENABLED and not user:
        raise HTTPException(status_code=401, detail="請先登入")
    return user


def current_tenant(authorization: str | None = Header(default=None)) -> str:
    """FastAPI 依賴：認出使用者、設好 contextvar 並回傳 tenant key。

    把它掛到受保護端點（Depends），即可在該請求內讓 in-process 工具讀到正確 tenant。
    """
    user = current_user(authorization)
    tenant = tenant_of(user)
    current_tenant_var.set(tenant)
    return tenant
