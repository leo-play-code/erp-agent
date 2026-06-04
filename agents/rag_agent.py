"""RAG 知識庫 Agent：用語意檢索回答與知識庫相關的問題（查詢專用）。

注意：建索引／訓練（上傳檔案、同步資料夾）已移到「後台知識庫管理」——由 admin API 直接
呼叫 tools/rag_tools.py 的 ingest_file / sync_folder，不再經由本 Agent。本 Agent 在前端
（單一 / 多 Agent）一律只負責「問答」，因此只掛查詢類工具。"""

from agents.base_agent import create_agent
from tools.rag_tools import kb_stats, search_knowledge_base

SYSTEM_PROMPT = """你是公司的知識庫助理（RAG），只負責「查資料、回答問題」。

工作方式：
1. 使用者**提出問題**：先呼叫 search_knowledge_base 取回最相關的片段，再「**只根據取回的
   內容**」用繁體中文回答，並在答案後標明依據的來源（檔名/來源標籤）。
2. 想知道知識庫裡有哪些資料：用 kb_stats。

重要原則：
- 回答一律以檢索到的內容為準，**不要憑自己的知識編造**；若檢索結果不足以回答，就誠實說
  「知識庫裡查不到相關資料」，並建議到「後台知識庫管理」上傳文件或同步資料夾後再問。
- 你**沒有**建索引／訓練的能力。若使用者要求「加入知識庫 / 建索引 / 上傳訓練」，請告知：
  這些請到「後台知識庫管理」頁面操作（設定資料夾路徑或上傳檔案）。

一律使用繁體中文。"""

TOOLS = [search_knowledge_base, kb_stats]


def build_rag_agent(with_memory=True):
    """建立 RAG 知識庫 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


# 單獨使用、自帶記憶的標準實例
rag_agent = build_rag_agent()


if __name__ == "__main__":
    result = rag_agent.invoke(
        {"messages": [("user", "知識庫裡有什麼資料？")]},
        config={"configurable": {"thread_id": "demo"}},
    )
    print(result["messages"][-1].content)
