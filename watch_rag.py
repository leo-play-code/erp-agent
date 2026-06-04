"""自動監看資料夾 —— 檔案一有變動就增量更新 RAG 知識庫索引。

用法（在 erp-agent 根目錄）：
    venv/bin/python watch_rag.py <資料夾路徑> [<資料夾2> ...]
    # 想在背景常駐：  nohup venv/bin/python watch_rag.py ~/company_docs > rag-watch.log 2>&1 &
    # 檢查間隔（秒）可用環境變數 RAG_WATCH_INTERVAL 調整（預設 86400 = 24 小時，每天掃一次）。
    #   想更即時可調小：RAG_WATCH_INTERVAL=300 …（每 5 分鐘）。

原理：每隔幾秒呼叫 sync_folder 做「增量同步」——靠檔案內容雜湊比對，
只重新建索引「有變動的單一檔」，沒變的略過、刪掉的移除，所以反覆掃也很省。
新增檔、改檔、刪檔都會在數秒內自動反映到知識庫。按 Ctrl-C 結束。
"""

import os
import sys
import time
from pathlib import Path

from tools.rag_tools import sync_folder

INTERVAL = max(3, int(os.getenv("RAG_WATCH_INTERVAL", "86400")))  # 預設每 24 小時掃一次


def _every() -> str:
    """把間隔秒數轉成好讀的文字。"""
    if INTERVAL % 86400 == 0:
        return f"每 {INTERVAL // 86400} 天"
    if INTERVAL % 3600 == 0:
        return f"每 {INTERVAL // 3600} 小時"
    if INTERVAL % 60 == 0:
        return f"每 {INTERVAL // 60} 分鐘"
    return f"每 {INTERVAL} 秒"


def main(folders: list[str]) -> None:
    folders = [str(Path(f).expanduser()) for f in folders]
    print(f"[rag-watch] 開始監看 {len(folders)} 個資料夾，{_every()}檢查一次（Ctrl-C 結束）：",
          flush=True)
    for f in folders:
        print(f"  - {f}", flush=True)
    while True:
        for f in folders:
            try:
                msg = sync_folder.invoke({"folder_path": f})
            except Exception as e:  # noqa: BLE001 單次失敗不該讓監看整個掛掉
                print(f"[rag-watch] {time.strftime('%H:%M:%S')} 同步 {f} 失敗：{e}", flush=True)
                continue
            if "無變動" not in msg:  # 只在真的有變動時才印，平常安靜
                print(f"[rag-watch] {time.strftime('%H:%M:%S')} {msg}", flush=True)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法：venv/bin/python watch_rag.py <資料夾路徑> [更多資料夾...]")
        sys.exit(1)
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n[rag-watch] 已停止監看。")
