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

記憶體 = LangGraph 的 **checkpointer**(目前用 `MemorySaver`)。本質:
**存在 RAM、依 `thread_id` 區分的「對話歷史」,存活範圍是程式行程的生命週期 —— 程式關掉就消失,並非永久。**

| 場景 | 怎麼做 | 記憶由誰管 |
|---|---|---|
| 單獨跑某個 Agent | `build_xxx_agent()`(預設 `with_memory=True`) | Agent 自己,**每個 Agent 各自一個 MemorySaver** |
| 接進 graph 當節點 | `build_xxx_agent(with_memory=False)` | **graph 那層的單一 MemorySaver** |

- 呼叫時要帶 `config={"configurable": {"thread_id": "<對話ID>"}}`;同 ID = 同一條對話。
- **絕不**讓接進 graph 的子 Agent 自帶記憶(會和 graph 那層的 checkpointer 打架)。
- 要「永久記憶」(重開程式還在):把 `base_agent.py` / `erp_graph.py` 的 `MemorySaver()`
  換成 `SqliteSaver` 或 `PostgresSaver` 即可,其餘不動。

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
- `MemorySaver` 是 RAM、非永久(見「記憶體規則」的升級方式)。
- SQL 範例庫 / schema 檢索目前是「單一資料庫」。要支援**多個 database**:在
  `catalog.json` / `schema.json` 各筆標註所屬 `db`,並加一層連線路由(先選 DB 再選表/SQL);
  資料量很大時 `_semantic_index` 可換成真正的向量資料庫(呼叫端介面不變)。
