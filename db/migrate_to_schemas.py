"""一次性遷移：把現況「單一 public schema」轉成「public 控制面 + 每公司 schema」。

現況所有業務表都在 public（所有公司共用）。本腳本把現有業務表「搬進」第一間公司的
schema（tenant_<key>），並建好控制面表。用 `ALTER TABLE ... SET SCHEMA` 搬移——保留資料、
索引、外鍵、序列，不需 dump/reload。checkpoint 表（對話記憶）留在 public 不動（thread_id
已含 tenant 做邏輯隔離）。

⚠️ 執行前請先 `pg_dump` 備份，並確保沒有連線正持有這些表（建議在維護視窗執行）。

用法：
  venv/bin/python -m db.migrate_to_schemas --tenant org_acme_com --name "Acme 公司"
"""

import argparse

import psycopg

from db import control_plane
from db.seed import DATABASE_URL
from tools.tenant import schema_for_tenant

# 業務表（HR 4 張 + 製造業 14 張）。checkpoint_* 與控制面表不在此列、不搬移。
BUSINESS_TABLES = [
    "leave_records", "leave_balances", "employees", "departments",
    "customers", "suppliers", "products", "materials", "bom", "machines",
    "sales_orders", "sales_order_items", "purchase_orders", "purchase_order_items",
    "production_orders", "quality_inspections", "machine_downtime", "inventory",
]


def migrate(tenant: str, name: str | None = None) -> None:
    schema = schema_for_tenant(tenant)
    if schema == "public":
        raise SystemExit("拒絕：tenant 不可解析成 public（請給真正的公司 tenant key）")

    control_plane.ensure_control_plane()
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
        moved = []
        for t in BUSINESS_TABLES:
            cur.execute(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=%s",
                (t,),
            )
            if cur.fetchone():
                cur.execute(f'ALTER TABLE public."{t}" SET SCHEMA "{schema}"')
                moved.append(t)
        print(f"已搬移 {len(moved)} 張業務表到 schema {schema}：{moved}")

    control_plane.ensure_company(tenant, name=name)
    print(f"已寫入 companies 列：tenant={tenant} schema={schema}")
    print("完成。checkpoint 表與控制面表留在 public（不影響對話記憶）。")


def main() -> None:
    p = argparse.ArgumentParser(description="把現有 public 業務表遷入第一間公司的 schema")
    p.add_argument("--tenant", required=True, help="現有公司的 tenant key（org_<網域>）")
    p.add_argument("--name", help="公司顯示名稱")
    args = p.parse_args()
    migrate(args.tenant, args.name)


if __name__ == "__main__":
    main()
