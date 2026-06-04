"""圖片轉文字（OCR）工具。

利用視覺模型辨識圖片中的文字。使用 base_agent.get_llm() 取得模型，
維持「模型只在一處設定」的原則（需為支援圖片輸入的模型，如 gpt-4o-mini）。
"""

import base64
import mimetypes

from langchain_core.messages import HumanMessage
from langchain_core.tools import tool

from agents.base_agent import get_llm


@tool
def image_to_text(file_path: str) -> str:
    """辨識並回傳圖片檔中的文字內容（OCR）。

    Args:
        file_path: 圖片檔案路徑（png / jpg / webp 等）。
    """
    with open(file_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode()
    mime = mimetypes.guess_type(file_path)[0] or "image/png"

    message = HumanMessage(
        content=[
            {
                "type": "text",
                "text": "請辨識並輸出這張圖片中的所有文字，盡量保留原本的換行與排列；"
                "只輸出文字內容，不要額外說明。",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{encoded}"},
            },
        ]
    )
    result = get_llm().invoke([message]).content
    return result or "（圖片中沒有偵測到文字。）"
