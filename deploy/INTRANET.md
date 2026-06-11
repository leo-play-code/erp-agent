# 內網自架版部署說明

把整套(erp + 可選的開發者 Agent)架在**公司內網**,用**帳號密碼登入**(不需 Google、不需外網)。
同一套程式也能跑雲端 SaaS——差別只在環境變數與 DB 位置。

## 架構與會用到的服務
```
公司內網單一入口(反向代理) ─┬─ /        erp 前端 (Next, 正式 build)
                              ├─ /api     erp 後端 (FastAPI)
                              └─ /dev     開發者 Agent (claude-frontend，選用)
                  資料：Postgres（內網自架 或 雲端皆可，用 DATABASE_URL 指定）
```

## 前置需求
- **Postgres 14+**;要用 RAG 知識庫(向量+Obsidian 關聯)則需 **pgvector** 擴充(`CREATE EXTENSION vector;`)。
- **Node.js ≥ 20.9**(前端)、**Python venv**(後端,`pip install -r requirements.txt`)。
- 反向代理:用 `deploy/run-proxy.sh`(docker 版 nginx,免 sudo)或自行裝 nginx 套 `deploy/nginx.conf`。
- 開發者 Agent(選用):需 docker + 已 build 的 `cf-agent` image(`claude-frontend/server/docker/build.sh`)。

> ⚠️ **LLM 需求**:AI agent 要呼叫 LLM。預設 OpenAI **需對外網**。完全斷網的內網請改本地模型——
> 只改 `agents/base_agent.py` 的 `get_llm()` 一處(指向內網的 vLLM/Ollama 等 OpenAI 相容端點)。

## .env(內網關鍵設定)
```bash
# 登入：只開帳密(不需 Google/外網)。要接公司 AD 改 local,ldap;接公司信箱改 local,imap
AUTH_MODES=local
APP_JWT_SECRET=<一串夠長的隨機字串>          # 簽 session JWT；開發者 Agent SSO 也用同一把

# 資料庫：內網自架 或 雲端，二擇一
DATABASE_URL=postgresql://user:pass@內網DB:5432/erp_agent
# CHECKPOINT_DATABASE_URL 不設則沿用上面；RAG 要存 DB 則：
# KB_BACKEND=postgres

# LLM：對外網用 OpenAI；或指向內網相容端點
OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=http://內網-llm:8000/v1   # 走本地模型時(視 base_agent 實作)
```

## 啟動步驟
```bash
# 1) DB：建擴充(用 KB 才需)、建控制面表、開一間公司
psql "$DATABASE_URL" -c "CREATE EXTENSION IF NOT EXISTS vector;"      # 選用(KB)
cd erp-agent
venv/bin/python -m db.control_plane
venv/bin/python -m db.provision --slug 你的公司代號 --name "你的公司" --admin admin@公司網域 --quota 5

# 2) 後端 API
venv/bin/uvicorn api.server:app --host 0.0.0.0 --port 8000

# 3) 前端(正式 build，比 dev 快很多)
cd frontend
BACKEND_ORIGIN=http://127.0.0.1:8000 npx next build
BACKEND_ORIGIN=http://127.0.0.1:8000 npx next start -p 3050

# 4) 反向代理(把上面併到單一入口；先確認 nginx.conf 內 erp 前端埠＝3050)
cd ../deploy && LISTEN=80 ./run-proxy.sh

# 5)(選用)開發者 Agent
cd ../../claude-frontend && CF_BASE=/dev/ npx vite build && bash start.sh
```

## 建帳號 / 登入
1. 用 `--admin` 指定的 email 第一次登入後,自動成為 **company_admin**(local 模式下,管理員需先有密碼——
   可在 DB 直接設,或讓 admin 走一次「忘記密碼」流程;最簡單:provision 後用下面指令給 admin 設密碼)。
   ```bash
   venv/bin/python -c "from db import control_plane as c; c.create_employee('org_公司網域','admin@公司網域','管理員','初始密碼','company_admin')"
   ```
2. 管理員登入 → 「員工管理」分頁 → **新增員工**(填密碼＝帳密登入;留空＝走公司信箱/AD)。
3. 在「員工管理」把 3–5 人開「開發者 Agent」席次。

## 切換登入方式(每間公司獨立)
- **帳密(預設)**:`AUTH_MODES=local`,管理員建帳號填密碼。
- **公司信箱(IMAP)**:`AUTH_MODES=local,imap`,管理員設定:
  ```bash
  venv/bin/python -c "from db import control_plane as c; c.set_company_auth('org_公司網域','imap',{'host':'mail.公司.com','port':993,'ssl':True})"
  ```
  再建員工(不填密碼),員工用**公司信箱帳密**登入。
- **AD/LDAP**:`AUTH_MODES=local,ldap`,`set_company_auth(..., 'ldap', {'url':'ldap://dc.公司.com:389','user_template':'{email}'})`。

## 正式環境建議
- 用 `systemd` 或 `pm2` 顧著 uvicorn / next start / cloudflared,開機自動起、掛掉自動拉。
- 對外請上 TLS(反向代理層接憑證);`APP_JWT_SECRET` 用強隨機值並妥善保存。
- 雲端 SaaS 版:把 `DATABASE_URL` 指雲端 DB、`AUTH_MODES` 視需要加 `google`,其餘相同。
