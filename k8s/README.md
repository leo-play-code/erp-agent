# 單機 k3s 部署 runbook

把 erp-agent 全棧（前端 + API + Postgres）與外部化的 ppt-agent 跑在單機 **k3s** 上。
manifest 以 Kustomize `base/` + `overlays/dev/` 管理，標清楚轉雲端要改的幾格（見白皮書 §21）。

> **分工**：image build 由開發機 docker 完成（免 sudo）；**裝 k3s、匯 image、apply、seed 需要 sudo**，
> 下列標 `sudo` 的步驟請你自己跑（在這個 session 用 `! <指令>` 也行）。

## 架構（叢集內）
```
Ingress(Traefik) → frontend(:3000) ──同源代理 /api,/files──> erp-api(:8000)
                                                              ├─ MCP/sse ─> ppt-agent(:8000)  [HPA 1..4]
                                                              └─ SQL ─────> postgres(:5432)
ppt-agent 寫 .pptx → outputs PVC ← erp-api 的 /files 讀同一份
```
erp-api 永遠連 **Service 名固定入口**（`http://ppt-agent:8000/sse`、`postgres:5432`）；Pod 擴縮不改設定。

---

## 步驟

### 0.（開發機，免 sudo）build 三個 image
```bash
docker build -t erp-api:0.1.0 -f Dockerfile .
docker build -t erp-frontend:0.1.0 -f frontend/Dockerfile frontend
docker build -t ppt-workflow:0.1.0 ../agents/ppt-workflow
docker images | grep 0.1.0          # 應看到三個
```

### 1. 裝 k3s（sudo）
```bash
curl -sfL https://get.k3s.io | sh -          # 裝好即自帶 Traefik/local-path/metrics-server/CoreDNS
sudo k3s kubectl get nodes                    # Ready 即成功
# 讓 kubectl 免 sudo（把 kubeconfig 複製給自己）
mkdir -p ~/.kube && sudo cp /etc/rancher/k3s/k3s.yaml ~/.kube/config \
  && sudo chown "$(id -u):$(id -g)" ~/.kube/config
kubectl get nodes
```

### 2. 匯入 image 到 k3s（sudo；k3s 不看 docker 的 image）
```bash
bash k8s/import-images.sh
sudo k3s ctr images ls | grep 0.1.0           # 應看到三個 docker.io/library/*:0.1.0
```

### 3. namespace + 真金鑰 Secret（sudo 視 kubeconfig 而定）
```bash
kubectl apply -f k8s/base/namespace.yaml
kubectl -n agents create secret generic agent-secrets \
  --from-literal=OPENAI_API_KEY="$(grep -E '^OPENAI_API_KEY=' .env | cut -d= -f2-)"
```

### 4. 部署全棧
```bash
kubectl apply -k k8s/overlays/dev
kubectl -n agents get pods -w                 # 等到 postgres/ppt-agent/erp-api/frontend 都 Running+Ready
```
> erp-api 有 initContainer 會等 postgres 與 ppt-agent 就緒才啟動，第一次起會慢一點，正常。

### 5. 灌示範資料（seed Job，已隨 apply 建立）
```bash
kubectl -n agents logs job/db-seed            # 看到 seed 完成；要重跑：
# kubectl -n agents delete job db-seed && kubectl apply -k k8s/overlays/dev
```

### 6. 開來看
```bash
# k3s 的 Traefik 預設在節點 :80。用節點 IP 或 localhost 開：
curl -s http://localhost/ | head             # 前端首頁
# 或查 ingress 位址：
kubectl -n agents get ingress
```

---

## 驗收（對應白皮書 §22）
```bash
# 固定入口 + 自動分流：擴 ppt-agent，erp-api 的 PPT_AGENT_URL 不變仍正常
kubectl -n agents scale deploy/ppt-agent --replicas=3
kubectl -n agents get endpoints ppt-agent     # 應看到 3 個 endpoint IP
# readiness：新 Pod 就緒前不被分流量（觀察沒有 5xx）
kubectl -n agents get pods -l app=ppt-agent
# 產物可下載：前端 /single 選 ppt 產出 → /files/<uuid>.pptx 可下載
# 資源生效：
kubectl -n agents top pods                    # 受 limits 約束
```

## 回滾 / 排錯
- ppt 出問題：`USE_PRESENTON_PPT=true`（改 configmap 後 `kubectl rollout restart deploy/erp-api`）切回舊路徑。
- 版本回滾：`kubectl -n agents rollout undo deploy/<name>`。
- 改 image 後要重匯：重跑步驟 2，再 `kubectl -n agents rollout restart deploy/<name>`
  （`imagePullPolicy: Never`，k3s 只用已匯入的本地 image）。
- 看事件：`kubectl -n agents describe pod <pod>` / `kubectl -n agents logs <pod>`。

## 轉雲端 k8s 要改的幾格（base 不動，改 overlay）
- `outputs-pvc` 的 `storageClassName` → 雲端 SC；多節點改 **RWX**（NFS/EFS）或改 **MinIO** 交付產物（§21.4）。
- `ingress` 的 `ingressClassName`/annotations → nginx 或雲端 LB。
- 控制面多節點 HA：k3s 換 etcd（`--cluster-init`）。
- I/O 型冷門 agent 要 scale-to-zero：裝 KEDA、加 `ScaledObject`（同一 Deployment 別同時掛原生 HPA）。

---

## 常用指令小抄

> 前提：k3s 的 kubectl 預設讀 root-only 的 `/etc/rancher/k3s/k3s.yaml`，**先讓它讀你的 kubeconfig**：
> ```bash
> export KUBECONFIG=$HOME/.kube/config     # 每個新 shell 都要，或寫進 ~/.bashrc
> ```
> 全部資源都在 `agents` namespace（下面指令已帶 `-n agents`）。

### 看狀態
```bash
kubectl -n agents get pods -o wide              # 各 Pod 狀態/在哪個節點
kubectl -n agents get deploy,sts,svc,hpa,ingress,pvc   # 一覽
kubectl -n agents get endpoints ppt-agent       # ppt-agent 後面幾個 replica（擴縮驗證）
kubectl -n agents top pods                       # 實際 CPU/記憶體用量（受 limits 約束）
kubectl -n agents logs -f deploy/erp-api         # 跟 api log（ppt 失敗、500 看這裡）
kubectl -n agents logs -f deploy/ppt-agent       # 跟 ppt-agent log
kubectl -n agents describe pod <pod>             # 卡住/重啟看 Events
kubectl -n agents get hpa ppt-agent              # HPA 現在想要幾個 replica
```

### 重新部署 / 改設定
```bash
kubectl apply -k k8s/overlays/dev                # 套用 manifest 變更（改 yaml 後）
kubectl -n agents rollout restart deploy/erp-api # 重啟（清 MCP client 卡死、重讀 configmap）
kubectl -n agents rollout status deploy/erp-api  # 等就緒
# 改了 configmap（如 USE_PRESENTON_PPT）要重啟才生效：
kubectl -n agents rollout restart deploy/erp-api
```

### 改 image 後重來（imagePullPolicy: Never，k3s 只認已匯入的本地 image）
```bash
docker build -t erp-api:0.1.0 -f Dockerfile .          # 1) 重 build（或前端/ppt-workflow）
bash k8s/import-images.sh                                # 2) 重匯進 k3s（sudo）
kubectl -n agents rollout restart deploy/erp-api         # 3) 重啟用新 image
```
> 同 tag 重匯後一定要 `rollout restart`，否則 Pod 還跑舊的（image 沒換 digest 不會自動更新）。

### 手動擴縮 / 重跑 seed
```bash
kubectl -n agents scale deploy/ppt-agent --replicas=3    # 手動擴（HPA 之後可能再調整）
kubectl -n agents delete job db-seed && kubectl apply -k k8s/overlays/dev   # 重灌示範資料
```

### 停 / 起 / 砍掉
```bash
# 停掉 workload（保留 k3s 本身與資料 PVC）：
kubectl -n agents scale deploy --all --replicas=0
kubectl -n agents scale sts/postgres --replicas=0
# 重新起：
kubectl -n agents scale sts/postgres --replicas=1 && kubectl -n agents scale deploy --all --replicas=1

# 整包砍掉 workload（保留 namespace 與 PVC 資料）：
kubectl delete -k k8s/overlays/dev
# 連資料一起砍（pgdata/outputs 也清）：
kubectl delete namespace agents

# 連 k3s 一起移除（最徹底，需 sudo）：
sudo /usr/local/bin/k3s-uninstall.sh
```

### 回滾
```bash
kubectl -n agents rollout undo deploy/<name>             # 回前一版
# ppt 出狀況臨時切回 Presenton：改 configmap USE_PRESENTON_PPT=true 後 rollout restart erp-api，
# 並起 Presenton（見專案根 docker-compose.yml）。
```
