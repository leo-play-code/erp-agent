"""Email 撰寫 Agent：擬商務 email 草稿（純 LLM，不寄出）。"""

from agents.base_agent import create_agent

SYSTEM_PROMPT = """你是商務 Email 撰寫助理。

根據使用者描述的情境與目的，擬一封專業、得體的繁體中文商務 email 草稿，
內容包含「主旨」與「內文」。只產生草稿，不會寄出。
若使用者提供的資訊不足，可做合理假設，並在最後簡短標註你做了哪些假設。"""

TOOLS = []  # 純 LLM，不需要工具


def build_email_agent(with_memory=True):
    """建立 Email 撰寫 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


email_agent = build_email_agent()
