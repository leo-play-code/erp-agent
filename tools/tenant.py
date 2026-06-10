"""跨層共用的「目前租戶」context。

API 進入點（依使用者的登入）設定它；in-process 工具（rag_tools 等）讀它做資料隔離。
放在 tools/ 低層，讓 api 與 tools 都能 import，不違反單向依賴（api → tools）。
預設 "default"：沒登入 / 未啟用 auth 時的單一租戶（向後相容）。
"""

import contextvars

current_tenant_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "tenant", default="default"
)


def get_tenant() -> str:
    return current_tenant_var.get()
