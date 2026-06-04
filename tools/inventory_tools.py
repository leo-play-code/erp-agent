"""庫存相關工具。

這裡用一個寫死的字典當作示範資料源；之後可替換成真正的 ERP 資料庫查詢，
Agent 與流程都不需要更動。
"""

from langchain_core.tools import tool

_INVENTORY = {
    "螺絲": {"stock": 1200, "unit": "顆", "location": "A-01"},
    "鋼板": {"stock": 35, "unit": "片", "location": "B-12"},
    "潤滑油": {"stock": 8, "unit": "桶", "location": "C-05"},
}


@tool
def query_inventory(item_name: str) -> str:
    """查詢指定品項的庫存數量與儲位。

    Args:
        item_name: 品項名稱（例如：螺絲、鋼板、潤滑油）。
    """
    item = _INVENTORY.get(item_name.strip())
    if not item:
        return f"查無品項「{item_name}」。目前可查詢：{'、'.join(_INVENTORY)}"
    return (
        f"品項：{item_name}｜庫存：{item['stock']} {item['unit']}｜儲位：{item['location']}"
    )
