#!/usr/bin/env bash
# 改完 wiki/ 筆記後,跑這個把變動同步進 RAG 索引(只重嵌有改的那幾篇)。
# vault 路徑可用環境變數 ERP_VAULT 覆蓋。
set -euo pipefail
cd "$(dirname "$0")"
export ERP_VAULT="${ERP_VAULT:-/mnt/c/Users/Administrator/Desktop/erp-kb}"
echo "▶ 同步 $ERP_VAULT/wiki → RAG 索引..."
venv/bin/python -c "import os; from tools.rag_tools import sync_folder; print(sync_folder.invoke({'folder_path': os.environ['ERP_VAULT'] + '/wiki'}))"
