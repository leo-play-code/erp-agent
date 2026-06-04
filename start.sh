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

# 後端 API / 前端 port，可用環境變數覆蓋（預設 8000 / 3005）。
# 例（Mac 上 port 被別的專案佔用時）：API_PORT=8001 FRONTEND_PORT=3006 bash start.sh
API_PORT="${API_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3005}"

# 偵測某 port 有沒有在 listen（跨平台:macOS 用 lsof,Linux 退回 ss）
running() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
  else
    ss -ltn 2>/dev/null | grep -qE ":$1(\s|$)"
  fi
}

echo "▶ 啟動 erp-agent 服務…"

# 1) PostgreSQL（私有 cluster，5433）
if running 5433; then
  echo "  ✓ PostgreSQL 已在跑 (5433)"
else
  if [ -d pgdata ]; then bash db/pg.sh start; else bash db/pg.sh init; fi
fi

# 2) 後端 API（$API_PORT）
if running "$API_PORT"; then
  echo "  ✓ 後端 API 已在跑 ($API_PORT)"
else
  nohup venv/bin/uvicorn api.server:app --host 0.0.0.0 --port "$API_PORT" > "$ROOT/api.log" 2>&1 &
  echo "  ✓ 後端 API 啟動中 ($API_PORT) → api.log"
fi

# 3) 前端（$FRONTEND_PORT，production build）
if running "$FRONTEND_PORT"; then
  echo "  ✓ 前端已在跑 ($FRONTEND_PORT)"
else
  if [ ! -d frontend/.next ]; then
    echo "  · 第一次啟動，先 build 前端（稍等）…"
    ( cd frontend && npm run build > "$ROOT/frontend-build.log" 2>&1 )
  fi
  ( cd frontend && BACKEND_ORIGIN="http://127.0.0.1:$API_PORT" nohup node_modules/.bin/next start -p "$FRONTEND_PORT" > "$ROOT/frontend.log" 2>&1 & )
  echo "  ✓ 前端啟動中 ($FRONTEND_PORT) → frontend.log"
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
echo "✅ 完成。前端 http://localhost:${FRONTEND_PORT}　｜　API http://localhost:${API_PORT}"
echo "   停止全部：bash stop.sh"
