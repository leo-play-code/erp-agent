"""圖片轉文字 Agent：辨識圖片中的文字（OCR）並整理輸出。"""

from agents.base_agent import create_agent
from tools.image_tools import image_to_text

SYSTEM_PROMPT = """你是圖片轉文字（OCR）助理。

當使用者提供圖片時：
1. 使用 image_to_text 工具辨識圖片中的文字。
2. 將辨識結果用繁體中文清楚呈現。
若圖片中沒有文字，請如實告知使用者。"""

TOOLS = [image_to_text]


def build_image_agent(with_memory=True):
    """建立圖片轉文字 Agent。接入 LangGraph 流程時請傳 with_memory=False。"""
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)


image_agent = build_image_agent()
