#!/usr/bin/env python
"""LLM Wiki 自動編譯(Compile-on-Write)。

理念(參考 obsidian-llm-wiki + .drafts 審稿閘):
  raw/ 的原始文件 → MarkItDown 轉文字 → LLM 拆成「忠實的原子筆記」(連結到既有 wiki)
  → 寫進 .drafts/ 待人審 → 你確認後把筆記移到 wiki/ → 重新索引(sync_folder 指 wiki/)。

刻意比 olw 簡單而安全:**只產草稿、不自動覆蓋 wiki/**(尊重人工編輯);
已編譯過的原始檔(以內容雜湊判斷)會自動略過。複用專案既有 _read_file 與 get_llm(維持 OpenAI)。

用法:
  venv/bin/python compile_wiki.py                # 編譯桌面 vault 的 raw/ 中「新增/變動」的檔
  venv/bin/python compile_wiki.py --all          # 重新編譯 raw/ 全部
  venv/bin/python compile_wiki.py --file <路徑>   # 只編譯指定一個檔(草稿仍寫進 vault/.drafts)
  venv/bin/python compile_wiki.py <vault路徑> ...  # 指定別的 vault
需要 OPENAI_API_KEY。
"""
import hashlib
import json
import re
import sys
from pathlib import Path

from agents.base_agent import get_llm
from tools.rag_tools import _read_file

DEFAULT_VAULT = "/mnt/c/Users/Administrator/Desktop/erp-kb"
RAW_EXTS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".pptx",
            ".xlsx", ".xls", ".csv", ".html", ".htm"}
MAX_CHARS = 40000  # 單檔送進 LLM 的上限;超過會截斷並警示(超大檔建議先人工分段)
DELIM = re.compile(r"^<<<NOTE:\s*(.+?)\s*>>>\s*$", re.M)

PROMPT = """你是公司知識庫的「知識編譯器」。把下面這份來源文件拆成數篇「原子化」筆記(一個主題一篇),供 Obsidian 知識庫使用。

嚴格要求:
- 只寫文件「明確寫出」的內容,嚴禁推論、編造或用常識補足;數值/日期/條號照原文逐字。
- 不確定、或與常識/其他來源可能矛盾之處,用「⚠」標註,不要自己選一個答案。
- 可連結到既有筆記(用 [[標題]]);既有筆記清單:{titles}
- 每篇用一行 <<<NOTE: 檔名>>> 分隔(檔名=簡短中文標題,不含副檔名),格式:

<<<NOTE: 範例標題>>>
---
tags: [標籤1, 標籤2]
---
# 範例標題

> 來源:{source}

(忠實內容)

## 相關
- [[相關筆記標題]]

只輸出筆記內容,不要任何額外說明或前言。

=== 來源文件「{source}」內容 ===
{text}
"""


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", name.strip()) or "未命名"


def _compile_one(llm, path: Path, source_name: str, titles_str: str, drafts: Path) -> list[str]:
    """編譯單一檔成草稿,回傳寫出的草稿檔名清單。"""
    text = _read_file(str(path))
    if not text.strip():
        print(f"  ⚠ 「{source_name}」抽不到文字,略過。")
        return []
    if len(text) > MAX_CHARS:
        print(f"  ⚠ 「{source_name}」過長({len(text)}字),截斷至 {MAX_CHARS} 字(超大檔建議先人工分段)。")
        text = text[:MAX_CHARS]
    out = llm.invoke(PROMPT.format(titles=titles_str, source=source_name, text=text)).content
    pieces = DELIM.split(out)
    notes = list(zip(pieces[1::2], pieces[2::2]))
    if not notes:  # LLM 沒照分隔格式 → 整段當一篇
        notes = [(Path(source_name).stem, out)]
    written = []
    for name, body in notes:
        fn = f"{_safe_name(name)}.md"
        (drafts / fn).write_text(body.strip() + "\n", "utf-8")
        written.append(fn)
    return written


def _titles_str(wiki: Path) -> str:
    titles = sorted(p.stem for p in wiki.glob("*.md")) if wiki.is_dir() else []
    return "、".join(f"[[{t}]]" for t in titles) or "(目前無)"


def compile_file_to_drafts(file_path: str, vault: str = DEFAULT_VAULT) -> list[str]:
    """編譯單一檔到 vault/.drafts/,回傳產生的草稿檔名清單(給後端 API / 前端用)。"""
    v = Path(vault)
    drafts = v / ".drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    return _compile_one(get_llm(), Path(file_path), Path(file_path).name, _titles_str(v / "wiki"), drafts)


def compile_folder_to_drafts(folder: str, vault: str = DEFAULT_VAULT) -> dict:
    """把指定資料夾(含子資料夾)內所有文件都編譯成草稿到 vault/.drafts/,回傳 {files, drafts}。
    略過隱藏資料夾(.obsidian 等)。給後端「資料夾批次 AI 編譯」用。"""
    v = Path(vault)
    drafts = v / ".drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    titles_str = _titles_str(v / "wiki")
    base = Path(folder).expanduser()
    files = [p for p in base.rglob("*")
             if p.is_file() and p.suffix.lower() in RAW_EXTS
             and not any(part.startswith(".") for part in p.relative_to(base).parts)]
    llm = get_llm()
    made = 0
    for p in files:
        made += len(_compile_one(llm, p, p.name, titles_str, drafts))
    return {"files": len(files), "drafts": made}


def main() -> None:
    argv = sys.argv[1:]
    redo_all = "--all" in argv
    one_file = None
    if "--file" in argv:
        one_file = Path(argv[argv.index("--file") + 1]).expanduser()
    pos = [a for a in argv if not a.startswith("--")
           and (one_file is None or a != str(argv[argv.index("--file") + 1]))]
    vault = Path(pos[0]).expanduser() if pos else Path(DEFAULT_VAULT)
    raw, wiki, drafts = vault / "raw", vault / "wiki", vault / ".drafts"
    drafts.mkdir(parents=True, exist_ok=True)

    titles = sorted(p.stem for p in wiki.glob("*.md")) if wiki.is_dir() else []
    titles_str = "、".join(f"[[{t}]]" for t in titles) or "(目前無)"
    llm = get_llm()

    if one_file:  # 單檔模式:不動 state
        n = len(_compile_one(llm, one_file, one_file.name, titles_str, drafts))
        print(f"已編譯「{one_file.name}」→ 產生 {n} 篇草稿 → {drafts}")
        return

    state_f = drafts / ".compiled.json"
    state = json.loads(state_f.read_text("utf-8")) if state_f.exists() and not redo_all else {}
    raws = [p for p in raw.rglob("*") if p.is_file() and p.suffix.lower() in RAW_EXTS] if raw.is_dir() else []
    made = skipped = 0
    for p in raws:
        h = hashlib.md5(p.read_bytes()).hexdigest()
        key = str(p.relative_to(raw))
        if state.get(key) == h:
            skipped += 1
            continue
        print(f"編譯:{key}")
        made += len(_compile_one(llm, p, p.name, titles_str, drafts))
        state[key] = h
    state_f.write_text(json.dumps(state, ensure_ascii=False, indent=2), "utf-8")
    print(f"\nraw 掃到 {len(raws)} 檔;略過(未變){skipped};產生草稿 {made} 篇 → {drafts}")
    print("下一步:到 Obsidian 的 .drafts 審核 → 滿意的移到 wiki/ → 重新索引(sync wiki/)。")


if __name__ == "__main__":
    main()
