"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { getAuthConfig, getToken, loginWithGoogle } from "@/lib/api";

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
      if (!cfg.google_client_id) {
        setNotReady("後端尚未設定 GOOGLE_CLIENT_ID，無法使用 Google 登入。");
        return;
      }
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
          用 Google 帳號登入，建立你自己的專屬工作區（首次登入即註冊）。
        </p>

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
