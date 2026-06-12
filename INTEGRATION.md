# erp-agent ⊕ claude-frontend 整合（商品版）

把 **erp-agent**（公司用多 agent ERP 助理）與 **claude-frontend**（每使用者一個 docker 的
coding agent）整合成一套可賣給企業的產品。claude-frontend 變成 erp 裡一個**受權限控管的
「開發者 Agent」分頁**，每公司限 3–5 名指定開發者使用。

## 架構
```
單一網域（nginx，deploy/nginx.conf）
  /            → erp Next.js  :3005     （外殼）
  /api,/files  → erp FastAPI :8000
  /dev/        → cf web 靜態檔（vite build，base=/dev/）  ← iframe 內容（開發者 Agent）
  /dev/api,/dev/ws,/dev/status → cf Fastify :8787
```
- **身分**：erp 是唯一 SSO。erp 發 HS256 JWT（含 `role`/`developer` claim）；開發者分頁把
  JWT POST 到 `/dev/api/auth/erp-sso`，cf 用**同一把 `APP_JWT_SECRET`** 驗證後種 `cf_session`
  cookie（Path=/dev，同站台），iframe 內含 WebSocket 一律自動帶 cookie。cf 的容器以
  `sha256('erp:'+sub)` 命名，故同一員工每次登入對到同一個 `cf-user-<id8>` 容器。
- **資料隔離**：同一 Postgres，每公司一個 schema（`tenant_<key>`）放業務表；`public` 放控制面
  （`companies`/`app_users`）+ 站內信箱 + 對話 checkpoint。SQL agent 查詢時每次借連線都
  `SET search_path`（`tools/sql_tools.py`），只看得到自己公司的表。
- **權限**：`company_admin`（管人、發/收開發者席次）、`employee`、`developer`（旗標，上限可設）。
- **開發者切換**：在對話中說「啟動開發者 agent」→ supervisor 路由 `DEV_AGENT` → API 檢查席次後
  串流 `{"type":"action","action":"open_dev_agent"}` → 前端切到 `/dev-agent` 分頁。
- **站內信箱**：員工間訊息 + 系統通知（如產出檔案完成）+ 管理員公告。

## 啟用 SSO / auth（必要）
1. `erp-agent/.env`：設 `GOOGLE_CLIENT_ID`（啟用登入與多租戶）與 `APP_JWT_SECRET`（已產生強密鑰）。
2. cf 端會自動從 `erp-agent/.env` 取 `APP_JWT_SECRET`（見 `claude-frontend/start.sh`），並開
   `CF_ERP_SSO=1`、`CF_COOKIE_PATH=/dev`。兩邊密鑰務必一致。

## 一次性遷移（既有單一 public 資料 → 每公司 schema）
```bash
cd erp-agent
pg_dump ...                                   # 先備份
bash db/pg.sh start
venv/bin/python -m db.control_plane           # 建控制面 + 信箱表
venv/bin/python -m db.migrate_to_schemas --tenant org_<你的網域> --name "你的公司"
```

## 開一間新公司（可重複）
```bash
venv/bin/python -m db.provision --slug acme.com --name "Acme" --admin admin@acme.com --quota 5 [--demo]
```
管理員 email 首次用 Google 登入時自動取得 `company_admin`，再到「員工管理」分頁授予開發者席次。

## 本機跑起來
```bash
# 1) erp
cd erp-agent && bash db/pg.sh start && bash start.sh        # :8000 / :3005
# 2) cf（自動讀 erp 的 APP_JWT_SECRET）
cd claude-frontend && bash start.sh                          # :8787 / :5180
# 3) 反向代理（部署）：先建 cf 前端靜態檔，再套 nginx
cd claude-frontend/web && CF_BASE=/dev/ npx vite build
sudo cp erp-agent/deploy/nginx.conf /etc/nginx/conf.d/erp.conf && sudo nginx -t && sudo nginx -s reload
```

## 驗證重點
- 同一帳號登入兩次 → 重用同一 `cf-user-<id8>` 容器。
- developer 員工在對話打「啟動開發者 agent」→ 自動切到 `/dev-agent`，iframe 內可開對話跑 coding；
  無席次 → 收到拒絕訊息且 Nav 無此分頁。
- provision 第二間公司 → SQL agent 只查得到自己 schema 的表。
- 站內信：A 寄給 B、B 收得到並可標已讀；管理員公告 fan-out 全公司；產出檔案後出現通知。
