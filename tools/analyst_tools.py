"""分析覆核工具：對外給老闆的關鍵 KPI，輸出前先做「合理性/區間校驗」（白皮書 §25 P0-4）。

text-to-SQL 可能把 KPI 算錯（JOIN 爆量、忘了排除『已取消』、除錯分母…），對外給決策
數字錯一次信任就崩。analyst 在報告每個關鍵數字前先用 check_kpi 覆核：通過才當事實輸出，
不通過就在報告標示 ⚠️ 並重跑一條獨立查詢確認，不把可疑數字直接當結論。

純規則檢查、不連資料庫；「第二來源」的實查覆核由 analyst 再跑一條獨立查詢達成。
"""

from langchain_core.tools import tool

# kind -> (合理下限, 合理上限, 說明)。None 表示該側不設限。
_KINDS = {
    "rate":   (0.0, 100.0, "率/佔比（%）應在 0~100"),
    "margin": (-100.0, 100.0, "毛利/利潤率（%）通常在 -100~100"),
    "money":  (0.0, None, "金額應 ≥ 0"),
    "count":  (0.0, None, "數量/筆數應為非負整數"),
    "growth": (-100.0, 1000.0, "成長率（%）可負，但超過 +1000% 多半是查詢爆量"),
}


@tool
def check_kpi(
    name: str,
    value: float,
    kind: str = "rate",
    low: float | None = None,
    high: float | None = None,
) -> str:
    """對關鍵 KPI 做合理性/區間校驗，回 ✅ 合理 或 ⚠️ 異常+原因（白皮書 §25 P0-4）。

    對外給老闆的每個關鍵數字，先用這個覆核再寫進報告：✅ 才當事實輸出；⚠️ 就在報告
    標示此數字可疑，並重跑一條「獨立的」查詢確認是真訊號還是查詢算錯，不要把可疑數字
    直接當結論。

    Args:
        name: KPI 名稱（如「毛利率」「準交率」「Q2 營收」），用於回覆訊息。
        value: 要校驗的數值（百分比請給 0~100 的數，不要給 0~1 的小數）。
        kind: rate（率/佔比,0~100）| margin（毛利/利潤率,-100~100）| money（金額,≥0）
              | count（數量,整數≥0）| growth（成長率,可負,過大標示）| range（自訂 low/high）。
        low, high: kind="range" 時自訂的合理區間（任一可省略表示該側不限）。
    """
    if kind == "range":
        lo, hi, desc = low, high, "自訂區間"
    else:
        spec = _KINDS.get(kind)
        if spec is None:
            return f"⚠️ check_kpi：未知的 kind『{kind}』，可用：{', '.join(_KINDS)}, range。"
        lo, hi, desc = spec

    reasons = []
    if lo is not None and value < lo:
        reasons.append(f"低於合理下限 {lo}")
    if hi is not None and value > hi:
        reasons.append(f"高於合理上限 {hi}")
    if kind == "count" and float(value) != int(value):
        reasons.append("數量應為整數")

    if reasons:
        return (
            f"⚠️ {name}={value} 異常（{desc}）：{'；'.join(reasons)}。"
            "請重跑一條獨立查詢覆核，並在報告中標示此數字可疑、不要直接當結論。"
        )
    return f"✅ {name}={value} 通過合理性校驗（{desc}）。"
