# ERP Agent — ERP AI 助理

以 **LangChain + LangGraph** 打造的 ERP AI 助理。採 **supervisor 多 Agent 架構**:一個請求進來,由 supervisor 看完整對話歷史,決定把問題派給哪個專長 Agent(可串接多個),全部完成才結束。

> 換句話說:你用自然語言問問題,系統自動判斷該「查資料庫」「分析營運」「讀 PDF」「做簡報」還是「查知識庫」,並把對應的角色串起來回答你。

---

## 它現在能做什麼

目前內建 **9 個 Agent**(登記於 `graph/registry.py`,流程圖自動接線):

| Agent | 能力 | 資料/工具來源 |
|---|---|---|
| **sql** | 用自然語言查 ERP 資料庫的**具體數字**(人資:員工/部門/特休/請假;製造:客戶/訂單/產品/採購/生產工單/品檢/機台/庫存) | 唯讀 text-to-SQL + **SQL 範例庫語意檢索**(23 條已驗證 SQL)+ schema 檢索 |
| **analyst** | **決策分析師**:跨領域整合製造營運資料,算 KPI(營收毛利/準交/良率/品質/庫存/供應商/客戶集中度)、找趨勢與風險、給老闆可拍板的決策建議 | 與 sql 共用唯讀 SQL 工具,分工做整合分析 |
| **rag** | **知識庫問答(RAG)**:語意檢索已建檔文件並標來源回答 | 純 Python 餘弦 + OpenAI embedding,索引在 `rag_index/` |
| **ppt** | 依主題/大綱產出**可下載、可再編輯的 .pptx 簡報** | **ppt-agent**(獨立部署的可攜式 agent,python-pptx 引擎,經 **MCP** 接回;舊 Presenton 仍可 `USE_PRESENTON_PPT=true` 回滾)|
| **pdf** | 讀取 PDF/文件並做重點分析 | `pypdf` |
| **image** | **圖片轉文字(OCR)** | 多模態 LLM |
| **inventory** | 庫存品項/數量/儲位查詢 | 目前為示範用寫死資料(可換真資料庫) |
| **email** | 撰寫商務 email 草稿(擬主旨+內文,不寄出) | 純 LLM |
| **report** | 對貼上的數據做摘要、趨勢與洞察 | 純 LLM |

### 前端介面(Next.js 16 + React 19)
- **`/chat` — 多 Agent 對話頁**:ChatGPT 式串流介面。左側對話清單(存 localStorage,可新增/切換/刪除)、隨時終止、編輯任一則訊息並從該點重跑、Markdown 渲染、`/files` 連結自動變下載/開啟按鈕。
- **`/single` — 單一 Agent 頁**:無記憶的 one-shot,直接挑一個 Agent 用;ppt 附 template 選擇器。
- **`/admin` — 知識庫管理**:上傳文件、建立/同步 RAG 索引、查看統計。
- **`/` — 首頁**。

### 資料與後端
- **PostgreSQL 私有 cluster**(專案內 `./pgdata`,跑在 **5433**,唯讀 text-to-SQL 安全雙層防護):**18 張表 / ~5300 筆 / 18 個月時序**(4 張 HR + 14 張製造業),由 `db/seed.py`、`db/seed_mfg.py` 灌入(固定亂數種子、可重跑)。
- **FastAPI 後端**(8000):`/api/chat/stream`(NDJSON 串流)、`/api/agent`、`/api/agents`、`/api/ppt/templates`、`/api/rag/*`、`/files/*`(下載產出檔)。
- **PPT 引擎 ppt-agent**:獨立部署的**可攜式 agent**(`ppt-agent/`,python-pptx),對外只露出 **MCP** 契約(`make_presentation` / `make_proposal`);erp-agent 經 MCP 連它、不 import 其實作。產出寫到與 `/files` 共享的目錄即可下載。template:general/modern/standard/swift(對應引擎四套配色)。詳見 `CLAUDE.md` 的「可攜式 Agent」一節。

---

## 架構與設計原則

```
graph/      ← LangGraph 流程編排(supervisor 模式,由 registry 自動接線)
  └ agents/ ← 角色 = 提示詞 + 它能用的工具
      └ tools/ ← 動作(@tool 標記)
          └ base_agent.py ← get_llm() / create_agent(),所有 Agent 的根
```

單向依賴:`graph → agents → tools → base_agent`(不可反向)。三條核心原則:

1. **換模型只改一處** — LLM 只在 `agents/base_agent.py` 的 `get_llm()` 建立。
2. **記憶體分層** — 單獨用 Agent 自帶記憶;接進 graph 的子 Agent 一律 `with_memory=False`,記憶交給 graph 那層。
3. **registry 是唯一登記處** — 新增 Agent 只在 `graph/registry.py` 登記一筆,router 選項/提示詞/節點/路由邊全自動生成。

> 詳細開發規範(新增 Agent / 擴充 SQL 範例庫的 SOP)見 [`CLAUDE.md`](./CLAUDE.md)。

---

## 快速開始

### 1. 環境準備
```bash
python -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env   # 填入 OPENAI_API_KEY 等(見下方)
```

`.env` 主要設定:`OPENAI_API_KEY`、`DATABASE_URL=postgresql://erp@localhost:5433/erp`;PPT 相關(`PPT_AGENT_*`、回滾用的 `USE_PRESENTON_PPT`/`PRESENTON_*`)多由 `start.sh` 自動處理,見 `.env.example`。

### 2. 灌入示範資料(第一次)
```bash
venv/bin/python -m db.seed       # HR 4 張表
venv/bin/python -m db.seed_mfg   # 製造業 14 張表
```

### 3. 一鍵啟動
```bash
bash start.sh        # PostgreSQL(5433)+ 後端 API(8000)+ 前端(3005),冪等可重跑
```
打開 **http://localhost:3005**。停止:`bash stop.sh`(加 `--all` 連 Postgres 一起停)。

### 4. PPT 引擎 ppt-agent(預設啟用,獨立部署的 sibling 服務)
ppt-agent 是**和 erp-agent 平行的獨立服務**,預設在 `../agents/ppt-agent`(自帶 venv/Dockerfile/compose)。
erp-agent **只用 URL(MCP)連它,不 import**。`start.sh` 會自動帶起它:
- **有 Docker** → 用 ppt-agent **自己的** compose 起容器(sse,對外 8002);
- **無 Docker** → 退回 stdio(由 api 直接 spawn,需先建好其 venv:
  `cd ../agents/ppt-agent && python -m venv .venv && .venv/bin/pip install -e ".[mcp,rest]"`)。

產出寫到 erp-agent 的 `./generated`(= `/files`)即可下載,不需 Presenton。
> 換成別的位置:設 `PPT_AGENT_DIR`;連遠端既有服務:設 `PPT_AGENT_URL`。
> 回滾:`USE_PRESENTON_PPT=true` 切回舊 Presenton,並 `docker compose up -d presenton`。

### 驗證(不需 API Key)
```bash
venv/bin/python -c "
import os; os.environ.setdefault('OPENAI_API_KEY','sk-test-dummy')
from graph.erp_graph import erp_graph
from graph.registry import AGENTS
print('已登記 Agent:', list(AGENTS))
print('節點:', sorted(erp_graph.get_graph().nodes))
"
venv/bin/python sql_library/validate.py   # 範例庫每條 SQL 實跑驗證
```

---

## 開發進度

**已完成**
- [x] supervisor 多 Agent 流程,registry 自動接線(9 個 Agent)
- [x] 多 Agent 串流對話頁(對話管理 / 終止 / 編輯重跑)+ 單一 Agent 頁
- [x] 唯讀 text-to-SQL,擴成製造業 ERP(18 表),含安全雙層防護
- [x] **SQL 範例庫 + schema 雙語意檢索**(retrieval-augmented SQL,提升準確度)
- [x] analyst 決策分析 Agent(跨域 KPI 整合)
- [x] RAG 知識庫問答 + 後台管理 UI
- [x] PPT 改走**可攜式 ppt-agent**(python-pptx 引擎,獨立部署、經 MCP 接回;Presenton 留作回滾)
- [x] PDF 分析、OCR、email 草稿、報表分析、庫存查詢

**未來可做**
- [ ] **永久記憶**:`MemorySaver`(RAM,程式關掉就消失)換成 `SqliteSaver` / `PostgresSaver`
- [ ] **多資料庫支援**:在 `catalog.json` / `schema.json` 標 `db` 並加連線路由(先選 DB 再選表/SQL)
- [ ] **庫存接真資料庫**:`inventory_tools.py` 目前是示範用寫死字典
- [ ] 資料量再放大時,語意索引換成真正的向量資料庫(呼叫端介面不變)
- [ ] text-to-SQL 算 KPI 仍可能算錯,給老闆的數字建議用 sql agent 覆核
- [ ] supervisor 每輪多一次調度 LLM 呼叫;長流程要留意 `recursion_limit`

---

## 技術棧

LangChain 1.3 · LangGraph 1.2 · langchain-openai · langchain-mcp-adapters(MCP)· FastAPI · uvicorn · PostgreSQL(psycopg)· Next.js 16 · React 19 · Tailwind CSS 4 · react-markdown · python-pptx(ppt-agent)

所有面向使用者的輸出皆為**繁體中文**。
