"""跨層共用的「目前租戶」context。

API 進入點（依使用者的登入）設定它；in-process 工具（rag_tools 等）讀它做資料隔離。
放在 tools/ 低層，讓 api 與 tools 都能 import，不違反單向依賴（api → tools）。
預設 "default"：沒登入 / 未啟用 auth 時的單一租戶（向後相容）。
"""

import contextvars
import re

current_tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tenant", default="default"
)


def get_tenant() -> str:
    return current_tenant_var.get()


def schema_for_tenant(tenant: str) -> str:
    """租戶 key → 該公司專屬的 Postgres schema 名（每公司獨立 schema）。

    `default`（單人 / 未登入，向後相容）對應 `public`；其餘對應 `tenant_<key>`，
    例如 `org_acme_com` → `tenant_org_acme_com`。是「租戶 → schema」的單一來源，
    sql_tools（查詢時設 search_path）、provision（建 schema）、control_plane 都用它。
    """
    if not tenant or tenant == "default":
        return "public"
    safe = re.sub(r"[^a-z0-9_]+", "_", tenant.lower()).strip("_")
    return "tenant_" + safe if safe else "public"
