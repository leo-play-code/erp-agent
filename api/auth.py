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
import re
import time
import urllib.parse
import urllib.request

import jwt
from dotenv import load_dotenv
from fastapi import Header, HTTPException

from tools.tenant import current_tenant_var  # 跨層共用的租戶 context（低層，api/tools 都能用）

# 本模組在 import 當下就讀環境變數，且在 server.py 比會載入 .env 的 tools 更早被 import，
# 故這裡自行 load_dotenv()，確保不論啟動方式都讀得到 .env 的 GOOGLE_CLIENT_ID / APP_JWT_SECRET。
load_dotenv()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
APP_JWT_SECRET = os.getenv("APP_JWT_SECRET", "dev-insecure-change-me")

# 啟用哪些登入方式（前端登入頁據此顯示）：
#   google = Google 登入（雲端）；local = 帳號密碼（管理員建帳號）；
#   imap/ldap = 帳密表單，但向公司 mail/AD 驗證（每間公司於 companies.auth_method 指定實際驗法）。
# AUTH_MODES 環境變數可明列（逗號分隔）；沒設時：有 GOOGLE_CLIENT_ID → google+local，否則單人免登入（向後相容）。
_modes_env = os.getenv("AUTH_MODES", "").strip()
if _modes_env:
    AUTH_MODES = [m.strip() for m in _modes_env.split(",") if m.strip()]
elif GOOGLE_CLIENT_ID:
    AUTH_MODES = ["google", "local"]
else:
    AUTH_MODES = []
# 登入頁有「帳密表單」(local/imap/ldap 任一) 或 Google 按鈕
PASSWORD_LOGIN = any(m in AUTH_MODES for m in ("local", "imap", "ldap"))
GOOGLE_LOGIN = "google" in AUTH_MODES
AUTH_ENABLED = bool(AUTH_MODES)
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


def issue_app_jwt(user: dict, role: str = "employee", developer: bool = False) -> str:
    """簽一張自家 JWT（前端存著、之後每個 API 帶上）。

    內含 role / developer 兩個權限 claim：前端據此顯示「員工管理」「開發者 Agent」分頁，
    claude-frontend 的 SSO 也用 developer claim 把關開發者席次。權限變更於下次登入刷新。
    """
    payload = {
        "sub": user["sub"],
        "email": user.get("email", ""),
        "name": user.get("name", ""),
        "role": role,
        "developer": bool(developer),
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
    """使用者 → 公司租戶 key（= email 網域）。同網域＝同公司，資料共享；跨網域隔離。
    沒使用者 / 無 email 用 default（向後相容、單人模式）。"""
    if not user or not user.get("email") or "@" not in user["email"]:
        return "default"
    domain = user["email"].rsplit("@", 1)[1].lower()
    return "org_" + re.sub(r"[^a-z0-9]+", "_", domain).strip("_")


def user_id_of(user: dict | None) -> str:
    """使用者個人 id（給對話紀錄等個人層資料用）。"""
    return ("u_" + user["sub"]) if user else "anon"


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


# ── 角色 / 權限（RBAC）─────────────────────────────────────────────────
# 讀「JWT 的 claim」做 gating（與前端看到的一致；權限變更於下次登入刷新）。授予/收回席次的
# 「真實寫入與上限檢查」走 db.control_plane（DB 為單一真相）。未啟用 auth（單人模式）時一律放行。
def role_of(user: dict | None) -> str:
    if not AUTH_ENABLED:
        return "company_admin"
    return (user or {}).get("role", "employee")


def is_company_admin(user: dict | None) -> bool:
    return role_of(user) == "company_admin"


def is_developer(user: dict | None) -> bool:
    if not AUTH_ENABLED:
        return True
    return bool((user or {}).get("developer"))


def require_company_admin(authorization: str | None = Header(default=None)) -> dict | None:
    """FastAPI 依賴：限公司管理員。順帶設好 tenant contextvar。"""
    user = current_user(authorization)
    if not is_company_admin(user):
        raise HTTPException(status_code=403, detail="需要公司管理員權限")
    current_tenant_var.set(tenant_of(user))
    return user


def require_developer(authorization: str | None = Header(default=None)) -> dict | None:
    """FastAPI 依賴：限擁有開發者席次者。"""
    user = current_user(authorization)
    if not is_developer(user):
        raise HTTPException(status_code=403, detail="無開發者席次")
    current_tenant_var.set(tenant_of(user))
    return user
