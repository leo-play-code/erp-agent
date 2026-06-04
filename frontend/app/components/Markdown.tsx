"use client";

import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { extractFileLink } from "@/lib/api";
import FileCard from "./FileCard";

// 把 markdown 的 children 攤平成純文字（給檔案卡片當名稱用）。
function childText(children: React.ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(childText).join("");
  return "";
}

// 把 agent 回覆的 markdown 渲染成有層次的內容（標題/清單/圖片/表格/程式碼）。
// /files/... 連結會自動變成漂亮的「檔案卡片」；其餘外連結在新分頁開啟。
const components: Components = {
  a({ href, children }) {
    const link = href ? extractFileLink(href) : null;
    if (link) {
      return <FileCard link={link} name={childText(children)} />;
    }
    // 只有「真正的外部 http(s) 連結」才開新分頁；其餘（#、空、相對路徑等 LLM 亂編的假連結）
    // 一律當純文字，避免點了開回前端首頁、卻沒有任何下載。
    const isExternal = !!href && /^https?:\/\//i.test(href);
    if (!isExternal) {
      return <span>{children}</span>;
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer">
        {children}
      </a>
    );
  },
  img({ src, alt }) {
    let s = typeof src === "string" ? src : "";
    const fl = extractFileLink(s); // 若是 /files 圖片，補上後端絕對網址
    if (fl) s = fl.url;
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={s} alt={alt ?? ""} className="md-img" />;
  },
};

export default function Markdown({ content }: { content: string }) {
  return (
    <div className="md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
