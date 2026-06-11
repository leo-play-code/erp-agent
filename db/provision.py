"""開新公司（租戶）provisioning —— 可重複執行的一鍵上線腳本。

把一間新公司接上產品所需的步驟封裝成一個函式（仿 migrate_to_vault.py 的一次性腳本風格，
重用 db.seed / db.seed_mfg 的建表邏輯）：
  1. 確保控制面表存在（public）。
  2. 建立公司專屬 schema（tenant_<key>）並建好 ERP 業務表。
  3. 寫入 companies 列（含 schema_name / 開發者席次 quota / 指定管理員 email）。

指定的管理員 email 會在他首次用 Google 登入時自動取得 company_admin 角色（見
control_plane.upsert_user），不需預先知道其 Google sub。

用法：
  venv/bin/python -m db.provision --slug acme --name "Acme 公司" \
      --admin admin@acme.com --quota 5 [--demo]

  --slug   公司租戶 key（建議用 email 網域，例如 acme.com 會存成 org_acme_com 對齊登入推導）
  --demo   連同灌入 mock 假資料（預設只建空表結構）
"""

import argparse
import re

from db import control_plane, seed, seed_mfg
from tools.tenant import schema_for_tenant


def _tenant_key(slug: str) -> str:
    """把使用者給的 slug 正規化成與登入推導一致的 tenant key（org_<sanitized>）。

    若已是 org_ 開頭就原樣；否則比照 api/auth.py::tenant_of 對網域的處理加上 org_ 前綴。
    """
    s = slug.strip().lower()
    if s.startswith("org_"):
        return s
    return "org_" + re.sub(r"[^a-z0-9]+", "_", s).strip("_")


def provision_company(
    slug: str, name: str, admin_email: str, seat_quota: int = 3, demo: bool = False
) -> dict:
    tenant = _tenant_key(slug)
    schema = schema_for_tenant(tenant)

    control_plane.ensure_control_plane()
    # 業務表建到公司 schema；HR 要先於製造業（seed_mfg 會讀 employees）
    seed.main(schema=schema, seed_data=demo)
    seed_mfg.main(schema=schema, seed_data=demo)

    company = control_plane.ensure_company(
        tenant, name=name, dev_quota=seat_quota, admin_email=admin_email
    )
    print(
        f"已開通公司：tenant={tenant} schema={schema} "
        f"開發者席次={company['dev_quota']} 管理員={admin_email}"
        f"{'（含 demo 假資料）' if demo else '（空白表結構）'}"
    )
    return company


def main() -> None:
    p = argparse.ArgumentParser(description="開通一間新公司（租戶）")
    p.add_argument("--slug", required=True, help="公司租戶 key（建議用 email 網域）")
    p.add_argument("--name", required=True, help="公司顯示名稱")
    p.add_argument("--admin", required=True, help="公司管理員 email（登入後自動成為 company_admin）")
    p.add_argument("--quota", type=int, default=3, help="開發者席次上限（3~5，預設 3）")
    p.add_argument("--demo", action="store_true", help="連同灌入 mock 假資料")
    args = p.parse_args()
    provision_company(args.slug, args.name, args.admin, args.quota, args.demo)


if __name__ == "__main__":
    main()
