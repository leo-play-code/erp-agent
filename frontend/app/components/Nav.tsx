"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getUser, logout, type AuthUser } from "@/lib/api";

const LINKS = [
  { href: "/single", label: "單一 Agent" },
  { href: "/chat", label: "多 Agent 對話" },
  { href: "/admin", label: "知識庫後台" },
];

export default function Nav() {
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null>(null);

  // localStorage 只能在 client 讀；mount 後再讀，避免 hydration 不一致。
  useEffect(() => setUser(getUser()), [pathname]);

  if (pathname === "/login") return null; // 登入頁不顯示導覽列

  return (
    <nav className="nav">
      <div className="container nav-inner">
        <Link href="/" className="brand">
          <span className="brand-dot" />
          <span className="brand-text">ERP AI 助理</span>
        </Link>
        <div className="nav-links" style={{ alignItems: "center", gap: 14 }}>
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`nav-link${pathname === l.href ? " active" : ""}`}
            >
              {l.label}
            </Link>
          ))}
          {user && (
            <>
              <span
                className="muted"
                style={{ fontSize: 13, maxWidth: 160, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                title={user.email}
              >
                {user.name || user.email}
              </span>
              <button
                onClick={logout}
                style={{ border: "1px solid var(--border)", borderRadius: 8, padding: "4px 10px", background: "transparent", cursor: "pointer", fontSize: 13 }}
              >
                登出
              </button>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
