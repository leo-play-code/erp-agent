#!/usr/bin/env bash
# 把本地 docker image 匯進 k3s 的 containerd（k3s 不看 docker daemon 的 image）。
# 需要 sudo（k3s ctr）。執行前先確認三個 image 都在：
#   docker images | grep 0.1.0
set -euo pipefail
for img in erp-api:0.1.0 erp-frontend:0.1.0 ppt-workflow:0.1.0; do
  echo "→ importing $img into k3s containerd"
  docker save "$img" | sudo k3s ctr images import -
done
echo "✓ done. 驗證：sudo k3s ctr images ls | grep 0.1.0"
