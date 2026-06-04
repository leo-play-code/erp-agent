"""製造業 ERP mock 資料 —— 精密金屬零組件廠（沖壓/電鍍/CNC/組裝）。

在既有 HR 資料（departments/employees/…）之外，補上製造業會有的核心營運資料，
讓「決策分析」能跨域整合：營收/毛利、準交率、生產良率、品質不良、機台稼動、
供應商績效、庫存健康度。資料含 18 個月時序（2025-01 ~ 2026-06），可看趨勢。

特性：固定亂數種子（可重跑、結果一致）；每次執行先 DROP 再重建（冪等）。
執行：venv/bin/python -m db.seed_mfg
"""

import os
import random
from datetime import date, timedelta

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://erp@localhost:5433/erp")
START = date(2025, 1, 1)
END = date(2026, 6, 1)
random.seed(2026)

# ── 名稱池 ─────────────────────────────────────────────────────────────
REGIONS = ["台灣", "中國", "美國", "日本", "歐洲", "東南亞"]
CUST_INDUSTRY = ["消費電子", "車用電子", "工業控制", "通訊網通", "醫療器材", "綠能儲能"]
CUST_NAMES = ["鴻海精密", "和碩聯合", "台達電子", "廣達電腦", "緯創資通", "仁寶電腦",
              "光寶科技", "群創光電", "友達光電", "華碩電腦", "宏碁", "研華科技",
              "正崴精密", "美律實業", "建準電機", "億光電子", "大立光", "玉晶光",
              "矽品精密", "日月光", "京元電子", "欣興電子", "南電", "健鼎科技", "敬鵬工業"]
SUPP_NAMES = ["中鋼", "燁聯鋼鐵", "華新麗華", "第一銅", "金益鼎", "光洋科", "其陽科技",
              "上品綜合工業", "永光化學", "長春石化", "台灣特宏", "三福化工", "尚化",
              "立敦科技", "凱崴電子", "嘉聯益", "definite 精化", "東捷科技"]
MAT_CATS = ["金屬原料", "電鍍藥水", "包材", "五金件", "耗材"]
MATERIALS = [
    ("銅捲 C2680", "金屬原料", "kg", 320), ("磷青銅捲 C5191", "金屬原料", "kg", 410),
    ("不鏽鋼板 SUS304", "金屬原料", "kg", 95), ("不鏽鋼捲 SUS301", "金屬原料", "kg", 110),
    ("鋁捲 A1050", "金屬原料", "kg", 130), ("鋁錠 ADC12", "金屬原料", "kg", 88),
    ("鍍鎳藥水", "電鍍藥水", "L", 680), ("鍍金藥水", "電鍍藥水", "L", 4200),
    ("鍍錫藥水", "電鍍藥水", "L", 520), ("脫脂劑", "電鍍藥水", "L", 180),
    ("塑膠包材 PET", "包材", "kg", 60), ("載帶 Carrier Tape", "包材", "卷", 240),
    ("防靜電袋", "包材", "包", 45), ("紙箱", "包材", "個", 12),
    ("螺絲 M2", "五金件", "千顆", 80), ("彈片", "五金件", "千件", 150),
    ("沖壓油", "耗材", "L", 95), ("研磨輪", "耗材", "個", 320),
]
PROD_CATS = ["連接器端子", "屏蔽罩", "散熱片", "精密沖壓件", "電鍍件", "組裝模組"]
PROD_PREFIX = {"連接器端子": "TRM", "屏蔽罩": "SHD", "散熱片": "HSK",
               "精密沖壓件": "STP", "電鍍件": "PLT", "組裝模組": "ASM"}
MACHINE_DEFS = [
    ("高速沖床 #1", "沖壓線", "沖壓"), ("高速沖床 #2", "沖壓線", "沖壓"),
    ("精密沖床 #3", "沖壓線", "沖壓"), ("連續電鍍線 #1", "電鍍線", "電鍍"),
    ("連續電鍍線 #2", "電鍍線", "電鍍"), ("CNC 加工 #1", "CNC線", "CNC"),
    ("CNC 加工 #2", "CNC線", "CNC"), ("自動組裝機 #1", "組裝線", "組裝"),
    ("自動組裝機 #2", "組裝線", "組裝"), ("注塑機 #1", "成型線", "成型"),
    ("雷射切割 #1", "加工線", "雷切"), ("CCD 檢測機 #1", "檢測線", "檢測"),
]
DOWNTIME_REASONS = ["換模", "保養", "故障維修", "缺料待機", "品質調機", "教育訓練", "停電"]
DEFECT_TYPES = ["毛邊", "尺寸超差", "刮傷", "鍍層不良", "變形", "髒污", "缺件"]

SCHEMA = """
DROP TABLE IF EXISTS quality_inspections CASCADE;
DROP TABLE IF EXISTS production_orders CASCADE;
DROP TABLE IF EXISTS machine_downtime CASCADE;
DROP TABLE IF EXISTS sales_order_items CASCADE;
DROP TABLE IF EXISTS sales_orders CASCADE;
DROP TABLE IF EXISTS purchase_order_items CASCADE;
DROP TABLE IF EXISTS purchase_orders CASCADE;
DROP TABLE IF EXISTS bom CASCADE;
DROP TABLE IF EXISTS inventory CASCADE;
DROP TABLE IF EXISTS machines CASCADE;
DROP TABLE IF EXISTS products CASCADE;
DROP TABLE IF EXISTS materials CASCADE;
DROP TABLE IF EXISTS suppliers CASCADE;
DROP TABLE IF EXISTS customers CASCADE;

CREATE TABLE customers (
    id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL,
    region TEXT, industry TEXT, credit_limit NUMERIC(14,0), active BOOLEAN DEFAULT true
);
CREATE TABLE suppliers (
    id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL,
    region TEXT, material_category TEXT, rating NUMERIC(2,1),  -- 1~5 星
    on_time_rate NUMERIC(4,1), payment_terms TEXT               -- 準交率 %
);
CREATE TABLE products (
    id SERIAL PRIMARY KEY, sku TEXT UNIQUE, name TEXT NOT NULL, category TEXT,
    unit_price NUMERIC(10,2), unit_cost NUMERIC(10,2), status TEXT DEFAULT '量產'
);
CREATE TABLE materials (
    id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT NOT NULL, category TEXT,
    unit TEXT, unit_cost NUMERIC(10,2), safety_stock NUMERIC(12,1)
);
CREATE TABLE bom (
    id SERIAL PRIMARY KEY, product_id INT REFERENCES products(id),
    material_id INT REFERENCES materials(id), qty_per_unit NUMERIC(10,4)
);
CREATE TABLE machines (
    id SERIAL PRIMARY KEY, code TEXT UNIQUE, name TEXT, line TEXT, type TEXT,
    status TEXT DEFAULT '運轉中', capacity_per_hour INT
);
CREATE TABLE inventory (
    id SERIAL PRIMARY KEY, item_type TEXT,           -- product / material
    item_id INT, item_name TEXT, warehouse TEXT,
    qty_on_hand NUMERIC(14,1), unit_cost NUMERIC(10,2), as_of_date DATE
);
CREATE TABLE sales_orders (
    id SERIAL PRIMARY KEY, so_no TEXT UNIQUE, customer_id INT REFERENCES customers(id),
    sales_rep_emp_id INT, order_date DATE, required_date DATE, ship_date DATE,
    status TEXT, total_amount NUMERIC(14,2)            -- 已出貨/生產中/已取消
);
CREATE TABLE sales_order_items (
    id SERIAL PRIMARY KEY, sales_order_id INT REFERENCES sales_orders(id),
    product_id INT REFERENCES products(id), qty INT,
    unit_price NUMERIC(10,2), amount NUMERIC(14,2)
);
CREATE TABLE purchase_orders (
    id SERIAL PRIMARY KEY, po_no TEXT UNIQUE, supplier_id INT REFERENCES suppliers(id),
    order_date DATE, expected_date DATE, received_date DATE,
    status TEXT, total_amount NUMERIC(14,2)
);
CREATE TABLE purchase_order_items (
    id SERIAL PRIMARY KEY, purchase_order_id INT REFERENCES purchase_orders(id),
    material_id INT REFERENCES materials(id), qty NUMERIC(12,1),
    unit_cost NUMERIC(10,2), amount NUMERIC(14,2)
);
CREATE TABLE production_orders (
    id SERIAL PRIMARY KEY, wo_no TEXT UNIQUE, product_id INT REFERENCES products(id),
    machine_id INT REFERENCES machines(id), planned_qty INT, good_qty INT,
    scrap_qty INT, start_date DATE, end_date DATE, status TEXT
);
CREATE TABLE quality_inspections (
    id SERIAL PRIMARY KEY, production_order_id INT REFERENCES production_orders(id),
    inspect_date DATE, sample_size INT, defect_count INT,
    result TEXT, defect_type TEXT                       -- 合格 / 不合格
);
CREATE TABLE machine_downtime (
    id SERIAL PRIMARY KEY, machine_id INT REFERENCES machines(id),
    log_date DATE, downtime_hours NUMERIC(5,1), reason TEXT
);
"""


def rand_date(a=START, b=END):
    return a + timedelta(days=random.randint(0, (b - a).days))


def main() -> None:
    with psycopg.connect(DATABASE_URL) as conn, conn.cursor() as cur:
        cur.execute(SCHEMA)

        # 取既有員工當業務代表（HR 已 seed 時）
        cur.execute("SELECT id FROM employees")
        emp_ids = [r[0] for r in cur.fetchall()] or [None]

        # 客戶
        cust = []
        for i, name in enumerate(CUST_NAMES, 1):
            cur.execute(
                "INSERT INTO customers (code,name,region,industry,credit_limit,active) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"C{i:03d}", name, random.choice(REGIONS), random.choice(CUST_INDUSTRY),
                 random.choice([5, 10, 20, 30, 50]) * 1_000_000,
                 random.random() > 0.1))
            cust.append(cur.fetchone()[0])

        # 供應商
        supp = []
        for i, name in enumerate(SUPP_NAMES, 1):
            cur.execute(
                "INSERT INTO suppliers (code,name,region,material_category,rating,on_time_rate,payment_terms)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"S{i:03d}", name, random.choice(REGIONS[:3]), random.choice(MAT_CATS),
                 round(random.uniform(2.5, 5.0), 1), round(random.uniform(75, 99), 1),
                 random.choice(["月結30天", "月結60天", "月結45天", "貨到付款"])))
            supp.append(cur.fetchone()[0])

        # 原物料
        mats = []
        for i, (name, catg, unit, cost) in enumerate(MATERIALS, 1):
            c = round(cost * random.uniform(0.9, 1.1), 2)
            cur.execute(
                "INSERT INTO materials (code,name,category,unit,unit_cost,safety_stock) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"M{i:03d}", name, catg, unit, c, random.choice([200, 500, 1000, 2000])))
            mats.append((cur.fetchone()[0], c))

        # 產品（含售價/成本，毛利 15~45%）
        prods = []
        for i in range(1, 41):
            catg = random.choice(PROD_CATS)
            cost = round(random.uniform(3, 60), 2)
            price = round(cost * random.uniform(1.18, 1.55), 2)
            sku = f"{PROD_PREFIX[catg]}-{random.randint(1000, 9999)}"
            cur.execute(
                "INSERT INTO products (sku,name,category,unit_price,unit_cost,status) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (sku, f"{catg} {sku}", catg, price, cost,
                 random.choices(["量產", "試產", "停產"], weights=[85, 10, 5])[0]))
            prods.append((cur.fetchone()[0], price, cost))

        # BOM：每個產品 2~5 種原料
        for pid, _, _ in prods:
            for mid, _ in random.sample(mats, random.randint(2, 5)):
                cur.execute("INSERT INTO bom (product_id,material_id,qty_per_unit) VALUES (%s,%s,%s)",
                            (pid, mid, round(random.uniform(0.01, 2.5), 4)))

        # 機台
        machs = []
        for i, (name, line, typ) in enumerate(MACHINE_DEFS, 1):
            cur.execute(
                "INSERT INTO machines (code,name,line,type,status,capacity_per_hour) "
                "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"EQ{i:02d}", name, line, typ,
                 random.choices(["運轉中", "保養中", "停機"], weights=[88, 8, 4])[0],
                 random.choice([500, 800, 1200, 2000, 3000])))
            machs.append(cur.fetchone()[0])

        # 銷售訂單 + 明細（600 筆）
        for i in range(1, 601):
            od = rand_date()
            req = od + timedelta(days=random.randint(14, 45))
            status = random.choices(["已出貨", "生產中", "已取消"], weights=[78, 18, 4])[0]
            ship = None
            if status == "已出貨":
                # 多數準交，少數延遲
                delta = random.randint(-8, 3) if random.random() > 0.18 else random.randint(4, 20)
                ship = req + timedelta(days=delta)
            cur.execute(
                "INSERT INTO sales_orders (so_no,customer_id,sales_rep_emp_id,order_date,"
                "required_date,ship_date,status,total_amount) VALUES (%s,%s,%s,%s,%s,%s,%s,0) RETURNING id",
                (f"SO{od:%y%m}{i:04d}", random.choice(cust), random.choice(emp_ids),
                 od, req, ship, status))
            soid = cur.fetchone()[0]
            total = 0
            for _ in range(random.randint(1, 4)):
                pid, price, _ = random.choice(prods)
                qty = random.choice([500, 1000, 2000, 5000, 10000, 20000])
                amt = round(price * qty, 2)
                total += amt
                cur.execute("INSERT INTO sales_order_items (sales_order_id,product_id,qty,unit_price,amount)"
                            " VALUES (%s,%s,%s,%s,%s)", (soid, pid, qty, price, amt))
            cur.execute("UPDATE sales_orders SET total_amount=%s WHERE id=%s", (round(total, 2), soid))

        # 採購單 + 明細（350 筆）
        for i in range(1, 351):
            od = rand_date()
            exp = od + timedelta(days=random.randint(7, 30))
            status = random.choices(["已入庫", "已下單", "已取消"], weights=[80, 16, 4])[0]
            recv = None
            if status == "已入庫":
                recv = exp + timedelta(days=(random.randint(-3, 2) if random.random() > 0.2 else random.randint(3, 14)))
            cur.execute(
                "INSERT INTO purchase_orders (po_no,supplier_id,order_date,expected_date,"
                "received_date,status,total_amount) VALUES (%s,%s,%s,%s,%s,%s,0) RETURNING id",
                (f"PO{od:%y%m}{i:04d}", random.choice(supp), od, exp, recv, status))
            poid = cur.fetchone()[0]
            total = 0
            for _ in range(random.randint(1, 3)):
                mid, cost = random.choice(mats)
                qty = random.choice([100, 200, 500, 1000, 2000])
                amt = round(cost * qty, 2)
                total += amt
                cur.execute("INSERT INTO purchase_order_items (purchase_order_id,material_id,qty,unit_cost,amount)"
                            " VALUES (%s,%s,%s,%s,%s)", (poid, mid, qty, cost, amt))
            cur.execute("UPDATE purchase_orders SET total_amount=%s WHERE id=%s", (round(total, 2), poid))

        # 生產工單（450 筆）+ 品檢
        for i in range(1, 451):
            pid = random.choice([p[0] for p in prods])
            mid = random.choice(machs)
            sd = rand_date()
            ed = sd + timedelta(days=random.randint(1, 7))
            planned = random.choice([1000, 2000, 5000, 10000, 20000])
            status = random.choices(["已完工", "生產中"], weights=[82, 18])[0]
            scrap = int(planned * random.uniform(0.005, 0.08))   # 0.5~8% 報廢
            good = planned - scrap if status == "已完工" else int((planned - scrap) * random.uniform(0.3, 0.9))
            cur.execute(
                "INSERT INTO production_orders (wo_no,product_id,machine_id,planned_qty,good_qty,"
                "scrap_qty,start_date,end_date,status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                (f"WO{sd:%y%m}{i:04d}", pid, mid, planned, good, scrap, sd,
                 ed if status == "已完工" else None, status))
            woid = cur.fetchone()[0]
            if status == "已完工" and random.random() > 0.25:   # 多數有品檢
                sample = random.choice([32, 50, 80, 125])
                defects = int(sample * random.uniform(0, 0.06))
                cur.execute(
                    "INSERT INTO quality_inspections (production_order_id,inspect_date,sample_size,"
                    "defect_count,result,defect_type) VALUES (%s,%s,%s,%s,%s,%s)",
                    (woid, ed, sample, defects, "合格" if defects <= sample * 0.02 else "不合格",
                     random.choice(DEFECT_TYPES) if defects else None))

        # 機台稼動異常（每台 ~30 筆）
        for mid in machs:
            for _ in range(random.randint(20, 36)):
                cur.execute("INSERT INTO machine_downtime (machine_id,log_date,downtime_hours,reason)"
                            " VALUES (%s,%s,%s,%s)",
                            (mid, rand_date(), round(random.uniform(0.5, 8), 1),
                             random.choice(DOWNTIME_REASONS)))

        # 庫存快照（產品 + 原料 各一筆，含是否低於安全庫存的情境）
        for pid, _, cost in prods:
            cur.execute("INSERT INTO inventory (item_type,item_id,item_name,warehouse,qty_on_hand,unit_cost,as_of_date)"
                        " SELECT 'product',%s,name,%s,%s,%s,%s FROM products WHERE id=%s",
                        (pid, random.choice(["成品倉A", "成品倉B"]),
                         round(random.uniform(0, 30000), 1), cost, END, pid))
        for mid, cost in mats:
            cur.execute("INSERT INTO inventory (item_type,item_id,item_name,warehouse,qty_on_hand,unit_cost,as_of_date)"
                        " SELECT 'material',%s,name,'原料倉',%s,%s,%s FROM materials WHERE id=%s",
                        (mid, round(random.uniform(0, 4000), 1), cost, END, mid))

        conn.commit()

        # 摘要
        tables = ["customers", "suppliers", "products", "materials", "bom", "machines",
                  "sales_orders", "sales_order_items", "purchase_orders", "purchase_order_items",
                  "production_orders", "quality_inspections", "machine_downtime", "inventory"]
        print("製造業資料完成（2025-01 ~ 2026-06）：")
        for t in tables:
            cur.execute(f"SELECT count(*) FROM {t}")
            print(f"  {t:24s} {cur.fetchone()[0]:>6} 筆")


if __name__ == "__main__":
    main()
