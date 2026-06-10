# ERP Agent — 專案開發規範

ERP AI 助理,基於 **LangChain + LangGraph**。本檔是這個專案的開發準則。
**之後新增任何 Agent、Tool 或相關功能,都必須依照本檔的規範。**

---

## 目錄結構與各層職責

```
erp-agent/
├── agents/              ← Agent（角色 + 提示詞 + 它能用的工具）
│   ├── base_agent.py    ← 共用框架：get_llm() 與 create_agent()，所有 Agent 的根
│   ├── pdf_agent.py     ← PDF 分析 Agent
│   └── inventory_agent.py ← 庫存查詢 Agent
├── tools/               ← Tool（Agent 實際執行的動作，用 @tool 標記）
│   ├── pdf_tools.py
│   ├── inventory_tools.py
│   ├── sql_tools.py        ← describe_schema + run_sql_query（唯讀執行）
│   ├── sql_library.py      ← find_sql：SQL 範例庫語意檢索
│   ├── sql_schema.py       ← find_tables + SCHEMA_OVERVIEW（schema 單一來源渲染/檢索）
│   └── _semantic_index.py  ← 共用語意索引（embedding/餘弦/快取，非 tool）
├── sql_library/         ← SQL 範例庫與 schema（資料，非程式）
│   ├── catalog.json        ← 問題→已驗證 SQL 清單（加 SQL 改這裡）
│   ├── schema.json         ← 資料表結構單一來源（加資料表改這裡）
│   ├── validate.py         ← 驗證每條範例 SQL 跑得通
│   └── *_index.json        ← embedding 快取（自動生成、不進版控）
├── graph/               ← LangGraph 流程編排
│   ├── registry.py      ← ★ Agent 註冊表：新增 Agent 的唯一登記處
│   └── erp_graph.py     ← 主流程，完全由 registry 自動接線
├── .env                 ← LLM 設定（API Key 等），不進版控
└── requirements.txt     ← 版本已鎖定
```

**分層原則**:Tool 是「動作」,Agent 是「會用某些動作的角色」,graph 是「決定把問題交給哪個角色」。三者單向依賴:`graph → agents → tools → base_agent`。不可反向 import。

---

## 三條核心原則(不可違反)

1. **換模型只改一處** — LLM 只在 `agents/base_agent.py` 的 `get_llm()` 建立。
   任何地方要用 LLM,一律 `from agents.base_agent import get_llm`,**不要**自己
   `ChatOpenAI(...)`。要換本地模型 / 換 provider / 改參數,只動 `get_llm()`。

2. **記憶體分兩種場景**(詳見下方「記憶體規則」) — 單獨用 Agent 帶記憶;
   接進 graph 的子 Agent **一律 `with_memory=False`**,記憶交給 graph 那層。

3. **registry 是唯一登記處** — 接進主流程的 Agent,一律在 `graph/registry.py`
   的 `AGENTS` 登記。**不要**在 `erp_graph.py` 寫死任何 Agent 名稱。

---

## SOP:新增一個 Agent

照這四步,缺一不可:

**① 寫 Tool** → `tools/<名稱>_tools.py`
```python
from langchain_core.tools import tool

@tool
def my_action(arg: str) -> str:
    """一句話說明這個工具做什麼（繁中）。LLM 靠這段 docstring 決定何時呼叫。

    Args:
        arg: 參數說明。
    """
    ...
    return "結果字串"
```

**② 寫 Agent** → `agents/<名稱>_agent.py`
```python
from agents.base_agent import create_agent
from tools.my_tools import my_action

SYSTEM_PROMPT = """你是 ...（角色）。
當 ... 時，使用 my_action 工具，並以繁體中文回覆。"""

TOOLS = [my_action]

def build_my_agent(with_memory=True):
    return create_agent(TOOLS, SYSTEM_PROMPT, with_memory=with_memory)

my_agent = build_my_agent()  # 單獨使用、自帶記憶的標準實例
```

**③ 登記到 registry** → `graph/registry.py` 的 `AGENTS` 加一筆
```python
"my": {
    "desc": "這個 Agent 負責什麼（給 router 判斷用，寫清楚）",
    "build": build_my_agent,
    "accepts_file": False,  # 這個 Agent 會不會用到上傳檔案；前端據此決定是否顯示上傳欄
},
```

**④ 驗證** → 跑下方「驗證指令」,確認節點與路由自動接好。

> graph 的 router 選項、提示詞、節點、路由邊都會從 registry **自動生成**,
> 所以 `erp_graph.py` 不需要改。這就是「依賴一處」的設計。

---

## SOP:擴充 SQL 查詢能力(範例庫 + schema 檢索)

`sql` agent 不把整個資料庫塞進 prompt,而是**先檢索**:`find_sql` 找相近的已驗證 SQL、
`find_tables` 找相關的資料表。要它變強,**改資料檔即可,不動 agent / 程式**。

**加一條常用查詢** → 編輯 `sql_library/catalog.json`,在 `queries` 加一筆:
```json
{ "id": "簡短英文代號", "domain": "hr 或 mfg",
  "question": "使用者會怎麼問（可多種說法，逗號分隔）",
  "note": "查詢邏輯 / 該注意的欄位真實值（如狀態『已核准』）",
  "sql": "一條完整 SELECT，不加分號" }
```

**加一張資料表**(換真資料庫、擴 schema 時)→ 編輯 `sql_library/schema.json`,在 `tables`
加一筆 `name/domain/group/desc/schema`;`schema` 字串用 `→` 標外鍵、括號標中文欄義與
**合法值(enum)**。`find_tables`、`SCHEMA_OVERVIEW`、analyst 都會自動吃到。

**驗證(必做)**:
```bash
venv/bin/python sql_library/validate.py   # catalog 每條 SQL 實跑，全綠才算數
```
索引(`*_index.json`)會在下次查詢時依內容雜湊**自動重建**,不必手動處理。

**原則**:範例與 schema 的欄位值一律用**資料庫真實值**(別讓 LLM 猜,例如 `已核准`≠`已批准`);
範例**品質 > 數量**,重疊的範例會拉低檢索準確度;每條新 SQL 先 `validate` 過再進版控。

---

## 可攜式 Agent(MCP 接入) —— 當 agent 該獨立部署時

一般 agent 照前面 SOP(tools + agents + registry)寫,跑在同一個行程。**但當某個能力需要
獨立部署、被外部重用、或相依很重/想隔離**時,把它做成「可攜式 agent」:一個**獨立的服務**,
對外只露出 **MCP 契約**,erp-agent 經 MCP 連它,**不 import 它的任何實作**。

**位置慣例(重要)**:可攜式 agent 是**和 erp-agent 平行(sibling)的獨立單位**,不放進
erp-agent 的套件裡(放進去再 import = 把想拆掉的耦合裝回去)。放在 workspace 同層:
```
/home/hermes/
  erp-agent/            ← host(消費端)
  agents/
    ppt-agent/          ← 平行,自己的 venv/容器/.git;erp 靠 URL 連,不靠 import
    <下一個>-agent/      ← 之後比照
```
分界不是「資料夾」是「各自獨立的套件＋容器＋用協定連」。判斷只有兩條:**①每個 agent 有自己的
相依環境＋容器;②erp-agent 靠 URL 連它、不靠 import**。守住這兩條,放同 repo 或分開都行。

**參考實作:`../agents/ppt-agent/`**(以 `portable-agent-template` 為基底,python-pptx 引擎,自帶 `docker-compose.yml`)。

**標準(每個可攜式 agent 都照這個長)**:
```
<agent>/
  agent.yaml          ← manifest:id/version/transports/tools/resources(host 讀這份就會用)
  pyproject.toml      ← 自己的相依、自己的環境
  Dockerfile          ← 自己的容器
  src/<pkg>/
    core/             ← ★純核心:只 import 標準庫 + 領域套件(如 python-pptx)。
                         絕不 import langchain/langgraph/mcp/fastapi —— 那些都在 adapters/。
    adapters/
      mcp_server.py   ← ★對外通用契約(FastMCP);只暴露白名單工具,不給「執行任意程式」能力
      cli.py / rest.py / langgraph_node.py  ← 其他接法(選用)
```
兩條鐵律:**① core 不碰任何 I/O 與框架**(LLM/DB/檔案/網路走注入或 adapter);
**② 對外只認 manifest 的 tools + 傳輸協定**,破壞性變更升 major 版本。

**erp-agent 如何接(以 ppt 為例,仍只在 registry 一筆)**:
1. `tools/ppt_mcp.py` 的 `load_ppt_tools()` 經 MCP(sse/stdio)載入工具並快取。
   - **放在 `tools/` 而非 `graph/`**:因為 `agents/ppt_agent.py` 會 import 它,放 graph 會違反
     單向依賴 `graph → agents → tools`。新增別的 MCP agent 比照,放 `tools/<名稱>_mcp.py`。
   - **MCP 工具是 async-only**(sync invoke 會丟 NotImplementedError)。本專案 graph/api 全同步,
     所以 `ppt_mcp` 把它**包成同步工具**(在背景事件迴圈執行緒跑 coroutine),呼叫端零感知、
     不必把整張圖改成 async。
   - **載入失敗一律回空清單**(服務沒起來時 erp_graph 仍能 import、驗證仍過)。
2. `agents/ppt_agent.py` 的 `TOOLS` 來源改成 `load_ppt_tools()`;提示詞/`with_memory=False` 照舊。
3. `graph/registry.py` 那筆**不用動**(build 函數內部換 tools 即可)。

**產物交付契約**:可攜式 agent 寫檔到 `OUTPUTS_DIR`(uuid 檔名),工具回傳 `/files/<uuid>.pptx`;
讓它和 api 指到**同一個產出目錄**(本機 = `./generated`;容器 = bind-mount/volume),`/files` 即可下載。

**回滾**:`USE_PRESENTON_PPT=true` 切回舊的 Presenton 路徑(`tools/ppt_tools.py`,保留未刪)。

**啟動**:`start.sh` 會用 ppt-agent **自己的** compose(`../agents/ppt-agent/docker-compose.yml`)起容器
(sse);無 Docker 則退回 stdio(由 api 直接 spawn,需先建好其 `.venv`)。相關環境變數見 `.env.example`
(`PPT_AGENT_TRANSPORT`/`PPT_AGENT_URL`/`PPT_AGENT_PORT`/`PPT_AGENT_DIR`/`OUTPUTS_DIR`)。
換位置設 `PPT_AGENT_DIR`,連遠端既有服務設 `PPT_AGENT_URL`。

**驗證可攜性(解耦不污染)**:
```bash
# erp-agent 不得 import 任何可攜式 agent 的實作(只經 MCP)
grep -rn "import portable_agent\|from portable_agent\|from ppt_agent" agents/ api/ graph/ tools/   # 應為空
# 可攜式 agent 的 core 不得 import 框架(在 agent 自己的 repo 裡跑)
grep -rnE "^\s*(import|from)\s+(langchain|langgraph|mcp|fastapi|fastmcp)" ../agents/ppt-agent/src/*/core/  # 應為空
```

---

## 部署與通訊鐵則(容器 / k3s)

容器化編排的鐵則(完整 manifest 在 `k8s/`,runbook 見 `k8s/README.md`):

1. **容器邊界＝行程邊界**:跨容器只能走網路(URL),**不可 Python import**。同一行程內的
   in-process agent(本地 `@tool`)才走函式呼叫。
2. **連「Service 名固定入口」,不是 `localhost`、不是某個 replica 的 IP**:
   `PPT_AGENT_URL=http://ppt-agent:8000/sse`、DB `postgres:5432`。replica 由 Service/HPA 動態
   進出,erp-agent **永遠不改 URL**。內網埠用 Service 暴露即可,要 scale 就別 publish 到主機。
3. **兩層分開**:**調動**(supervisor 決定派誰)在 graph 內、記憶體、無 HTTP;**執行**才可能對外——
   in-process agent=函式呼叫,外部化 agent(MCP-backed)=MCP/HTTP 到該服務。LLM 呼叫是另一條 HTTPS。
4. **外部化 agent 必須常駐 up**:連線是「連到正在跑的服務」;它沒起來,`load_*_tools()` 會優雅
   回空清單(erp 仍能起,但該 agent 暫無工具)。**in-process agent 不另跑容器**,隨 host 一起跑。
   **MCP-SSE 是有狀態的**(GET `/sse` 拿 session_id、POST `/messages/?session_id=` 必須回同一 pod):
   replica>1 時 Service 一定要 `sessionAffinity: ClientIP`,否則 round-robin 會 404 把 client 弄死
   (見 `k8s/base/ppt-agent.yaml`)。要 SSE 真跨 replica 分流需 session 感知 LB,屬後續。
5. **每容器 `requests`+`limits` + readiness/liveness 必設**(對應 `agent.yaml`,§16)。MCP-SSE 無
   HTTP 健康端點 → 用 `tcpSocket` 探針;REST adapter 有 `/healthz` 可 `httpGet`。
6. **秘密放 Secret、設定放 ConfigMap**,env 注入,**勿烤進 image**(`.env`、金鑰都在 `.dockerignore`)。
7. **產物交付**:ppt-agent 寫 `OUTPUTS_DIR`、erp-api 的 `/files` 讀同一處 → 單機共用一個 PVC
   (local-path,RWO 同節點);**多節點/雲端**改 RWX(NFS/EFS)或改 MinIO 物件儲存(白皮書 §21.4)。
8. **單機用 k3s**(完整 k8s、輕量);manifest 一開始就寫成可轉雲端,轉換只改 overlay 的幾格
   (StorageClass / ingressClassName / SC),`base/` 的 Deployment/Service/HPA 不動。

> 現況:本機仍可用 `start.sh`(原生)開發;k3s 是另一條部署路徑(`k8s/`),兩者不衝突。
> 新增可攜式 agent 時,在 `k8s/base/` 比照 ppt-agent 加 Deployment+Service(+HPA),erp 連其 Service 名。

---

## Tool 撰寫規範

- 一律用 `@tool` 裝飾器(from `langchain_core.tools`)。
- **docstring 必寫、用繁中**:LLM 完全靠它判斷何時、如何呼叫工具。要寫清楚功能與每個參數。
- **回傳 `str`**:回給 LLM 閱讀的內容。查無資料 / 預期內的失敗,回傳「友善的說明字串」(參考 `query_inventory`),不要丟例外。
- 資料源可先寫死(如 `inventory_tools.py` 的字典)當示範,之後換真資料庫時只改 Tool,Agent 與 graph 不動。
- **純 LLM agent**(不需任何工具)可以 `TOOLS = []`,例如 `email`、`report`。
- **會產出檔案的工具**(如 `ppt`):把檔案存到專案根目錄的 `generated/`,回傳含 `/files/<檔名>` 的字串;
  後端已把 `generated/` 掛在 `/files` 供下載,前端會自動偵測 `/files/...` 並顯示下載鈕。

---

## 記憶體規則(重要,容易踩雷)

記憶體 = LangGraph 的 **checkpointer**,依 `thread_id` 區分的「對話歷史」。
**後端只在 `base_agent.py` 的 `get_checkpointer()` 一處決定**(與 `get_llm()` 對稱,換後端只改這裡):

- **設了 `CHECKPOINT_DATABASE_URL`(或退用 `DATABASE_URL`)且連得上 Postgres → `PostgresSaver` 持久化**:
  記憶不在 RAM,erp-agent 才能開**多 replica**(任何 replica 都接得到同一條對話)、程式重啟記憶還在。
  checkpoint 表(`checkpoints`/`checkpoint_writes` 等)建在 URL 指向的 DB,用「可寫」連線,與
  sql_tools 對 ERP 的唯讀連線獨立、表名不衝突。要記憶/業務分庫,把 URL 指向另一個 database 即可。
- **連不上 / 沒設 → 優雅退回 `MemorySaver`(RAM、程式關掉即消失)**:服務沒起來時 erp 仍能 import、
  驗證仍過,只是記憶不持久、不能橫向擴。

| 場景 | 怎麼做 | 記憶由誰管 |
|---|---|---|
| 單獨跑某個 Agent | `build_xxx_agent()`(預設 `with_memory=True`) | Agent 自己,後端由 `get_checkpointer()` 決定 |
| 接進 graph 當節點 | `build_xxx_agent(with_memory=False)` | **graph 那層的單一 checkpointer**(同上來源) |

- 呼叫時要帶 `config={"configurable": {"thread_id": "<對話ID>"}}`;同 ID = 同一條對話。
- **絕不**讓接進 graph 的子 Agent 自帶記憶(會和 graph 那層的 checkpointer 打架)。

---

## graph 連接方式(supervisor 模式)

- 拓樸:`START → supervisor →（指派）→ 某個 Agent → supervisor → ... → FINISH(END)`。
  **一個請求可串接多個 Agent**(例:先 `pdf` 分析、再 `inventory` 查庫存)。
- `supervisor` 看**完整對話歷史**決定下一步:指派某個 Agent,或回答 `FINISH` 結束。
- 每個 Agent 跑完都**回到 supervisor**;其產出會以該 Agent 名稱(`message.name`)標記,
  供 supervisor 判斷進度、避免重複指派。
- 狀態型別 `ERPState` 繼承 `MessagesState`,額外帶 `route`(supervisor 的決策)。
  Agent 之間靠 `messages` 傳遞;若要傳結構化資料,在 `ERPState` 加欄位。
- 整張圖由 `registry.py` 自動生成,新增 Agent 不需改 `erp_graph.py`。

---

## 慣例

- 所有面向使用者的輸出用**繁體中文**。
- 檔名:`<名稱>_agent.py` / `<名稱>_tools.py`;registry key 用簡短小寫英文(如 `pdf`)。
- 每個 Agent 模組匯出:`SYSTEM_PROMPT`、`TOOLS`、`build_<名稱>_agent()`、以及標準實例。

---

## 驗證指令

改完後務必跑這個(不需 API Key,純檢查能否編譯、節點與路由是否自動接好):

```bash
venv/bin/python -c "
import os; os.environ.setdefault('OPENAI_API_KEY','sk-test-dummy')
from graph.erp_graph import erp_graph
from graph.registry import AGENTS
print('已登記 Agent:', list(AGENTS))
print('節點:', sorted(erp_graph.get_graph().nodes))
"
```

實際端到端(需在 `.env` 填好 `OPENAI_API_KEY`,會產生費用):

```bash
venv/bin/python -m graph.erp_graph        # 跑主流程
venv/bin/python -m agents.inventory_agent # 單獨跑某個 Agent
```

---

## 已知限制 / 待辦

- `supervisor` 每輪都會多一次 LLM 呼叫(調度用);串接 N 個 Agent 約 N+1 次調度呼叫,屬正常成本。
- supervisor 是回圈,理論上可能無限循環。靠提示詞(完成即 FINISH)+ LangGraph 預設
  `recursion_limit`(25)收斂;若流程很長可在 `.invoke(..., {"recursion_limit": N})` 調高。
- 記憶後端:連得上 Postgres 時用 `PostgresSaver` 持久化(可多 replica),否則退回 RAM 的
  `MemorySaver`(見「記憶體規則」)。
- SQL 範例庫 / schema 檢索目前是「單一資料庫」。要支援**多個 database**:在
  `catalog.json` / `schema.json` 各筆標註所屬 `db`,並加一層連線路由(先選 DB 再選表/SQL);
  資料量很大時 `_semantic_index` 可換成真正的向量資料庫(呼叫端介面不變)。
