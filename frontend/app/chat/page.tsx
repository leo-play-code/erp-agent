"use client";

import { useEffect, useRef, useState } from "react";
import { streamChat, listAgents, type ChatMessage } from "@/lib/api";
import Markdown from "../components/Markdown";

// 每個 agent 的頭像圖示、配色與顯示名稱（與單一 agent 頁一致）
const ICON: Record<string, string> = {
  pdf: "📄",
  inventory: "📦",
  ppt: "📊",
  email: "✉️",
  report: "📈",
  image: "🖼️",
  sql: "🗄️",
};
const AVATAR_BG: Record<string, string> = {
  pdf: "#635bff",
  inventory: "#00b37e",
  ppt: "#ff7a00",
  email: "#0a85ff",
  report: "#8b5cf6",
  image: "#06b6d4",
  sql: "#0d9488",
};
// 空狀態的範例快捷鈕（老闆級分析；點一下直接送出）
const SUGGESTIONS = [
  {
    t: "📊 本季經營體檢",
    s: "營收毛利、準交、良率、庫存、客戶集中度一次看",
    p: "以老闆視角做一份本季經營體檢：營收與毛利率趨勢、準交率、生產良率、庫存健康度與客戶集中度，把有風險的地方點出來，並依優先順序給我決策建議。",
  },
  {
    t: "🚚 準交率為什麼下滑",
    s: "找出交貨延遲的原因與改善方向",
    p: "分析最近幾個月準交率的變化趨勢，並從生產良率、機台停機、訂單量等面向找出可能原因，給我具體可執行的改善建議。",
  },
  {
    t: "📦 庫存呆滯盤點",
    s: "哪些庫存金額高、可能呆滯或缺料",
    p: "盤點目前庫存：哪些產品與原料的庫存金額最高、可能呆滯？有哪些原料低於安全庫存？給我處理建議。",
  },
  {
    t: "🏆 客戶與產品貢獻",
    s: "營收毛利的集中度與風險",
    p: "分析各客戶與各產品的營收與毛利貢獻，前五大各佔多少比例？有沒有過度集中的風險？",
  },
  {
    t: "📚 查公司知識庫",
    s: "問已建檔文件，或了解怎麼建立索引",
    p: "知識庫裡目前有哪些資料？另外，我要怎麼把公司的文件、或某個資料夾加進知識庫？",
  },
];

// 對話中顯示的友善名稱（取代生硬的英文 key，如 sql → 資料查詢）
const NAME: Record<string, string> = {
  pdf: "PDF 分析",
  inventory: "庫存查詢",
  ppt: "簡報製作",
  email: "Email 撰寫",
  report: "報表分析",
  image: "圖片 OCR",
  sql: "資料查詢",
};

// 一段對話：自帶 sessionId（後端 thread_id）與訊息；存在瀏覽器 localStorage。
type Conversation = {
  id: string;
  title: string;
  sessionId: string;
  messages: ChatMessage[];
  updatedAt: number;
};

const STORAGE_KEY = "erp_chats";
const uid = () => crypto.randomUUID();
const newConv = (): Conversation => ({
  id: uid(),
  title: "新對話",
  sessionId: uid(),
  messages: [],
  updatedAt: Date.now(),
});

export default function ChatPage() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState("");
  const [input, setInput] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null); // 目前正在工作的 Agent
  const [descs, setDescs] = useState<Record<string, string>>({}); // agent → 在做什麼
  const [error, setError] = useState("");
  const [editingIndex, setEditingIndex] = useState<number | null>(null);
  const [editingText, setEditingText] = useState("");
  const [sidebarOpen, setSidebarOpen] = useState(false); // 手機版抽屜側欄
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  const active = conversations.find((c) => c.id === activeId) ?? null;

  // 載入 localStorage 的對話；沒有就開一個新的。同時取 Agent 說明給狀態列用。
  useEffect(() => {
    let convs: Conversation[] = [];
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) convs = JSON.parse(raw);
    } catch {
      convs = [];
    }
    if (!Array.isArray(convs) || convs.length === 0) convs = [newConv()];
    setConversations(convs);
    setActiveId(convs[0].id);
    listAgents()
      .then((as) => setDescs(Object.fromEntries(as.map((a) => [a.name, a.desc]))))
      .catch(() => {});
  }, []);

  // 任何變動都存回 localStorage
  useEffect(() => {
    if (conversations.length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations));
    }
  }, [conversations]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [active?.messages, loading]);

  const patchConv = (id: string, fn: (c: Conversation) => Conversation) =>
    setConversations((cs) => cs.map((c) => (c.id === id ? fn(c) : c)));

  function newChat() {
    if (loading) return;
    const c = newConv();
    setConversations((cs) => [c, ...cs]);
    setActiveId(c.id);
    setEditingIndex(null);
    setSidebarOpen(false);
  }

  function selectChat(id: string) {
    setActiveId(id);
    setEditingIndex(null);
    setError("");
    setSidebarOpen(false);
  }

  function deleteChat(id: string) {
    setConversations((cs) => {
      const rest = cs.filter((c) => c.id !== id);
      const next = rest.length ? rest : [newConv()];
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  // 核心：跑一輪。history 有值代表這是「編輯/重跑分支」，把該點之前的對話當脈絡種子。
  async function runTurn(
    convId: string,
    sessionId: string,
    userText: string,
    history?: ChatMessage[]
  ) {
    patchConv(convId, (c) => ({
      ...c,
      sessionId,
      title:
        c.messages.length === 0 || c.title === "新對話"
          ? userText.slice(0, 30)
          : c.title,
      messages: [...c.messages, { agent: null, role: "human", content: userText }],
      updatedAt: Date.now(),
    }));
    setLoading(true);
    setStatus(null);
    setError("");
    const sentFile = file;
    setFile(null);
    const controller = new AbortController();
    abortRef.current = controller;
    let gotMessage = false;
    let hadError = false;
    try {
      await streamChat(
        userText,
        sessionId,
        sentFile,
        (ev) => {
          if (ev.type === "status") {
            setStatus(ev.agent);
          } else if (ev.type === "message") {
            gotMessage = true;
            patchConv(convId, (c) => ({
              ...c,
              messages: [...c.messages, { agent: ev.agent, role: "ai", content: ev.content }],
              updatedAt: Date.now(),
            }));
            setStatus(null);
          } else if (ev.type === "error") {
            hadError = true;
            setError(ev.detail);
          }
        },
        { history, signal: controller.signal }
      );
    } catch (e) {
      // 使用者按「停止」造成的中止不算錯誤
      if ((e as Error).name !== "AbortError") {
        hadError = true;
        setError((e as Error).message);
      }
    } finally {
      setLoading(false);
      setStatus(null);
      abortRef.current = null;
    }
    // 防呆：一輪結束卻沒有任何回覆，不要讓畫面「沒動靜」——給明確提示
    if (!gotMessage && !hadError && !controller.signal.aborted) {
      setError("這一輪沒有產生回覆，請換個說法或補充更多需求再試一次。");
    }
  }

  function handleSend() {
    const text = input.trim();
    if (!text || loading || !active) return;
    setInput("");
    // 一般接續：用該對話既有的 sessionId（後端靠它的記憶延續）
    runTurn(active.id, active.sessionId, text);
  }

  // 範例快捷鈕：直接用指定問題開跑一輪
  function sendPrompt(text: string) {
    if (loading || !active) return;
    runTurn(active.id, active.sessionId, text);
  }

  function stop() {
    abortRef.current?.abort();
  }

  function startEdit(i: number, content: string) {
    if (loading) return;
    setEditingIndex(i);
    setEditingText(content);
  }

  function saveEdit() {
    if (editingIndex == null || !active) return;
    const text = editingText.trim();
    if (!text) return;
    const idx = editingIndex;
    const history = active.messages.slice(0, idx); // 編輯點之前的對話當脈絡
    const branchSession = uid(); // 新 thread，避免和舊記憶衝突
    patchConv(active.id, (c) => ({
      ...c,
      messages: c.messages.slice(0, idx), // 砍掉編輯點(含)之後
      sessionId: branchSession,
    }));
    setEditingIndex(null);
    setEditingText("");
    runTurn(active.id, branchSession, text, history);
  }

  const msgs = active?.messages ?? [];

  return (
    <div className="chat-shell">
      {/* 手機版點背景關閉抽屜 */}
      <div
        className={`chat-backdrop${sidebarOpen ? " show" : ""}`}
        onClick={() => setSidebarOpen(false)}
      />

      {/* 對話紀錄側欄：貼最左邊、整高 */}
      <aside className={`chat-sidebar${sidebarOpen ? " open" : ""}`}>
        <button className="new-chat-btn" onClick={newChat} disabled={loading}>
          ＋ 新對話
        </button>
        <div className="conv-list">
          {conversations.map((c) => (
            <div
              key={c.id}
              className={`conv-item${c.id === activeId ? " active" : ""}`}
              onClick={() => selectChat(c.id)}
            >
              <span className="conv-title">{c.title || "新對話"}</span>
              <button
                className="conv-del"
                title="刪除對話"
                onClick={(e) => {
                  e.stopPropagation();
                  deleteChat(c.id);
                }}
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      </aside>

      {/* 主對話區 */}
      <div className="chat-main">
        {/* 手機版頂部列：開關側欄 + 目前對話標題 */}
        <div className="chat-topbar">
          <button
            className="sidebar-toggle"
            onClick={() => setSidebarOpen((v) => !v)}
            title="對話紀錄"
          >
            ☰
          </button>
          <span className="chat-topbar-title">{active?.title || "多 Agent 對話"}</span>
        </div>

        <div className="chat-scroll">
          <div className="chat-thread">
            {msgs.length === 0 && !loading && (
              <div className="chat-empty">
                <div className="chat-empty-title">多 Agent 對話</div>
                <p>描述你的需求，supervisor 會自動派合適的 Agent；或從下面的範例開始：</p>
                <div className="suggest-chips">
                  {SUGGESTIONS.map((g) => (
                    <button
                      key={g.t}
                      type="button"
                      className="suggest-chip"
                      onClick={() => sendPrompt(g.p)}
                      disabled={loading}
                      title={g.s}
                    >
                      <span className="suggest-chip-title">{g.t}</span>
                      <span className="suggest-chip-sub">{g.s}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {msgs.map((m, i) => {
              const isUser = m.role === "human";
              const agent = m.agent ?? "agent";
              return (
                <div key={i} className={`msg-row ${isUser ? "user" : "assistant"}`}>
                  <div
                    className={`msg-avatar ${isUser ? "user" : ""}`}
                    style={isUser ? undefined : { background: AVATAR_BG[agent] ?? "#8a94a6" }}
                  >
                    {isUser ? "你" : ICON[agent] ?? "🤖"}
                  </div>
                  <div className="msg-body">
                    <div className="msg-who">{isUser ? "你" : NAME[agent] ?? agent}</div>
                    {isUser && editingIndex === i ? (
                      <>
                        <textarea
                          className="textarea"
                          autoFocus
                          style={{ width: "100%", minHeight: 60 }}
                          value={editingText}
                          onChange={(e) => setEditingText(e.target.value)}
                        />
                        <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
                          <button className="btn btn-white" onClick={() => setEditingIndex(null)}>
                            取消
                          </button>
                          <button className="btn btn-primary" onClick={saveEdit} disabled={loading}>
                            送出並重跑
                          </button>
                        </div>
                      </>
                    ) : isUser ? (
                      <>
                        <div className="msg-user-text">{m.content}</div>
                        {!loading && (
                          <button className="msg-edit-btn" onClick={() => startEdit(i, m.content)}>
                            ✎ 編輯
                          </button>
                        )}
                      </>
                    ) : (
                      <Markdown content={m.content} />
                    )}
                  </div>
                </div>
              );
            })}

            {loading && (
              <div className="msg-row">
                <div
                  className="msg-avatar"
                  style={{ background: status ? AVATAR_BG[status] ?? "#8a94a6" : "#8a94a6" }}
                >
                  {status ? ICON[status] ?? "🤖" : "🤖"}
                </div>
                <div className="msg-body" style={{ display: "flex", gap: 10, alignItems: "center" }}>
                  <span className="spinner spinner-dark" />
                  <span style={{ color: "var(--slate)" }}>
                    {status
                      ? `正在使用 ${NAME[status] ?? status}${descs[status] ? `：${descs[status]}` : ""}…`
                      : "supervisor 調度中…"}
                  </span>
                </div>
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        {/* 底部 composer */}
        <div className="composer-wrap">
          <div className="composer">
            <label className={`composer-btn composer-attach${file ? " has-file" : ""}`} title="附加檔案">
              📎
              <input
                type="file"
                style={{ display: "none" }}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <textarea
              className="composer-input"
              rows={1}
              placeholder="輸入訊息，按 Enter 送出（Shift+Enter 換行）"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            {loading ? (
              <button className="composer-btn composer-send stop" onClick={stop} title="停止">
                ■
              </button>
            ) : (
              <button
                className="composer-btn composer-send"
                disabled={!input.trim()}
                onClick={handleSend}
                title="送出"
              >
                ↑
              </button>
            )}
          </div>
          {(file || error) && (
            <div className="composer-meta">
              {file && (
                <span className="composer-file">
                  📎 已附檔 <b>{file.name}</b>
                  <button className="composer-clear" onClick={() => setFile(null)} title="移除">
                    ✕
                  </button>
                </span>
              )}
              {error && <span className="composer-error">⚠️ {error}</span>}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
