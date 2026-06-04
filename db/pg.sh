#!/usr/bin/env bash
# 私有 PostgreSQL cluster 管理腳本（不需 sudo，資料持久化在專案內 ./pgdata）。
#
# 為什麼這樣設計：
#   這台機器沒有系統級 PostgreSQL service，也不能用 Docker。安裝 postgresql 套件
#   只需要一次 sudo；之後用 initdb 在專案目錄開一個「由本使用者擁有」的 cluster，
#   跑在非預設的 5433 port、用 trust 認證（純本機開發用），完全不需要再動 sudo。
#
# 用法：
#   bash db/pg.sh init     # 第一次：建立 cluster + erp 資料庫
#   bash db/pg.sh start    # 啟動
#   bash db/pg.sh stop     # 停止
#   bash db/pg.sh status   # 狀態
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGDATA="$PROJECT_DIR/pgdata"
PORT=5433
SOCKET_DIR=/tmp
DB_NAME=erp
DB_USER=erp

# 自動找到 initdb / pg_ctl / createdb（跨平台：Linux apt 與 macOS Homebrew 都不在 PATH）
PGBIN="$(ls -d /usr/lib/postgresql/*/bin 2>/dev/null | sort -V | tail -1 || true)"           # Linux (apt)
[ -z "$PGBIN" ] && PGBIN="$(ls -d /opt/homebrew/opt/postgresql@*/bin 2>/dev/null | sort -V | tail -1 || true)"  # macOS (Apple Silicon brew)
[ -z "$PGBIN" ] && PGBIN="$(ls -d /usr/local/opt/postgresql@*/bin 2>/dev/null | sort -V | tail -1 || true)"     # macOS (Intel brew)
[ -z "$PGBIN" ] && command -v initdb >/dev/null 2>&1 && PGBIN="$(dirname "$(command -v initdb)")"               # 已在 PATH
if [ -z "$PGBIN" ]; then
  echo "找不到 PostgreSQL binaries。請先安裝：" >&2
  echo "  Linux: sudo apt-get install -y postgresql postgresql-contrib" >&2
  echo "  macOS: brew install postgresql@16" >&2
  exit 1
fi

case "${1:-}" in
  init)
    if [ -d "$PGDATA" ]; then
      echo "pgdata 已存在，略過 initdb。如要重來請先刪除 $PGDATA"
    else
      "$PGBIN/initdb" -D "$PGDATA" -U "$DB_USER" --auth=trust \
        --encoding=UTF8 --locale=C >/dev/null
      echo "已建立 cluster（superuser=$DB_USER）"
    fi
    "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" \
      -o "-p $PORT -k $SOCKET_DIR -c listen_addresses=localhost" -w start
    if ! "$PGBIN/psql" -h localhost -p "$PORT" -U "$DB_USER" -d postgres \
          -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
      "$PGBIN/createdb" -h localhost -p "$PORT" -U "$DB_USER" "$DB_NAME"
      echo "已建立資料庫 $DB_NAME"
    fi
    echo "就緒：postgresql://$DB_USER@localhost:$PORT/$DB_NAME"
    ;;
  start)
    "$PGBIN/pg_ctl" -D "$PGDATA" -l "$PGDATA/server.log" \
      -o "-p $PORT -k $SOCKET_DIR -c listen_addresses=localhost" -w start
    ;;
  stop)
    "$PGBIN/pg_ctl" -D "$PGDATA" -w stop
    ;;
  status)
    "$PGBIN/pg_ctl" -D "$PGDATA" status || true
    "$PGBIN/pg_isready" -h localhost -p "$PORT" || true
    ;;
  *)
    echo "用法: bash db/pg.sh {init|start|stop|status}" >&2
    exit 1
    ;;
esac
