"""報表數據分析 Agent：對使用者提供的數據做摘要與洞察（純 LLM）。"""

from agents.base_agent import create_agent

SYSTEM_PROMPT = """你是報表數據分析助理。

使用者會貼上數據（表格、數字、KPI 等）。請：
1. 摘要關鍵數據。
2. 指出趨勢、異常與值得注意的洞察。
3. 必要時提出具體建議。

請用繁體中文、條列式呈現。"""

TOOLS = []  # 純 LLM，不需要工具


def build_report_agent(with_memory=True):
    """建立報表數據分析 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


report_agent = build_report_agent()
