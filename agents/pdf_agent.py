"""PDF 分析 Agent：讀取 PDF → 轉文字 → 分析重點 → 條列式輸出。"""

from agents.base_agent import create_agent
from tools.pdf_tools import extract_pdf_text

SYSTEM_PROMPT = """你是一個 ERP 系統的 PDF 文件分析助理。

當使用者提供 PDF 檔案路徑時，請依下列步驟處理：
1. 使用 extract_pdf_text 工具讀取該 PDF 的文字內容。
2. 理解並分析文件的重點。
3. 以「條列式」（bullet points）輸出重點摘要，使用繁體中文。

輸出格式範例：
- 重點一
- 重點二
- 重點三

若 PDF 無法擷取文字，請如實告知使用者。"""

TOOLS = [extract_pdf_text]


def build_pdf_agent(with_memory=True):
    """建立 PDF 分析 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


# 單獨使用、自帶記憶的標準實例
pdf_agent = build_pdf_agent()


if __name__ == "__main__":
    # 簡單的本機測試：python -m agents.pdf_agent <pdf路徑>
    import sys

    path = sys.argv[1] if len(sys.argv) > 1 else "請提供 PDF 路徑"
    result = pdf_agent.invoke(
        {"messages": [("user", f"請分析這份 PDF：{path}")]},
        config={"configurable": {"thread_id": "demo"}},
    )
    print(result["messages"][-1].content)
