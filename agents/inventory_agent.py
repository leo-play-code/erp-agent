"""庫存查詢 Agent：查詢品項庫存數量與儲位。"""

from agents.base_agent import create_agent
from tools.inventory_tools import query_inventory

SYSTEM_PROMPT = """你是一個 ERP 系統的庫存查詢助理。

當使用者詢問某個品項的庫存時：
1. 使用 query_inventory 工具查詢該品項。
2. 以繁體中文清楚回覆庫存數量與儲位。
3. 若該品項不存在，請告知使用者目前可查詢哪些品項。"""

TOOLS = [query_inventory]


def build_inventory_agent(with_memory=True):
    """建立庫存查詢 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


# 單獨使用、自帶記憶的標準實例
inventory_agent = build_inventory_agent()


if __name__ == "__main__":
    result = inventory_agent.invoke(
        {"messages": [("user", "螺絲還有多少庫存？")]},
        config={"configurable": {"thread_id": "demo"}},
    )
    print(result["messages"][-1].content)
