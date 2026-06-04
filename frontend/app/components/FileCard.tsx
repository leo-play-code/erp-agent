"use client";

import type { FileLink } from "@/lib/api";

// 依副檔名決定圖示與配色（ChatGPT/Claude 式檔案卡片）
const STYLE: Record<string, { emoji: string; bg: string }> = {
  pdf: { emoji: "📕", bg: "#e5484d" },
  pptx: { emoji: "📊", bg: "#ff7a00" },
  ppt: { emoji: "📊", bg: "#ff7a00" },
  html: { emoji: "🔍", bg: "#0a85ff" },
  htm: { emoji: "🔍", bg: "#0a85ff" },
};
const DEFAULT_STYLE = { emoji: "📄", bg: "#635bff" };

// 一張乾淨的下載/預覽卡片：左圖示方塊 + 名稱/類型 + 右箭頭。
export default function FileCard({ link, name }: { link: FileLink; name?: string }) {
  const s = STYLE[link.ext] ?? DEFAULT_STYLE;
  const title = name?.trim() || (link.download ? "下載簡報" : "開啟預覽");
  const sub = `${(link.ext || "檔案").toUpperCase()} · ${
    link.download ? "點擊下載" : "在新分頁開啟"
  }`;
  return (
    <a
      className="file-card"
      href={link.url}
      {...(link.download
        ? { download: true }
        : { target: "_blank", rel: "noopener noreferrer" })}
    >
      <span className="file-card-icon" style={{ background: s.bg }}>
        {s.emoji}
      </span>
      <span className="file-card-body">
        <span className="file-card-name">{title}</span>
        <span className="file-card-sub">{sub}</span>
      </span>
      <span className="file-card-arrow">{link.download ? "↓" : "↗"}</span>
    </a>
  );
}
