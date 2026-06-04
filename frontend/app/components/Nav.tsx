"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS = [
  { href: "/single", label: "單一 Agent" },
  { href: "/chat", label: "多 Agent 對話" },
  { href: "/admin", label: "知識庫後台" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="nav">
      <div className="container nav-inner">
        <Link href="/" className="brand">
          <span className="brand-dot" />
          <span className="brand-text">ERP AI 助理</span>
        </Link>
        <div className="nav-links">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`nav-link${pathname === l.href ? " active" : ""}`}
            >
              {l.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
