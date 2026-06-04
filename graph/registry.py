"""Agent 註冊表 —— 新增 Agent 的「唯一登記處」。

要把一個新 Agent 接進 ERP 流程，只需在 AGENTS 加一筆：

    "名稱": {
        "desc":  "這個 Agent 負責什麼（會交給 router 判斷路由用，請寫清楚）",
        "build": 該 Agent 的建構器函數（需支援 with_memory 參數）,
        "accepts_file": 這個 Agent 是否會用到上傳的檔案（前端據此決定是否顯示上傳欄）,
        "needs_text": 選填，預設 True；設 False 表示只收檔案、不需文字輸入（如 image OCR）,
    }

graph/erp_graph.py 會從這個字典「自動」生成：router 的合法選項、router 的
提示詞、流程節點、以及路由邊。除了寫 Agent/Tool 本身的檔案，不需要再改其他地方。
"""

from agents.email_agent import build_email_agent
from agents.image_agent import build_image_agent
from agents.inventory_agent import build_inventory_agent
from agents.pdf_agent import build_pdf_agent
from agents.ppt_agent import build_ppt_agent
from agents.analyst_agent import build_analyst_agent
from agents.rag_agent import build_rag_agent
from agents.report_agent import build_report_agent
from agents.sql_agent import build_sql_agent

AGENTS = {
    "pdf": {
        "desc": "PDF、文件、檔案的讀取與重點分析",
        "build": build_pdf_agent,
        "accepts_file": True,
    },
    "inventory": {
        "desc": "庫存、品項、數量、儲位的查詢",
        "build": build_inventory_agent,
        "accepts_file": False,
    },
    "sql": {
        "desc": "查詢 ERP 資料庫的具體數字：人資（員工/部門/特休/請假）與製造營運"
                "（客戶/訂單/產品/採購/生產工單/品檢/機台/庫存）。單一明確的查詢問題用它。",
        "build": build_sql_agent,
        "accepts_file": False,
    },
    "analyst": {
        "desc": "決策分析師：跨領域整合製造營運資料（營收毛利、準交、良率、品質、庫存、"
                "供應商、客戶集中度），算 KPI、找趨勢與風險、給老闆可拍板的決策建議。"
                "凡是『分析』『趨勢』『為什麼』『該怎麼決策』類的整合性問題用它。",
        "build": build_analyst_agent,
        "accepts_file": False,
    },
    "rag": {
        "desc": "知識庫問答（RAG）：用語意檢索查回已建檔文件的內容並標來源，回答『根據公司"
                "文件 / 知識庫 / 已上傳的資料』類問題。只做問答，不負責建索引（建索引請到"
                "後台知識庫管理操作）。",
        "build": build_rag_agent,
        "accepts_file": False,
    },
    "ppt": {
        "desc": "製作 PowerPoint 簡報，依主題或大綱產出可下載的 .pptx",
        "build": build_ppt_agent,
        "accepts_file": False,
    },
    "email": {
        "desc": "撰寫商務 email 草稿（擬主旨與內文，不寄出）",
        "build": build_email_agent,
        "accepts_file": False,
    },
    "report": {
        "desc": "報表數據分析：對貼上的數據做摘要、趨勢與洞察",
        "build": build_report_agent,
        "accepts_file": False,
    },
    "image": {
        "desc": "圖片轉文字（OCR）：辨識圖片中的文字內容",
        "build": build_image_agent,
        "accepts_file": True,
        "needs_text": False,  # 只收圖片，前端不顯示文字輸入框
    },
}
