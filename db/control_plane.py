"""控制面（control plane）：跨公司共用、放在 public schema 的資料表 + 存取函式。

多租戶採「每公司一個 Postgres schema」（業務表在 tenant_<key> schema），但**身分、角色、
開發者席次、站內信箱**這些跨公司一致的東西放在 `public`，用 `tenant` 欄位隔離。理由：
信箱/角色的結構各公司完全相同，放 public + tenant 欄位比每個 schema 複製一份 DDL 乾淨，
也避免跨 schema 外鍵。所有查詢都帶 `WHERE tenant = ...` 做隔離（與 RAG 的 per-tenant 子目錄
同樣紀律）。

- 連線：用「可寫」連線（與 sql_tools 對業務資料的唯讀池獨立）。
- 角色：company_admin / employee；developer 是獨立旗標（可疊加），受公司席次 quota 限制。
- 執行 `venv/bin/python -m db.control_plane` 會建好 public 的控制面表（冪等）。
"""

import hashlib
import os
import secrets
from contextlib import contextmanager

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from tools.tenant import schema_for_tenant

load_dotenv()

DATABASE_URL = os.getenv("CONTROL_PLANE_DATABASE_URL") or os.getenv(
    "DATABASE_URL", "postgresql://erp@localhost:5433/erp"
)
DEFAULT_DEV_QUOTA = int(os.getenv("DEVELOPER_SEAT_QUOTA", "5"))

CONTROL_PLANE_DDL = """
CREATE TABLE IF NOT EXISTS companies (
    tenant      TEXT PRIMARY KEY,            -- 公司租戶 key（= org_<email 網域>）
    name        TEXT,
    schema_name TEXT NOT NULL,               -- 業務資料所在 schema（tenant_<key>）
    dev_quota   INT  NOT NULL DEFAULT 5,     -- 開發者席次上限（3~5）
    admin_email TEXT,                        -- 指定的公司管理員 email（登入時自動授 company_admin）
    auth_method TEXT NOT NULL DEFAULT 'local',-- 這間公司用哪種登入：local | imap | ldap | google
    auth_config JSONB,                        -- imap/ldap 連線設定（host/port/ssl/base_dn…）
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_users (
    sub           TEXT PRIMARY KEY,          -- 身分 key：Google=google sub；本地/IMAP/LDAP=local:<email>
    tenant        TEXT NOT NULL,
    email         TEXT,
    name          TEXT,
    role          TEXT NOT NULL DEFAULT 'employee',  -- company_admin | employee
    developer     BOOLEAN NOT NULL DEFAULT false,    -- 開發者席次旗標（開啟開發者 agent 分頁）
    password_hash TEXT,                        -- 僅 local 模式用（scrypt salt:hash）；Google/IMAP/LDAP 為 NULL
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS app_users_tenant_idx ON app_users (tenant);
CREATE INDEX IF NOT EXISTS app_users_tenant_email_idx ON app_users (tenant, lower(email));

-- 既有資料庫補欄位（冪等；新欄位上線時自動加上）
ALTER TABLE companies ADD COLUMN IF NOT EXISTS auth_method TEXT NOT NULL DEFAULT 'local';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS auth_config JSONB;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS password_hash TEXT;

CREATE TABLE IF NOT EXISTS mailbox_messages (
    id         SERIAL PRIMARY KEY,
    tenant     TEXT NOT NULL,
    sender_sub TEXT,                         -- NULL = 系統發送
    subject    TEXT,
    body       TEXT,
    kind       TEXT NOT NULL DEFAULT 'message',  -- message | announcement
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS mailbox_recipients (
    id            SERIAL PRIMARY KEY,
    message_id    INTEGER NOT NULL REFERENCES mailbox_messages(id) ON DELETE CASCADE,
    recipient_sub TEXT NOT NULL,
    read_at       TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS mailbox_recipients_inbox_idx
    ON mailbox_recipients (recipient_sub, read_at);

CREATE TABLE IF NOT EXISTS notifications (
    id         SERIAL PRIMARY KEY,
    tenant     TEXT NOT NULL,
    user_sub   TEXT NOT NULL,
    kind       TEXT,
    title      TEXT,
    body       TEXT,
    link       TEXT,
    read_at    TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_sub, read_at);
"""


_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=DATABASE_URL,
            min_size=0,
            max_size=int(os.getenv("CONTROL_POOL_MAX", "5")),
            timeout=5,
            kwargs={"autocommit": True, "prepare_threshold": 0, "connect_timeout": 3},
            open=True,
        )
    return _pool


@contextmanager
def _conn():
    """借一個可寫連線（控制面表都在 public，固定 search_path 到 public）。回傳 dict_row 游標方便取用。"""
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO public")
        yield conn


def ensure_control_plane() -> None:
    """建立控制面所有表（冪等，可重複呼叫）。"""
    # prepare=False：走 simple protocol，才能一次執行多條 DDL（pool 設了 prepare_threshold=0
    # 會強制 prepared statement，而 prepared statement 不允許多語句）。
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(CONTROL_PLANE_DDL, prepare=False)


# ── 公司 / 使用者 / 角色 / 開發者席次 ─────────────────────────────────────
def ensure_company(
    tenant: str, name: str | None = None, dev_quota: int | None = None,
    admin_email: str | None = None,
) -> dict:
    """確保公司列存在（schema_name 由 schema_for_tenant 推導）。回傳公司列。"""
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        # dev_quota 只在「建立」公司時帶入（INSERT），之後 ensure_company（每次登入都會呼叫）
        # 不覆寫既有 quota，只回填 name / admin_email。
        cur.execute(
            """INSERT INTO companies (tenant, name, schema_name, dev_quota, admin_email)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (tenant) DO UPDATE SET
                   name = COALESCE(EXCLUDED.name, companies.name),
                   admin_email = COALESCE(EXCLUDED.admin_email, companies.admin_email)
               RETURNING *""",
            (tenant, name, schema_for_tenant(tenant),
             dev_quota if dev_quota is not None else DEFAULT_DEV_QUOTA, admin_email),
        )
        return cur.fetchone()


def get_company(tenant: str) -> dict | None:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM companies WHERE tenant = %s", (tenant,))
        return cur.fetchone()


def get_user(sub: str) -> dict | None:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM app_users WHERE sub = %s", (sub,))
        return cur.fetchone()


def upsert_user(sub: str, tenant: str, email: str = "", name: str = "") -> dict:
    """登入時呼叫：沒有就建（公司第一位使用者自動成為 company_admin），有就更新 email/name。

    回傳該使用者列（含 role / developer）。會順帶確保公司列存在。
    """
    company = ensure_company(tenant, name=None)
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM app_users WHERE sub = %s", (sub,))
        u = cur.fetchone()
        if u:
            cur.execute(
                "UPDATE app_users SET email = %s, name = %s WHERE sub = %s RETURNING *",
                (email or u["email"], name or u["name"], sub),
            )
            return cur.fetchone()
        # company_admin 判定：① 指定的 admin_email 相符，或 ② 公司還沒有任何 company_admin
        #（鏡像 cf 的「第一人即 admin」）。其餘為 employee。
        admin_email = (company or {}).get("admin_email")
        is_named_admin = bool(admin_email and email and email.lower() == admin_email.lower())
        cur.execute(
            "SELECT 1 FROM app_users WHERE tenant = %s AND role = 'company_admin' LIMIT 1",
            (tenant,),
        )
        has_admin = cur.fetchone() is not None
        role = "company_admin" if (is_named_admin or not has_admin) else "employee"
        cur.execute(
            """INSERT INTO app_users (sub, tenant, email, name, role)
               VALUES (%s, %s, %s, %s, %s) RETURNING *""",
            (sub, tenant, email, name, role),
        )
        return cur.fetchone()


# ── 帳號密碼登入（模式 A，本地）+ 憑證驗證分派（A/B/C）──────────────────
def hash_password(pw: str) -> str:
    """scrypt 雜湊（stdlib，無外部依賴），格式 salt:hash。"""
    salt = secrets.token_hex(16)
    h = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64).hex()
    return f"{salt}:{h}"


def verify_password(pw: str, stored: str | None) -> bool:
    if not stored or ":" not in stored:
        return False
    salt, h = stored.split(":", 1)
    try:
        test = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=64).hex()
    except Exception:  # noqa: BLE001
        return False
    return secrets.compare_digest(test, h)


def _local_sub(tenant: str, email: str) -> str:
    """本地/IMAP/LDAP 帳號的身分 key（無 Google sub）：穩定、可當 thread_id 用。"""
    return f"local:{tenant}:{email.lower()}"


def get_user_by_email(tenant: str, email: str) -> dict | None:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM app_users WHERE tenant = %s AND lower(email) = lower(%s)",
            (tenant, email),
        )
        return cur.fetchone()


def create_employee(
    tenant: str, email: str, name: str = "", password: str | None = None,
    role: str = "employee",
) -> dict:
    """管理員後台建員工帳號。給 password＝本地帳密登入；不給＝IMAP/LDAP 允許名單（用公司帳密登入）。"""
    ensure_company(tenant, name=None)
    sub = _local_sub(tenant, email)
    pwd = hash_password(password) if password else None
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """INSERT INTO app_users (sub, tenant, email, name, role, password_hash)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (sub) DO UPDATE SET
                   name = COALESCE(NULLIF(EXCLUDED.name,''), app_users.name),
                   role = EXCLUDED.role,
                   password_hash = COALESCE(EXCLUDED.password_hash, app_users.password_hash)
               RETURNING *""",
            (sub, tenant, email, name, role, pwd),
        )
        return cur.fetchone()


def set_password(tenant: str, email: str, password: str) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE app_users SET password_hash = %s WHERE tenant = %s AND lower(email) = lower(%s)",
            (hash_password(password), tenant, email),
        )


def set_company_auth(tenant: str, method: str, config: dict | None = None) -> dict:
    """設定某公司用哪種登入（local/imap/ldap/google）與其連線設定。"""
    if method not in ("local", "imap", "ldap", "google"):
        raise ValueError("登入方式僅能是 local / imap / ldap / google")
    import json
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "UPDATE companies SET auth_method = %s, auth_config = %s WHERE tenant = %s RETURNING *",
            (method, json.dumps(config) if config is not None else None, tenant),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("找不到該公司")
        return row


def verify_credentials(tenant: str, email: str, password: str) -> dict | None:
    """依公司的 auth_method 驗證帳密，回使用者列或 None。

    - local：比對 app_users.password_hash。
    - imap/ldap：向公司的 mail/AD 伺服器驗證；且該 email 必須已被管理員建檔（允許名單）。
    """
    company = get_company(tenant) or {}
    method = company.get("auth_method") or "local"
    user = get_user_by_email(tenant, email)
    if method == "local":
        return user if (user and verify_password(password, user.get("password_hash"))) else None
    if method in ("imap", "ldap"):
        if not user:  # 允許名單：管理員沒建檔的人不得登入
            return None
        from tools.auth_backends import verify_external
        return user if verify_external(method, company.get("auth_config") or {}, email, password) else None
    return None  # google 走另一條（/api/auth/google）


def list_company_users(tenant: str) -> list[dict]:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT * FROM app_users WHERE tenant = %s ORDER BY created_at", (tenant,)
        )
        return cur.fetchall()


def set_role(tenant: str, sub: str, role: str) -> dict:
    if role not in ("company_admin", "employee"):
        raise ValueError("角色僅能是 company_admin 或 employee")
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "UPDATE app_users SET role = %s WHERE sub = %s AND tenant = %s RETURNING *",
            (role, sub, tenant),
        )
        u = cur.fetchone()
        if not u:
            raise ValueError("找不到該使用者")
        return u


def developer_count(tenant: str) -> int:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM app_users WHERE tenant = %s AND developer = true",
            (tenant,),
        )
        return cur.fetchone()[0]


def developer_quota(tenant: str) -> int:
    c = get_company(tenant)
    return c["dev_quota"] if c else DEFAULT_DEV_QUOTA


def set_developer(tenant: str, sub: str, on: bool) -> dict:
    """授予 / 收回開發者席次。授予前檢查公司席次 quota，超過則丟 ValueError。"""
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        if on:
            quota = developer_quota(tenant)
            cur.execute(
                "SELECT developer FROM app_users WHERE sub = %s AND tenant = %s",
                (sub, tenant),
            )
            row = cur.fetchone()
            if row is None:
                raise ValueError("找不到該使用者")
            if not row["developer"] and developer_count(tenant) >= quota:
                raise ValueError(f"已達開發者席次上限（{quota}）")
        cur.execute(
            "UPDATE app_users SET developer = %s WHERE sub = %s AND tenant = %s RETURNING *",
            (on, sub, tenant),
        )
        u = cur.fetchone()
        if not u:
            raise ValueError("找不到該使用者")
        return u


# ── 站內信箱 / 通知 ───────────────────────────────────────────────────────
def send_message(
    tenant: str, sender_sub: str | None, recipient_subs: list[str], subject: str, body: str,
    kind: str = "message",
) -> int:
    """寄一封站內信給多位收件者，回傳 message id。"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO mailbox_messages (tenant, sender_sub, subject, body, kind)
               VALUES (%s, %s, %s, %s, %s) RETURNING id""",
            (tenant, sender_sub, subject, body, kind),
        )
        mid = cur.fetchone()[0]
        for r in recipient_subs:
            cur.execute(
                "INSERT INTO mailbox_recipients (message_id, recipient_sub) VALUES (%s, %s)",
                (mid, r),
            )
        return mid


def post_announcement(tenant: str, sender_sub: str | None, subject: str, body: str) -> int:
    """發布公司公告：對全公司每位使用者各建一筆收件紀錄。"""
    subs = [u["sub"] for u in list_company_users(tenant)]
    return send_message(tenant, sender_sub, subs, subject, body, kind="announcement")


def inbox(tenant: str, sub: str, limit: int = 100) -> list[dict]:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """SELECT m.id, m.subject, m.body, m.kind, m.sender_sub, m.created_at,
                      r.id AS recipient_id, r.read_at,
                      s.name AS sender_name, s.email AS sender_email
               FROM mailbox_recipients r
               JOIN mailbox_messages m ON m.id = r.message_id
               LEFT JOIN app_users s ON s.sub = m.sender_sub
               WHERE r.recipient_sub = %s AND m.tenant = %s
               ORDER BY m.created_at DESC LIMIT %s""",
            (sub, tenant, limit),
        )
        return cur.fetchall()


def mark_message_read(sub: str, recipient_id: int) -> None:
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE mailbox_recipients SET read_at = now() WHERE id = %s AND recipient_sub = %s",
            (recipient_id, sub),
        )


def create_notification(
    tenant: str, user_sub: str, kind: str, title: str, body: str = "", link: str = ""
) -> None:
    """系統事件通知（如 agent 長任務完成、管理動作）。最小實作：直接寫表，不做佇列/背景工。"""
    with _conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO notifications (tenant, user_sub, kind, title, body, link)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            (tenant, user_sub, kind, title, body, link),
        )


def notifications(tenant: str, sub: str, limit: int = 100) -> list[dict]:
    with _conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """SELECT * FROM notifications WHERE tenant = %s AND user_sub = %s
               ORDER BY created_at DESC LIMIT %s""",
            (tenant, sub, limit),
        )
        return cur.fetchall()


def mark_notification_read(sub: str, notif_id: int | None) -> None:
    """notif_id 給就標記單筆；None 標記該使用者全部未讀。"""
    with _conn() as conn, conn.cursor() as cur:
        if notif_id is None:
            cur.execute(
                "UPDATE notifications SET read_at = now() WHERE user_sub = %s AND read_at IS NULL",
                (sub,),
            )
        else:
            cur.execute(
                "UPDATE notifications SET read_at = now() WHERE id = %s AND user_sub = %s",
                (notif_id, sub),
            )


if __name__ == "__main__":
    ensure_control_plane()
    print("控制面資料表已就緒（companies / app_users / mailbox_* / notifications）。")
