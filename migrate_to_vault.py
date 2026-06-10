#!/usr/bin/env python
"""一次性工具:從現有 rag_index/index.json 產生 Obsidian vault 初稿(Phase 0 搬遷 / 舊資料補轉)。

每個來源分兩種處理:
  - 原始檔還在(index 有 path 且檔案存在)→ 用「現在的 MarkItDown」重新轉一次 → 寫成乾淨 .md。
    這就是「補上當年可能沒真正走到的 MarkItDown」。原始檔同時複製到 <vault>/raw/ 供追溯。
  - 原始檔遺失(貼上型 / folder 已不存在 / 無 path)→ 只能把索引裡的 chunk 文字接回成 .md,
    並在檔頭標註「由索引還原、原始檔遺失,請人工校對」。

產出後請在 Obsidian 裡把它整理成原子化、用 [[ ]] 互聯的筆記,再把 watch_rag 指向這個 vault。
本工具只「寫入新的 vault 目錄」,不動 index.json、不動 uploads/,安全、可重跑。

用法:venv/bin/python migrate_to_vault.py [vault目錄,預設 ~/erp-kb]
"""
import json
import shutil
import sys
from collections import OrderedDict
from pathlib import Path

from tools.rag_tools import INDEX_FILE, _read_file


def _safe_stem(source: str) -> str:
    """來源檔名 → 安全的 .md 檔名主幹(去副檔名;sync_folder 來源可能含子路徑)。"""
    stem = Path(source).stem.replace("/", "_").replace("\\", "_").strip()
    return stem or "untitled"


def main() -> None:
    vault = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path("~/erp-kb").expanduser()
    raw = vault / "raw"
    vault.mkdir(parents=True, exist_ok=True)
    raw.mkdir(exist_ok=True)

    items = json.loads(INDEX_FILE.read_text("utf-8"))["items"]
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()  # 依來源分組,保留出現順序(=chunk 順序)
    for it in items:
        groups.setdefault(it["source"], []).append(it)

    reconverted, restored = [], []
    for source, segs in groups.items():
        out = vault / f"{_safe_stem(source)}.md"
        path = segs[0].get("path")
        if path and Path(path).exists():  # 原始檔還在 → 用現行 MarkItDown 重轉
            text = _read_file(path)
            shutil.copy2(path, raw / Path(path).name)  # 留底供追溯
            head = f"> 來源:{source}(已用現行 MarkItDown 重新轉換,原始檔存於 raw/)"
            out.write_text(f"# {Path(source).stem}\n\n{head}\n\n{text}\n", "utf-8")
            reconverted.append(source)
        else:  # 原始檔遺失 → 由索引片段還原
            body = "\n\n".join(s["text"] for s in segs)
            head = f"> 來源:{source}(原始檔已遺失,以下由索引片段還原,可能不完整,請人工校對)"
            out.write_text(f"# {Path(source).stem}\n\n{head}\n\n{body}\n", "utf-8")
            restored.append(source)

    print(f"vault 初稿已產生於:{vault}\n")
    print(f"✓ 重新 MarkItDown 轉換({len(reconverted)}):")
    for s in reconverted:
        print(f"    - {s}")
    print(f"\n⚠ 由索引還原、需人工校對({len(restored)}):")
    for s in restored:
        print(f"    - {s}")
    print("\n下一步:")
    print("  1. 在 Obsidian 開啟此 vault,整理成原子化、用 [[ ]] 互聯的筆記。")
    print(f"  2. 先備份舊索引:cp rag_index/index.json rag_index/index.json.bak")
    print(f"  3. 確認後把 watch 指向 vault:venv/bin/python watch_rag.py {vault}")


if __name__ == "__main__":
    main()
