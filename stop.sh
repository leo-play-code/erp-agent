#!/usr/bin/env bash
# 停止 start.sh 啟動的本機服務（PostgreSQL 預設保留，加 --all 才一起停）。
cd "$(dirname "$0")" || exit 1
echo "■ 停止 erp-agent 服務…"

pkill -f "erp-agent/frontend/node_modules/.bin/next" 2>/dev/null && echo "  ✓ 前端已停" || echo "  · 前端未在跑"
pkill -f "uvicorn api.server:app" 2>/dev/null && echo "  ✓ 後端 API 已停" || echo "  · 後端未在跑"
pkill -f "watch_rag.py" 2>/dev/null && echo "  ✓ RAG watcher 已停" || echo "  · watcher 未在跑"

if [ "${1:-}" = "--all" ]; then
  bash db/pg.sh stop 2>/dev/null && echo "  ✓ PostgreSQL 已停" || echo "  · PostgreSQL 未在跑"
else
  echo "  · PostgreSQL 保留運轉（要一起停：bash stop.sh --all）"
fi
echo "（Presenton 在 Docker，請自行 docker stop presenton）"
