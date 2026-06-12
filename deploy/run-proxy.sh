#!/usr/bin/env bash
# 用 docker 跑 nginx 反向代理（免 sudo；需有 docker 權限）。把 erp(/) 與 cf(/dev) 併到同一埠。
#
# 用 --network host：容器內 nginx 直接連 127.0.0.1 上的 erp(3005/8000) 與 cf(8787/5180/dist)。
# 設定檔 deploy/nginx.conf 掛進官方 nginx 的 conf.d（已被包在 http{} 內，故 map/server 合法）。
# cf 靜態檔需先建：cd claude-frontend/web && CF_BASE=/dev/ npx vite build
#
# ⚠️ 安全：erp 未設 GOOGLE_CLIENT_ID 時是「免登入單人模式」。對外開放前務必先啟用登入，
#    否則任何人都能進。預設只聽 127.0.0.1（本機測試）；要對外請設 LISTEN=80 並自行確認防火牆。
set -euo pipefail
cd "$(dirname "$0")"

LISTEN="${LISTEN:-127.0.0.1:8090}"   # 預設只綁本機；對外改成 80（先確認已啟用登入）
NAME="${NAME:-erp-proxy}"
CONF="$(pwd)/nginx.conf"
DIST="/home/hermes/claude-frontend/web/dist"

[ -f "$CONF" ] || { echo "找不到 $CONF"; exit 1; }
[ -d "$DIST" ] || { echo "找不到 cf 靜態檔 $DIST，請先：cd claude-frontend/web && CF_BASE=/dev/ npx vite build"; exit 1; }

# 依 LISTEN 產生一份 conf（把 `listen 80;` 換成指定的綁定位址）。
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
sed "s/listen 80;/listen ${LISTEN};/" "$CONF" > "$TMP"

docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --network host --restart unless-stopped \
  -v "$TMP:/etc/nginx/conf.d/default.conf:ro" \
  -v "$DIST:$DIST:ro" \
  nginx:stable
echo "反向代理已啟動（$NAME），監聽 ${LISTEN}。"
echo "測試：curl -s http://${LISTEN}/ | head；停止：docker rm -f $NAME"
