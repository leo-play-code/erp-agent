#!/usr/bin/env python
"""掃描 Obsidian vault 的 [[ ]] 連結,輸出關聯狀態:統計 + Mermaid 關聯圖 + 斷鏈清單。

產出一個 `知識庫關聯圖.md` 放回 vault(Obsidian 會直接渲染 Mermaid),並在終端印摘要。
用法:venv/bin/python graph_view.py [vault目錄,預設 ~/erp-kb]
"""
import re
import sys
from collections import defaultdict
from pathlib import Path

OUT_NAME = "知識庫關聯圖.md"
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def main() -> None:
    vault = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/erp-kb").expanduser()
    files = [p for p in vault.glob("*.md") if p.name != OUT_NAME]
    titles = {p.stem for p in files}

    edges: list[tuple[str, str]] = []
    out_deg: dict[str, int] = defaultdict(int)
    in_deg: dict[str, int] = defaultdict(int)
    for p in files:
        src = p.stem
        for raw in LINK_RE.findall(p.read_text("utf-8")):
            tgt = raw.split("|")[0].split("#")[0].strip()  # 去別名/標題錨點
            if not tgt:
                continue
            edges.append((src, tgt))
            out_deg[src] += 1
            in_deg[tgt] += 1

    nodes = titles | {t for _, t in edges}
    broken = sorted({t for _, t in edges if t not in titles})
    orphans = sorted(t for t in titles if in_deg[t] == 0 and out_deg[t] == 0)
    top = sorted(titles, key=lambda t: in_deg[t], reverse=True)[:12]

    # Mermaid:中文標題用 id 對應,避免特殊字元問題
    ids = {n: f"n{i}" for i, n in enumerate(sorted(nodes))}
    lines = ["```mermaid", "graph LR"]
    for n in sorted(nodes):
        shape = f'{ids[n]}["{n}"]' if n in titles else f'{ids[n]}("{n}❓")'  # ❓=尚未建立的目標
        lines.append(f"  {shape}")
    for s, t in sorted(set(edges)):
        lines.append(f"  {ids[s]} --> {ids[t]}")
    lines.append("```")
    mermaid = "\n".join(lines)

    md = [
        "---", "tags: [關聯圖, 自動產生]", "---",
        "# 知識庫關聯圖", "",
        f"- 筆記總數(實體檔):**{len(titles)}**",
        f"- 連結總數:**{len(edges)}**(去重 {len(set(edges))})",
        f"- 圖中節點(含被連到但尚未建立者):**{len(nodes)}**",
        f"- 斷鏈(連到不存在的筆記):**{len(broken)}**",
        f"- 孤島(無進出連結):**{len(orphans)}**", "",
        "## 最多人連結的中樞(in-degree Top 12)",
        *[f"{i}. **{t}** ← 被 {in_deg[t]} 篇連結" for i, t in enumerate(top, 1)], "",
    ]
    if broken:
        md += ["## ⚠ 斷鏈(目標筆記不存在,建議補建或改名)",
               *[f"- [[{b}]]" for b in broken], ""]
    if orphans:
        md += ["## 孤島筆記(還沒接上任何連結)",
               *[f"- [[{o}]]" for o in orphans], ""]
    md += ["## 關聯圖(Obsidian 會直接渲染)", "", mermaid, ""]
    (vault / OUT_NAME).write_text("\n".join(md), "utf-8")

    # 終端摘要
    print(f"vault:{vault}")
    print(f"筆記 {len(titles)} 篇 / 連結 {len(edges)} 條 / 斷鏈 {len(broken)} / 孤島 {len(orphans)}")
    print("\n最多人連結的中樞:")
    for i, t in enumerate(top, 1):
        print(f"  {i:2}. {t}（被 {in_deg[t]} 篇連結）")
    if broken:
        print("\n⚠ 斷鏈(連到不存在的筆記):", "、".join(broken))
    if orphans:
        print("\n孤島(無任何連結):", "、".join(orphans))
    print(f"\n已寫出關聯圖:{vault / OUT_NAME}(在 Obsidian 開啟即見 Mermaid 圖)")


if __name__ == "__main__":
    main()
