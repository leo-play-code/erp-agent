#!/usr/bin/env python
"""把 Obsidian vault 的 [[ ]] 關聯畫成 PNG(力導向佈局 + 分群上色),純 Pillow、免額外安裝。
用法:venv/bin/python draw_graph.py [vault,預設 ~/erp-kb] [輸出png,預設 ~/erp-kb/關聯圖.png]
"""
import math
import re
import sys
from collections import defaultdict
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = "/mnt/c/Windows/Fonts/msjh.ttc"  # 微軟正黑體
W, H, MARGIN = 3200, 2300, 150
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")

HUB_OF = {"新進人員指引": "onboarding", "請假辦法": "leave",
          "安全衛生守則": "safety", "2026Q1財報總覽": "financial"}
CENTRAL = {"知識庫總覽", "公司簡介"}
BUSINESS = {"品保規定", "報價政策", "採購單範例-PO-2026-001"}
COLORS = {"onboarding": (37, 99, 235), "leave": (13, 148, 136), "safety": (234, 88, 12),
          "financial": (124, 58, 237), "business": (22, 163, 74), "central": (220, 38, 38)}
# 各群初始落點(畫面方位,角度°)
SECTOR = {"central": None, "onboarding": 300, "leave": 10, "safety": 200,
          "financial": 130, "business": 245}


def cluster_of(node, links):
    if node in CENTRAL:
        return "central"
    if node in HUB_OF:
        return HUB_OF[node]
    if node in BUSINESS:
        return "business"
    if node.startswith("2026Q1"):
        return "financial"
    for hub in ("安全衛生守則", "請假辦法", "新進人員指引"):
        if hub in links:
            return HUB_OF[hub]
    return "onboarding"


def main():
    vault = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/erp-kb").expanduser()
    out = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else vault / "關聯圖.png"

    files = [p for p in vault.glob("*.md") if p.name not in ("知識庫關聯圖.md",)]
    links_of = {}
    for p in files:
        links_of[p.stem] = [r.split("|")[0].split("#")[0].strip()
                            for r in LINK_RE.findall(p.read_text("utf-8"))]
    nodes = list(links_of)
    idx = {n: i for i, n in enumerate(nodes)}
    edges = [(s, t) for s, ts in links_of.items() for t in ts if t in idx]

    indeg = defaultdict(int)
    for _, t in edges:
        indeg[t] += 1
    clu = {n: cluster_of(n, links_of[n]) for n in nodes}

    # 初始落點:依群方位 + 依索引散開(決定性,不用亂數)
    cx, cy = W / 2, H / 2
    pos = {}
    per = defaultdict(int)
    for n in nodes:
        c = clu[n]
        if c == "central":
            pos[n] = [cx + (40 if n == "公司簡介" else -40), cy]
            continue
        ang = math.radians(SECTOR[c])
        base = (cx + 760 * math.cos(ang), cy - 760 * math.sin(ang))
        k = per[c]; per[c] += 1
        a2 = k * 2.399  # 黃金角散開
        pos[n] = [base[0] + 230 * math.cos(a2) + (k % 5) * 7,
                  base[1] + 230 * math.sin(a2) + (k % 3) * 7]

    # Fruchterman-Reingold
    area = (W - 2 * MARGIN) * (H - 2 * MARGIN)
    k = 0.9 * math.sqrt(area / len(nodes))
    eset = set(edges)
    temp = (W) / 9
    for it in range(420):
        disp = {n: [0.0, 0.0] for n in nodes}
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.hypot(dx, dy) or 0.01
                f = k * k / d
                ux, uy = dx / d, dy / d
                disp[a][0] += ux * f; disp[a][1] += uy * f
                disp[b][0] -= ux * f; disp[b][1] -= uy * f
        for a, b in eset:
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.hypot(dx, dy) or 0.01
            f = d * d / k
            ux, uy = dx / d, dy / d
            disp[a][0] -= ux * f; disp[a][1] -= uy * f
            disp[b][0] += ux * f; disp[b][1] += uy * f
        # 群心向其方位輕拉,維持分群
        for n in nodes:
            c = clu[n]
            if c == "central":
                disp[n][0] += (cx - pos[n][0]) * 0.06; disp[n][1] += (cy - pos[n][1]) * 0.06
                continue
            ang = math.radians(SECTOR[c])
            tx, ty = cx + 820 * math.cos(ang), cy - 820 * math.sin(ang)
            disp[n][0] += (tx - pos[n][0]) * 0.035; disp[n][1] += (ty - pos[n][1]) * 0.035
        for n in nodes:
            dl = math.hypot(*disp[n]) or 0.01
            pos[n][0] += disp[n][0] / dl * min(dl, temp)
            pos[n][1] += disp[n][1] / dl * min(dl, temp)
            pos[n][0] = min(W - MARGIN, max(MARGIN, pos[n][0]))
            pos[n][1] = min(H - MARGIN, max(MARGIN, pos[n][1]))
        temp = max(temp * 0.965, 2.0)

    # 繪製
    img = Image.new("RGB", (W, H), (250, 250, 249))
    d = ImageDraw.Draw(img)
    for s, t in edges:  # 邊
        d.line([tuple(pos[s]), tuple(pos[t])], fill=(208, 208, 206), width=1)
    f_lab = ImageFont.truetype(FONT, 21)
    f_hub = ImageFont.truetype(FONT, 27)
    for n in nodes:  # 點
        r = 9 + min(indeg[n], 28) * 1.7
        x, y = pos[n]
        col = COLORS[clu[n]]
        d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(255, 255, 255), width=2)
    for n in nodes:  # 標籤(白描邊)
        x, y = pos[n]
        big = n in HUB_OF or n in CENTRAL
        fnt = f_hub if big else f_lab
        tw = d.textlength(n, font=fnt)
        d.text((x - tw / 2, y + 11 + min(indeg[n], 28) * 1.7), n, font=fnt,
               fill=(20, 20, 20), stroke_width=4, stroke_fill=(250, 250, 249))

    # 圖例
    lx, ly = MARGIN, MARGIN - 60
    leg = [("人資/工作規則", "onboarding"), ("請假", "leave"), ("安全衛生", "safety"),
           ("財報", "financial"), ("業務/採購", "business"), ("總覽中樞", "central")]
    fx = ImageFont.truetype(FONT, 24)
    for i, (lab, c) in enumerate(leg):
        px = lx + i * 300
        d.ellipse([px, ly, px + 26, ly + 26], fill=COLORS[c])
        d.text((px + 34, ly - 2), lab, font=fx, fill=(20, 20, 20))
    d.text((lx, MARGIN - 100), f"鉅祥知識庫關聯圖　筆記 {len(nodes)} 篇／連結 {len(edges)} 條",
           font=ImageFont.truetype(FONT, 30), fill=(20, 20, 20))

    img.save(out)
    print(f"已輸出:{out}（{W}x{H}）")


if __name__ == "__main__":
    main()
