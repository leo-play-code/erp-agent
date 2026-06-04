"use client";

import { useEffect, useRef, useState } from "react";
import {
  ragStats,
  ragSyncFolder,
  ragUpload,
  type KbSummary,
} from "@/lib/api";

// 知識庫後台：設定要訓練的資料夾路徑、上傳檔案建索引。
// 前端的 RAG agent 只做問答，「訓練 / 建索引」集中在這一頁（呼叫後端 admin API）。
export default function AdminPage() {
  const [stats, setStats] = useState<KbSummary | null>(null);
  const [statsError, setStatsError] = useState("");

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

  function refreshStats() {
    ragStats()
      .then((s) => {
        setStats(s);
        setStatsError("");
      })
      .catch((e) => setStatsError(e.message));
  }
  useEffect(refreshStats, []);

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
              <div>
                {stats.sources.map((s) => (
                  <div className="kb-source" key={s.name}>
                    <span className="kb-source-icon">📄</span>
                    <span className="kb-source-name">{s.name}</span>
                    <span className="kb-pill">{s.segments} 段</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

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
