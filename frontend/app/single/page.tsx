"use client";

import { useEffect, useState } from "react";
import {
  listAgents,
  listPptOptions,
  runAgent,
  extractFileLink,
  type AgentInfo,
  type PptOptions,
} from "@/lib/api";
import FileCard from "../components/FileCard";

// 每個 agent 的 icon、配色、精簡描述、以及「需提供什麼」（前端定義；未登記的用 fallback）
const META: Record<
  string,
  { icon: string; color: string; blurb: string; needs: string }
> = {
  pdf: { icon: "📄", color: "#635bff", blurb: "讀取 PDF 並條列重點摘要", needs: "PDF 檔案" },
  inventory: { icon: "📦", color: "#00b37e", blurb: "查詢品項的庫存數量與儲位", needs: "品項名稱（如：螺絲）" },
  ppt: { icon: "📊", color: "#ff7a00", blurb: "依主題或大綱產出簡報檔", needs: "簡報主題或大綱" },
  email: { icon: "✉️", color: "#0a85ff", blurb: "擬一封專業商務 email 草稿", needs: "情境與目的" },
  report: { icon: "📈", color: "#8b5cf6", blurb: "數據摘要、趨勢與洞察分析", needs: "要分析的數據" },
  image: { icon: "🖼️", color: "#06b6d4", blurb: "辨識圖片中的文字（OCR）", needs: "圖片檔（png/jpg）" },
  sql: { icon: "🗄️", color: "#0d9488", blurb: "查詢人資與製造營運的數字", needs: "想查的問題（如：特休前5名）" },
  analyst: { icon: "🧠", color: "#7c3aed", blurb: "整合營運數據、找趨勢、給決策建議", needs: "經營問題（如：本季體檢）" },
  rag: { icon: "📚", color: "#0ea5e9", blurb: "文件建索引、語意檢索問答（RAG）", needs: "上傳文件，或直接問已建檔內容" },
};
const fallback = { icon: "🤖", color: "#635bff", blurb: "", needs: "" };
const metaOf = (name: string) => META[name] ?? fallback;

export default function SinglePage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [listError, setListError] = useState("");
  const [active, setActive] = useState<AgentInfo | null>(null);

  // modal 內的表單狀態
  const [message, setMessage] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [reply, setReply] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // ppt 專用：ppt-workflow 的選項（對象/風格/篇幅/語氣）與目前選定值（每組預設取第一個）
  const [pptOptions, setPptOptions] = useState<PptOptions | null>(null);
  const [pptSel, setPptSel] = useState<Record<string, string>>({});

  useEffect(() => {
    listAgents()
      .then(setAgents)
      .catch((e) => setListError(e.message));
    // 簡報選項只給 ppt 用；抓失敗就靜默（選擇器不顯示，仍可純文字使用）
    listPptOptions()
      .then((o) => {
        setPptOptions(o);
        // 每組預設選第一個
        const init: Record<string, string> = {};
        for (const [k, opts] of Object.entries(o.groups)) init[k] = opts[0]?.key ?? "";
        setPptSel(init);
      })
      .catch(() => {});
  }, []);

  function open(agent: AgentInfo) {
    setActive(agent);
    setMessage("");
    setFile(null);
    setReply("");
    setError("");
  }
  const close = () => setActive(null);

  // Esc 關閉 modal
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [active]);

  const isPpt = !!active && active.name === "ppt" && !!pptOptions;

  async function handleRun() {
    if (!active) return;
    if (active.needs_text && !message.trim()) return;
    if (!active.needs_text && !file) return;
    setLoading(true);
    setError("");
    setReply("");
    try {
      // 不需文字的 agent（如 image）：送一句預設指令，讓它直接處理圖片
      let text = active.needs_text ? message : "請辨識這張圖片的文字";
      // ppt：把使用者用按鈕選的設定（對象/風格/篇幅/語氣）一起送出，agent 直接餵給 make_deck
      if (isPpt && pptOptions) {
        const settings = Object.keys(pptOptions.groups)
          .filter((k) => pptSel[k])
          .map((k) => `${pptOptions.labels[k] ?? k}:${pptSel[k]}`)
          .join("；");
        text = `（簡報設定 → ${settings}）\n${text}`;
      }
      setReply(await runAgent(active.name, text, file));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="container" style={{ padding: "56px 24px 80px" }}>
      <h1 className="page-title">單一 Agent</h1>
      <p className="muted page-lead">選一個 Agent 點進去，提供需求即可直接處理。</p>

      {listError && <p style={{ color: "#cd3d64" }}>⚠️ {listError}</p>}
      {agents.length === 0 && !listError && <p className="muted">載入中…</p>}

      <div className="agent-grid">
        {agents.map((a) => {
          const m = metaOf(a.name);
          return (
            <button key={a.name} className="agent-card" onClick={() => open(a)}>
              <span className="card-icon" style={{ background: m.color + "1a" }}>
                {m.icon}
              </span>
              <span className="card-body">
                <span className="name">{a.name}</span>
                <span className="blurb">{m.blurb || a.desc}</span>
                {m.needs && (
                  <span className="needs">
                    <strong>需提供：</strong>
                    {m.needs}
                  </span>
                )}
              </span>
            </button>
          );
        })}
      </div>

      {/* Modal */}
      {active && (
        <div className="modal-overlay" onClick={close}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={close} aria-label="關閉">
              ✕
            </button>

            <div className="modal-head">
              <span
                className="avatar avatar-sm"
                style={{ background: metaOf(active.name).color + "1a" }}
              >
                {metaOf(active.name).icon}
              </span>
              <div>
                <div style={{ fontSize: 20, fontWeight: 700 }}>{active.name}</div>
                <div className="desc" style={{ fontSize: 14, color: "var(--slate)" }}>
                  {active.desc}
                </div>
              </div>
            </div>

            {isPpt && pptOptions && (
              <>
                {Object.entries(pptOptions.groups).map(([group, opts]) => (
                  <div key={group} style={{ marginBottom: 14 }}>
                    <label className="field-label">
                      {pptOptions.labels[group] ?? group}
                    </label>
                    <div
                      style={{
                        display: "flex",
                        flexWrap: "wrap",
                        gap: 8,
                        marginTop: 8,
                      }}
                    >
                      {opts.map((o) => {
                        const selected = o.key === pptSel[group];
                        return (
                          <button
                            key={o.key}
                            type="button"
                            onClick={() =>
                              setPptSel((s) => ({ ...s, [group]: o.key }))
                            }
                            className={`agent-option${selected ? " selected" : ""}`}
                            style={{ minWidth: 96, flex: "0 0 auto" }}
                            title={o.key}
                          >
                            <span className="name">
                              {selected ? "✓ " : ""}
                              {o.zh}
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
                <div style={{ height: 8 }} />
              </>
            )}

            {active.needs_text && (
              <>
                <label className="field-label">
                  需求描述
                  {metaOf(active.name).needs && (
                    <span style={{ color: "var(--slate)", fontWeight: 400 }}>
                      　·　需提供：{metaOf(active.name).needs}
                    </span>
                  )}
                </label>
                <textarea
                  className="textarea"
                  autoFocus
                  placeholder={
                    metaOf(active.name).needs
                      ? `請提供：${metaOf(active.name).needs}`
                      : "輸入你的需求…"
                  }
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                />
              </>
            )}

            {active.accepts_file && (
              <>
                <label
                  className="field-label"
                  style={{ marginTop: active.needs_text ? 18 : 0 }}
                >
                  {active.needs_text ? "附加檔案（選填）" : "上傳圖片（必填）"}
                </label>
                <input
                  type="file"
                  className="input"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </>
            )}

            <button
              className="btn btn-primary"
              style={{ marginTop: 22 }}
              disabled={
                loading || (active.needs_text ? !message.trim() : !file)
              }
              onClick={handleRun}
            >
              {loading && <span className="spinner" />}
              {loading ? "執行中…" : "執行"}
            </button>

            {error && <p style={{ color: "#cd3d64", marginTop: 18 }}>⚠️ {error}</p>}

            {reply && (
              <div
                style={{
                  marginTop: 24,
                  padding: 20,
                  background: "var(--light)",
                  border: "1px solid var(--border)",
                  borderRadius: 12,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.7,
                }}
              >
                {reply}
                {(() => {
                  const link = extractFileLink(reply);
                  if (!link) return null;
                  return (
                    <div style={{ marginTop: 16 }}>
                      <FileCard link={link} />
                    </div>
                  );
                })()}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
