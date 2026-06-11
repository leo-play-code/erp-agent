"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getAuthConfig, getToken, loginWithGoogle, loginWithPassword } from "@/lib/api";

// Google Identity Services 全域物件（由 gsi script 注入）
declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (cfg: Record<string, unknown>) => void;
          renderButton: (el: HTMLElement, opts: Record<string, unknown>) => void;
        };
      };
    };
  }
}

export default function LoginPage() {
  const btnRef = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const [error, setError] = useState("");
  const [notReady, setNotReady] = useState("");
  const [showGoogle, setShowGoogle] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);

  const submitPassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await loginWithPassword(email, password);
      router.replace("/");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (getToken()) {
      router.replace("/");
      return;
    }
    let script: HTMLScriptElement | null = null;
    getAuthConfig().then((cfg) => {
      if (!cfg.auth_enabled) {
        router.replace("/"); // 單人模式：不需登入
        return;
      }
      setShowPassword(!!cfg.password_login);
      if (!cfg.google_login || !cfg.google_client_id) {
        if (!cfg.password_login) {
          setNotReady("後端尚未設定任何登入方式。");
        }
        return; // 沒啟用 Google 就只走帳密表單
      }
      setShowGoogle(true);
      script = document.createElement("script");
      script.src = "https://accounts.google.com/gsi/client";
      script.async = true;
      script.defer = true;
      script.onload = () => {
        const g = window.google;
        if (!g) return;
        g.accounts.id.initialize({
          client_id: cfg.google_client_id,
          callback: async (resp: { credential: string }) => {
            try {
              await loginWithGoogle(resp.credential);
              router.replace("/");
            } catch (e) {
              setError((e as Error).message);
            }
          },
        });
        if (btnRef.current) {
          g.accounts.id.renderButton(btnRef.current, {
            theme: "outline",
            size: "large",
            text: "continue_with",
            shape: "pill",
            width: 280,
          });
        }
      };
      document.body.appendChild(script);
    });
    return () => {
      script?.remove();
    };
  }, [router]);

  return (
    <div
      style={{
        minHeight: "calc(100vh - 60px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 24,
      }}
    >
      <div
        style={{
          width: "100%",
          maxWidth: 380,
          background: "#fff",
          border: "1px solid var(--border)",
          borderRadius: 16,
          padding: "40px 32px",
          textAlign: "center",
          boxShadow: "0 8px 30px rgba(0,0,0,0.06)",
        }}
      >
        <div style={{ fontSize: 32 }}>🤖</div>
        <h1 style={{ fontSize: 22, fontWeight: 700, margin: "12px 0 6px" }}>
          ERP AI 助理
        </h1>
        <p className="muted" style={{ fontSize: 14, marginBottom: 28 }}>
          登入你的公司工作區（資料與他人隔離）。
        </p>

        {showPassword && (
          <form onSubmit={submitPassword} style={{ display: "flex", flexDirection: "column", gap: 10, textAlign: "left" }}>
            <input
              type="email" placeholder="公司 email" value={email} autoComplete="username"
              onChange={(e) => setEmail(e.target.value)}
              style={{ padding: "10px 12px", borderRadius: 10, border: "1px solid var(--border)" }}
            />
            <input
              type="password" placeholder="密碼" value={password} autoComplete="current-password"
              onChange={(e) => setPassword(e.target.value)}
              style={{ padding: "10px 12px", borderRadius: 10, border: "1px solid var(--border)" }}
            />
            <button
              type="submit" disabled={busy || !email || !password}
              style={{ padding: "10px 12px", borderRadius: 10, border: "none", background: "#2d6cdf", color: "#fff", fontWeight: 600, cursor: "pointer" }}
            >
              {busy ? "登入中…" : "登入"}
            </button>
          </form>
        )}

        {showPassword && showGoogle && (
          <div style={{ display: "flex", alignItems: "center", gap: 10, margin: "18px 0", color: "var(--muted)", fontSize: 12 }}>
            <span style={{ flex: 1, height: 1, background: "var(--border)" }} />或<span style={{ flex: 1, height: 1, background: "var(--border)" }} />
          </div>
        )}

        <div style={{ display: "flex", justifyContent: "center" }} ref={btnRef} />

        {notReady && (
          <p style={{ color: "#cd3d64", fontSize: 13, marginTop: 20 }}>⚠️ {notReady}</p>
        )}
        {error && (
          <p style={{ color: "#cd3d64", fontSize: 13, marginTop: 20 }}>⚠️ {error}</p>
        )}
        <p className="muted" style={{ fontSize: 12, marginTop: 28 }}>
          登入後，你的對話、知識庫（RAG）與產出檔案都是私人、與他人隔離的。
        </p>
      </div>
    </div>
  );
}
