#!/usr/bin/env bash
# 一鍵啟動 erp-agent 的本機服務：PostgreSQL + 後端 API(8000) + 前端(3005)。
#
# 選用：設 RAG_WATCH_DIR=/你的文件資料夾  會一併啟動 RAG 自動監看（每天掃一次）。
#   例：RAG_WATCH_DIR=~/company_docs bash start.sh
#
# 注意：
# - 已在跑的服務會自動略過，不會重開（可重複執行）。
# - 不會重新灌資料（DB cluster 持久化，資料都在）。要重灌：venv/bin/python -m db.seed / db.seed_mfg
# - Presenton 跑在你的 Docker（localhost:5000），不由此腳本管理，請自行 docker run。
cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"

running() { ss -ltn 2>/dev/null | grep -qE ":$1(\s|$)"; }

echo "▶ 啟動 erp-agent 服務…"

# 1) PostgreSQL（私有 cluster，5433）
if running 5433; then
  echo "  ✓ PostgreSQL 已在跑 (5433)"
else
  if [ -d pgdata ]; then bash db/pg.sh start; else bash db/pg.sh init; fi
fi

# 2) 後端 API（8000）
if running 8000; then
  echo "  ✓ 後端 API 已在跑 (8000)"
else
  nohup venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000 > "$ROOT/api.log" 2>&1 &
  echo "  ✓ 後端 API 啟動中 (8000) → api.log"
fi

# 3) 前端（3005，production build）
if running 3005; then
  echo "  ✓ 前端已在跑 (3005)"
else
  if [ ! -d frontend/.next ]; then
    echo "  · 第一次啟動，先 build 前端（稍等）…"
    ( cd frontend && npm run build > "$ROOT/frontend-build.log" 2>&1 )
  fi
  ( cd frontend && nohup node_modules/.bin/next start -p 3005 > "$ROOT/frontend.log" 2>&1 & )
  echo "  ✓ 前端啟動中 (3005) → frontend.log"
fi

# 4) RAG 自動監看（選用，需設 RAG_WATCH_DIR）
if [ -n "${RAG_WATCH_DIR:-}" ]; then
  if pgrep -f "watch_rag.py" >/dev/null; then
    echo "  ✓ RAG watcher 已在跑"
  else
    nohup venv/bin/python watch_rag.py "$RAG_WATCH_DIR" > "$ROOT/rag-watch.log" 2>&1 &
    echo "  ✓ RAG watcher 監看 $RAG_WATCH_DIR → rag-watch.log"
  fi
fi

echo ""
echo "✅ 完成。前端 http://localhost:3005　｜　API http://localhost:8000"
echo "   停止全部：bash stop.sh"
