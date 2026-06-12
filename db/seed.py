"""建立 ERP 人事 schema 並灌入 mock 資料（員工、部門、特休餘額、請假紀錄）。

- 連線字串取自環境變數 DATABASE_URL（見 .env）。
- 資料用固定亂數種子產生，重跑結果一致；每次執行會先 DROP 再重建（冪等）。
- 特休總額依「到職年資」按台灣勞基法級距計算，剩餘 = 總額 − 已用。

執行：venv/bin/python -m db.seed
"""

import os
import random
from datetime import date, timedelta

import psycopg
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp@localhost:5433/erp")
TODAY = date(2026, 6, 1)  # 以此為基準日計算年資與特休
random.seed(42)

DEPARTMENTS = ["業務部", "工程部", "財務部", "人資部", "採購部", "資訊部", "製造部", "品保部"]
SURNAMES = list("陳林黃張李王吳劉蔡楊許鄭謝郭洪曾邱廖賴周")
GIVEN = ["志明", "淑芬", "家豪", "怡君", "建宏", "雅婷", "俊傑", "美玲", "宗翰", "詩涵",
         "冠廷", "雅雯", "承恩", "欣怡", "柏翰", "婷婷", "信宏", "佩珊", "彥廷", "曉君",
         "孟儒", "宜蓁", "智偉", "瑞穎", "國誠", "麗華", "建良", "靜宜", "明哲", "嘉玲"]
TITLES = ["專員", "資深專員", "工程師", "資深工程師", "課長", "副理", "經理", "助理"]
LEAVE_TYPES = ["特休", "事假", "病假", "婚假", "喪假"]

SCHEMA = """
DROP TABLE IF EXISTS leave_records CASCADE;
DROP TABLE IF EXISTS leave_balances CASCADE;
DROP TABLE IF EXISTS employees CASCADE;
DROP TABLE IF EXISTS departments CASCADE;

CREATE TABLE departments (
    id      SERIAL PRIMARY KEY,
    name    TEXT UNIQUE NOT NULL,
    manager TEXT
);

CREATE TABLE employees (
    id            SERIAL PRIMARY KEY,
    emp_no        TEXT UNIQUE NOT NULL,        -- 員工編號
    name          TEXT NOT NULL,
    gender        TEXT,                        -- 男 / 女
    email         TEXT,
    department_id INTEGER REFERENCES departments(id),
    title         TEXT,                        -- 職稱
    hire_date     DATE NOT NULL,               -- 到職日
    status        TEXT DEFAULT '在職'           -- 在職 / 留職停薪 / 離職
);

CREATE TABLE leave_balances (
    id               SERIAL PRIMARY KEY,
    employee_id      INTEGER REFERENCES employees(id),
    year             INTEGER NOT NULL,
    annual_quota     NUMERIC(4,1) NOT NULL,    -- 當年度特休總額（天）
    annual_used      NUMERIC(4,1) NOT NULL,    -- 已用特休（天）
    annual_remaining NUMERIC(4,1) NOT NULL,    -- 特休剩餘（天）
    UNIQUE (employee_id, year)
);

CREATE TABLE leave_records (
    id          SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES employees(id),
    leave_type  TEXT NOT NULL,                 -- 特休 / 事假 / 病假 ...
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    days        NUMERIC(4,1) NOT NULL,
    reason      TEXT,
    status      TEXT DEFAULT '已核准',          -- 已核准 / 待審核 / 已駁回
    applied_at  TIMESTAMP DEFAULT now()
);
"""


def annual_quota(years: float) -> float:
    """依台灣勞基法給特休天數（年資 → 天）。"""
    if years < 0.5:
        return 0
    if years < 1:
        return 3
    if years < 2:
        return 7
    if years < 3:
        return 10
    if years < 5:
        return 14
    if years < 10:
        return 15
    return float(min(30, 15 + (int(years) - 9)))  # 滿10年起每年+1，上限30


def main(schema: str = "public", seed_data: bool = True) -> None:
    """建立人事 schema，並（預設）灌入 mock 資料。

    多租戶：`schema` 指定要建到哪個公司 schema（provision 新公司時傳 tenant_<key>）。
    `seed_data=False` 只建表結構、不灌假資料（給真實空白公司用）。
    """
    with psycopg.connect(DATABASE_URL, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"; SET search_path TO "{schema}";')
        cur.execute(SCHEMA)
        if not seed_data:
            print(f"完成：已在 schema {schema} 建立人事表（未灌假資料）。")
            return

        # 部門
        dept_ids = {}
        for name in DEPARTMENTS:
            manager = random.choice(SURNAMES) + random.choice(GIVEN)
            cur.execute(
                "INSERT INTO departments (name, manager) VALUES (%s, %s) RETURNING id",
                (name, manager + "經理"),
            )
            dept_ids[name] = cur.fetchone()[0]

        # 員工 + 特休餘額 + 請假紀錄
        for i in range(1, 61):
            name = random.choice(SURNAMES) + random.choice(GIVEN)
            gender = random.choice(["男", "女"])
            dept = random.choice(DEPARTMENTS)
            title = random.choice(TITLES)
            # 到職日：2014~2026 之間
            hire = TODAY - timedelta(days=random.randint(60, 365 * 12))
            years = (TODAY - hire).days / 365.25
            status = random.choices(["在職", "留職停薪", "離職"], weights=[92, 4, 4])[0]
            emp_no = f"E{i:04d}"
            email = f"{emp_no.lower()}@erp.example.com"

            cur.execute(
                """INSERT INTO employees
                   (emp_no, name, gender, email, department_id, title, hire_date, status)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                (emp_no, name, gender, email, dept_ids[dept], title, hire, status),
            )
            emp_id = cur.fetchone()[0]

            quota = annual_quota(years)
            used = round(random.uniform(0, quota), 1) if quota else 0.0
            remaining = round(quota - used, 1)
            cur.execute(
                """INSERT INTO leave_balances
                   (employee_id, year, annual_quota, annual_used, annual_remaining)
                   VALUES (%s,%s,%s,%s,%s)""",
                (emp_id, TODAY.year, quota, used, remaining),
            )

            # 0~4 筆請假紀錄
            for _ in range(random.randint(0, 4)):
                ltype = random.choice(LEAVE_TYPES)
                days = random.choice([0.5, 1, 1, 2, 3])
                start = TODAY - timedelta(days=random.randint(1, 300))
                end = start + timedelta(days=int(days) if days >= 1 else 0)
                status_r = random.choices(["已核准", "待審核", "已駁回"], weights=[80, 15, 5])[0]
                cur.execute(
                    """INSERT INTO leave_records
                       (employee_id, leave_type, start_date, end_date, days, reason, status)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (emp_id, ltype, start, end, days, f"{ltype}申請", status_r),
                )

        cur.execute("SELECT count(*) FROM employees")
        n_emp = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM leave_records")
        n_rec = cur.fetchone()[0]
        print(f"完成：{len(DEPARTMENTS)} 部門、{n_emp} 員工、{n_rec} 筆請假紀錄。")


if __name__ == "__main__":
    main()
