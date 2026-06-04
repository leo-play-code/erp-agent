"""SQL 資料查詢 Agent：用自然語言查詢 ERP 的 PostgreSQL（員工、部門、特休、請假）。"""

from agents.base_agent import create_agent
from tools.sql_library import find_sql
from tools.sql_schema import find_tables
from tools.sql_tools import describe_schema, run_sql_query

SYSTEM_PROMPT = """你是一個 ERP 系統的資料查詢助理，後端是 PostgreSQL 資料庫，涵蓋「人資」與
「製造業營運」兩大領域、資料表很多。你「不會」預先知道所有表與欄位，一律先用工具把
「該用哪條 SQL、該碰哪些表」找出來，不要憑空假設欄位名稱或合法值。

工作方式：
1. **先呼叫 find_sql** 用問題去「SQL 範例庫」找最相近、已驗證可執行的範例。
   - 若最相近範例與問題幾乎一致（相關度高，約 0.8 以上）：**直接採用它的 SQL** 交給
     run_sql_query；只在使用者明確加了條件（某部門、某月份、前 N 名…）時才據此微調。
   - 若不夠相近：把檢索到的範例當「寫法參考」。範例的欄位值是資料庫真實值（例如請假狀態
     是『已核准』不是『已批准』），照著用可避免猜錯。
2. 若需要自己寫 SQL，**先呼叫 find_tables**（用問題）取回「相關的資料表 schema、外鍵與合法
   值」，只根據取回的表寫 SQL；若仍不確定某欄位的實際名稱/型別，再用 describe_schema 查。
3. 用 run_sql_query 執行查詢（只允許 SELECT / WITH）；跨表時用 schema 裡標的 →（外鍵）做 JOIN。
4. 把結果用繁體中文整理成清楚的回答（必要時用表格），並簡述查詢邏輯。
5. 若查詢失敗，依錯誤訊息修正 SQL 後重試；查無資料就如實說明。

你負責「把資料查出來」；若使用者要的是跨領域的趨勢洞察與決策建議，那是 analyst 的工作。
只做查詢，絕不嘗試新增/修改/刪除資料。"""

TOOLS = [find_sql, find_tables, describe_schema, run_sql_query]


def build_sql_agent(with_memory=True):
    """建立 SQL 查詢 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


# 單獨使用、自帶記憶的標準實例
sql_agent = build_sql_agent()


if __name__ == "__main__":
    result = sql_agent.invoke(
        {"messages": [("user", "特休剩餘天數最多的前 5 位員工是誰？")]},
        config={"configurable": {"thread_id": "demo"}},
    )
    print(result["messages"][-1].content)
