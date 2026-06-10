"use client";

import { useEffect, useRef, useState } from "react";
import {
  ragStats,
  ragSyncFolder,
  ragUpload,
  wikiUpload,
  wikiCompileFolder,
  wikiDrafts,
  wikiDeleteDraft,
  wikiPublish,
  wikiPublishAll,
  type KbSummary,
  type WikiDraft,
} from "@/lib/api";

// 知識庫後台：設定要訓練的資料夾路徑、上傳檔案建索引。
// 前端的 RAG agent 只做問答，「訓練 / 建索引」集中在這一頁（呼叫後端 admin API）。
export default function AdminPage() {
  const [stats, setStats] = useState<KbSummary | null>(null);
  const [statsError, setStatsError] = useState("");
  const [kbSearch, setKbSearch] = useState("");

  const [folder, setFolder] = useState("");
  const [folderBusy, setFolderBusy] = useState(false);
  const [folderMsg, setFolderMsg] = useState("");
  const [folderErr, setFolderErr] = useState("");

  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [uploadBusy, setUploadBusy] = useState(false);
  const [uploadMsg, setUploadMsg] = useState("");
  const [uploadErr, setUploadErr] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);

  // 知識庫 vault 流程：上傳 → AI 整理 → 審核 → 發布
  const [wikiFile, setWikiFile] = useState<File | null>(null);
  const [wikiDragging, setWikiDragging] = useState(false);
  const [wikiBusy, setWikiBusy] = useState(false);
  const [wikiMsg, setWikiMsg] = useState("");
  const [wikiErr, setWikiErr] = useState("");
  const wikiInput = useRef<HTMLInputElement>(null);
  const [drafts, setDrafts] = useState<WikiDraft[]>([]);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [rowBusy, setRowBusy] = useState("");
  const [allBusy, setAllBusy] = useState(false);
  const [draftSearch, setDraftSearch] = useState("");

  // 資料夾批次 AI 編譯
  const [folderC, setFolderC] = useState("");
  const [folderCBusy, setFolderCBusy] = useState(false);
  const [folderCMsg, setFolderCMsg] = useState("");
  const [folderCErr, setFolderCErr] = useState("");

  function refreshStats() {
    ragStats()
      .then((s) => {
        setStats(s);
        setStatsError("");
      })
      .catch((e) => setStatsError(e.message));
  }
  function refreshDrafts() {
    wikiDrafts()
      .then(setDrafts)
      .catch(() => {});
  }
  useEffect(refreshStats, []);
  useEffect(refreshDrafts, []);

  async function handleWikiUpload() {
    if (!wikiFile) return;
    setWikiBusy(true);
    setWikiMsg("");
    setWikiErr("");
    try {
      const r = await wikiUpload(wikiFile);
      setWikiMsg(r.text);
      setWikiFile(null);
      refreshDrafts();
    } catch (e) {
      setWikiErr((e as Error).message);
    } finally {
      setWikiBusy(false);
    }
  }

  async function handlePublish(name: string, content: string) {
    setRowBusy(name);
    setWikiErr("");
    try {
      await wikiPublish(name, content);
      setEdited((m) => {
        const n = { ...m };
        delete n[name];
        return n;
      });
      refreshDrafts();
      refreshStats();
    } catch (e) {
      setWikiErr((e as Error).message);
    } finally {
      setRowBusy("");
    }
  }

  async function handlePublishAll() {
    if (drafts.length === 0) return;
    setAllBusy(true);
    setWikiErr("");
    try {
      const items = drafts.map((d) => ({ name: d.name, content: edited[d.name] ?? d.content }));
      await wikiPublishAll(items);
      setEdited({});
      refreshDrafts();
      refreshStats();
    } catch (e) {
      setWikiErr((e as Error).message);
    } finally {
      setAllBusy(false);
    }
  }

  async function handleDeleteDraft(name: string) {
    setRowBusy(name);
    setWikiErr("");
    try {
      await wikiDeleteDraft(name);
      refreshDrafts();
    } catch (e) {
      setWikiErr((e as Error).message);
    } finally {
      setRowBusy("");
    }
  }

  function onWikiDrop(e: React.DragEvent) {
    e.preventDefault();
    setWikiDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setWikiFile(f);
  }

  async function handleCompileFolder() {
    if (!folderC.trim()) return;
    setFolderCBusy(true);
    setFolderCMsg("");
    setFolderCErr("");
    try {
      const r = await wikiCompileFolder(folderC.trim());
      setFolderCMsg(r.text);
      refreshDrafts();
    } catch (e) {
      setFolderCErr((e as Error).message);
    } finally {
      setFolderCBusy(false);
    }
  }

  async function handleSync() {
    if (!folder.trim()) return;
    setFolderBusy(true);
    setFolderMsg("");
    setFolderErr("");
    try {
      setFolderMsg(await ragSyncFolder(folder.trim()));
      refreshStats();
    } catch (e) {
      setFolderErr((e as Error).message);
    } finally {
      setFolderBusy(false);
    }
  }

  async function handleUpload() {
    if (!file) return;
    setUploadBusy(true);
    setUploadMsg("");
    setUploadErr("");
    try {
      setUploadMsg(await ragUpload(file));
      setFile(null);
      refreshStats();
    } catch (e) {
      setUploadErr((e as Error).message);
    } finally {
      setUploadBusy(false);
    }
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files?.[0];
    if (f) setFile(f);
  }

  const kbFiltered = (stats?.sources ?? []).filter((s) =>
    s.name.toLowerCase().includes(kbSearch.trim().toLowerCase())
  );
  const draftFiltered = drafts.filter((d) =>
    d.name.toLowerCase().includes(draftSearch.trim().toLowerCase())
  );

  return (
    <div className="container" style={{ padding: "56px 24px 80px", maxWidth: 820 }}>
      <h1 className="page-title">知識庫後台</h1>
      <p className="muted page-lead">
        設定要訓練的資料夾，或上傳檔案建立向量索引。前端的 RAG 問答會用這裡建好的知識庫作答。
      </p>

      {/* 目前知識庫現況 */}
      <div className="card admin-card" style={{ marginBottom: 24 }}>
        <div className="section-head" style={{ marginBottom: 0 }}>
          <span className="section-icon" style={{ background: "#e8f7ff", color: "#0284c7" }}>
            📚
          </span>
          <div style={{ flex: 1 }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <h3 style={{ margin: "2px 0 4px" }}>目前知識庫</h3>
              <button
                className="btn btn-white"
                style={{ padding: "7px 14px", fontSize: 13 }}
                onClick={refreshStats}
              >
                ↻ 重新整理
              </button>
            </div>
            <p className="section-desc">RAG 問答的依據來源；下方新增資料後會即時更新。</p>
          </div>
        </div>

        {statsError ? (
          <div className="banner banner-err" style={{ marginTop: 18 }}>
            ⚠️ {statsError}
          </div>
        ) : !stats ? (
          <p className="muted" style={{ marginTop: 18 }}>
            載入中…
          </p>
        ) : (
          <div style={{ marginTop: 18 }}>
            <div className="admin-stat-grid">
              <div className="admin-stat">
                <div className="num">{stats.total_segments}</div>
                <div className="label">內容段數</div>
              </div>
              <div className="admin-stat">
                <div className="num">{stats.source_count}</div>
                <div className="label">文件來源</div>
              </div>
            </div>
            {stats.sources.length === 0 ? (
              <div className="kb-empty">知識庫還是空的 —— 從下方設定資料夾或上傳檔案開始建立。</div>
            ) : (
              <div style={{ marginTop: 14 }}>
                <input
                  className="input"
                  placeholder="🔍 搜尋來源檔名…"
                  value={kbSearch}
                  onChange={(e) => setKbSearch(e.target.value)}
                  style={{ marginBottom: 10 }}
                />
                <div
                  style={{
                    maxHeight: 300,
                    overflowY: "auto",
                    border: "1px solid var(--border)",
                    borderRadius: 10,
                    padding: 6,
                  }}
                >
                  {kbFiltered.length === 0 ? (
                    <div className="muted" style={{ padding: "12px 10px" }}>
                      找不到符合「{kbSearch}」的來源。
                    </div>
                  ) : (
                    kbFiltered.map((s) => (
                      <div className="kb-source" key={s.name}>
                        <span className="kb-source-icon">📄</span>
                        <span className="kb-source-name">{s.name}</span>
                        <span className="kb-pill">{s.segments} 段</span>
                      </div>
                    ))
                  )}
                </div>
                <div className="muted" style={{ marginTop: 8, fontSize: 12 }}>
                  共 {stats.sources.length} 個來源
                  {kbSearch.trim() && `，符合 ${kbFiltered.length} 個`}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 新增知識：上傳 → AI 整理 → 審核 → 發布（一站完成） */}
      <div className="card admin-card" style={{ marginBottom: 24 }}>
        <div className="section-head">
          <span className="section-icon" style={{ background: "#eafff1", color: "#16a34a" }}>
            🧩
          </span>
          <div>
            <h3>新增知識（AI 整理 + 審核）</h3>
            <p className="section-desc">
              上傳文件，AI 自動拆成原子筆記草稿；你在下方檢視 / 編輯後按「發布」，即加入知識庫並重新索引。
            </p>
          </div>
        </div>

        <div
          className={`dropzone${wikiDragging ? " drag" : ""}${wikiFile ? " has-file" : ""}`}
          onClick={() => wikiInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setWikiDragging(true);
          }}
          onDragLeave={() => setWikiDragging(false)}
          onDrop={onWikiDrop}
        >
          <span className="dz-icon">{wikiFile ? "📄" : "⬆️"}</span>
          <span className="dz-main">
            {wikiFile ? wikiFile.name : "點此選擇檔案，或拖放到這裡"}
          </span>
          <span className="dz-sub">
            {wikiFile
              ? `${(wikiFile.size / 1024).toFixed(1)} KB · 點擊可重新選擇`
              : "支援 PDF / Word / Excel / .txt / .md 等"}
          </span>
          <input
            ref={wikiInput}
            type="file"
            accept=".pdf,.txt,.md,.markdown,.docx,.pptx,.xlsx,.xls,.csv,.html,.htm"
            style={{ display: "none" }}
            onChange={(e) => setWikiFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <button
          className="btn btn-primary"
          style={{ marginTop: 18 }}
          disabled={wikiBusy || !wikiFile}
          onClick={handleWikiUpload}
        >
          {wikiBusy && <span className="spinner" />}
          {wikiBusy ? "AI 整理中…（約數十秒）" : "上傳並 AI 整理"}
        </button>
        {wikiErr && <div className="banner banner-err">⚠️ {wikiErr}</div>}
        {wikiMsg && <div className="banner banner-ok">✓ {wikiMsg}</div>}
      </div>

      {/* 資料夾批次 AI 整理 → 草稿 */}
      <div className="card admin-card" style={{ marginBottom: 24 }}>
        <div className="section-head">
          <span className="section-icon" style={{ background: "#eef2ff", color: "#4f46e5" }}>
            🗂️
          </span>
          <div>
            <h3>資料夾批次 AI 整理</h3>
            <p className="section-desc">
              指定後端資料夾路徑，把裡面所有文件（含子資料夾）AI 拆成原子筆記草稿，集中到下方「待審草稿」審核後發布。
              Windows 資料夾請用 /mnt/c/… 路徑。檔多會花較久（每檔一次 AI）。
            </p>
          </div>
        </div>
        <label className="field-label">資料夾路徑</label>
        <input
          className="input"
          placeholder="例如：/mnt/c/Users/Administrator/Desktop/公司文件"
          value={folderC}
          onChange={(e) => setFolderC(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCompileFolder()}
        />
        <button
          className="btn btn-primary"
          style={{ marginTop: 18 }}
          disabled={folderCBusy || !folderC.trim()}
          onClick={handleCompileFolder}
        >
          {folderCBusy && <span className="spinner" />}
          {folderCBusy ? "AI 整理中…（檔多會較久）" : "資料夾批次 AI 整理"}
        </button>
        {folderCErr && <div className="banner banner-err">⚠️ {folderCErr}</div>}
        {folderCMsg && <div className="banner banner-ok">✓ {folderCMsg}</div>}
      </div>

      {/* 待審草稿：檢視 / 編輯 / 發布 / 刪除 */}
      {drafts.length > 0 && (
        <div className="card admin-card" style={{ marginBottom: 24 }}>
          <div className="section-head">
            <span className="section-icon" style={{ background: "#fffbe6", color: "#b45309" }}>
              📝
            </span>
            <div>
              <h3>待審草稿（{drafts.length}）</h3>
              <p className="section-desc">
                確認內容正確（尤其 ⚠ 標註處），可直接編輯，再發布到知識庫。發布後即可被問答引用。
              </p>
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 6 }}>
            <button
              className="btn btn-primary"
              style={{ padding: "9px 18px", fontSize: 14 }}
              disabled={allBusy || rowBusy !== ""}
              onClick={handlePublishAll}
            >
              {allBusy && <span className="spinner" />}
              {allBusy ? "全部發布中…" : `✓ 全部發布（${drafts.length}）`}
            </button>
          </div>
          <input
            className="input"
            placeholder="🔍 搜尋草稿…"
            value={draftSearch}
            onChange={(e) => setDraftSearch(e.target.value)}
            style={{ marginTop: 12, marginBottom: 4 }}
          />
          <div style={{ maxHeight: 520, overflowY: "auto", marginTop: 8 }}>
          {draftFiltered.length === 0 ? (
            <div className="muted" style={{ padding: "12px 4px" }}>
              找不到符合「{draftSearch}」的草稿。
            </div>
          ) : draftFiltered.map((d) => {
            const val = edited[d.name] ?? d.content;
            return (
              <div
                key={d.name}
                style={{ marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--border)" }}
              >
                <div style={{ fontWeight: 600, marginBottom: 8 }}>📄 {d.name}</div>
                <textarea
                  value={val}
                  onChange={(e) =>
                    setEdited((m) => ({ ...m, [d.name]: e.target.value }))
                  }
                  style={{
                    width: "100%",
                    minHeight: 180,
                    fontFamily: "ui-monospace, monospace",
                    fontSize: 13,
                    lineHeight: 1.6,
                    padding: 12,
                    borderRadius: 10,
                    border: "1px solid var(--border)",
                    resize: "vertical",
                    boxSizing: "border-box",
                  }}
                />
                <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
                  <button
                    className="btn btn-primary"
                    style={{ padding: "9px 18px", fontSize: 14 }}
                    disabled={rowBusy === d.name}
                    onClick={() => handlePublish(d.name, val)}
                  >
                    {rowBusy === d.name && <span className="spinner" />}
                    {rowBusy === d.name ? "處理中…" : "✓ 發布到知識庫"}
                  </button>
                  <button
                    className="btn btn-white"
                    style={{ padding: "9px 18px", fontSize: 14 }}
                    disabled={rowBusy === d.name}
                    onClick={() => handleDeleteDraft(d.name)}
                  >
                    🗑 刪除
                  </button>
                </div>
              </div>
            );
          })}
          </div>
        </div>
      )}

      {/* A. 設定資料夾路徑 */}
      <div className="card admin-card" style={{ marginBottom: 24 }}>
        <div className="section-head">
          <span className="section-icon" style={{ background: "#fff1e0", color: "#c2410c" }}>
            📁
          </span>
          <div>
            <h3>訓練資料夾</h3>
            <p className="section-desc">
              填後端機器上的資料夾完整路徑，會把裡面所有 PDF / .txt / .md（含子資料夾）建成索引。
              這是「增量同步」：只重建有變動的檔、沒變的略過、已刪除的移除——之後再按一次即可更新。
            </p>
          </div>
        </div>
        <label className="field-label">資料夾路徑</label>
        <input
          className="input"
          placeholder="例如：/home/hermes/company_docs"
          value={folder}
          onChange={(e) => setFolder(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSync()}
        />
        <button
          className="btn btn-primary"
          style={{ marginTop: 18 }}
          disabled={folderBusy || !folder.trim()}
          onClick={handleSync}
        >
          {folderBusy && <span className="spinner" />}
          {folderBusy ? "同步中…" : "同步資料夾"}
        </button>
        {folderErr && <div className="banner banner-err">⚠️ {folderErr}</div>}
        {folderMsg && <div className="banner banner-ok">✓ {folderMsg}</div>}
      </div>

      {/* B. 上傳檔案 */}
      <div className="card admin-card">
        <div className="section-head">
          <span className="section-icon" style={{ background: "#f1f0ff", color: "#635bff" }}>
            ⬆️
          </span>
          <div>
            <h3>上傳檔案訓練</h3>
            <p className="section-desc">
              選一個檔案（PDF 或純文字 .txt / .md）上傳，立即切塊建索引加入知識庫，以原檔名作為來源標籤。
            </p>
          </div>
        </div>

        <div
          className={`dropzone${dragging ? " drag" : ""}${file ? " has-file" : ""}`}
          onClick={() => fileInput.current?.click()}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <span className="dz-icon">{file ? "📄" : "⬆️"}</span>
          <span className="dz-main">{file ? file.name : "點此選擇檔案，或拖放到這裡"}</span>
          <span className="dz-sub">
            {file
              ? `${(file.size / 1024).toFixed(1)} KB · 點擊可重新選擇`
              : "支援 PDF / .txt / .md"}
          </span>
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.txt,.md,.markdown"
            style={{ display: "none" }}
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </div>

        <button
          className="btn btn-primary"
          style={{ marginTop: 18 }}
          disabled={uploadBusy || !file}
          onClick={handleUpload}
        >
          {uploadBusy && <span className="spinner" />}
          {uploadBusy ? "建索引中…" : "上傳並建索引"}
        </button>
        {uploadErr && <div className="banner banner-err">⚠️ {uploadErr}</div>}
        {uploadMsg && <div className="banner banner-ok">✓ {uploadMsg}</div>}
      </div>
    </div>
  );
}
