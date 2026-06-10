#!/usr/bin/env bash
# 加新文件流程:把新檔放進 vault 的 raw/ 後,跑這個自動編譯成草稿,再人工審核移到 wiki/。
# vault 路徑可用環境變數 ERP_VAULT 覆蓋。
set -euo pipefail
cd "$(dirname "$0")"
export ERP_VAULT="${ERP_VAULT:-/mnt/c/Users/Administrator/Desktop/erp-kb}"

echo "▶ 編譯 raw/ 中「新增/變動」的文件成草稿(花 LLM,約數十秒)..."
venv/bin/python compile_wiki.py "$ERP_VAULT"

echo
echo "✅ 草稿已產生在:$ERP_VAULT/.drafts"
echo "接下來(人工把關):"
echo "  1. 在 Obsidian 打開 .drafts 資料夾,逐篇審核(尤其 ⚠ 標註處)"
echo "  2. 確認無誤的筆記,從 .drafts 移到 wiki/"
echo "  3. 執行  ./sync.sh  重新索引,新知識即生效"
