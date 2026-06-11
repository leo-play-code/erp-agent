"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getToken, getUser } from "@/lib/api";

// 開發者 Agent 分頁：把 claude-frontend（受權限控管的 coding agent）以 iframe 嵌入。
// 進來前先做 SSO 握手——把 erp 的 JWT POST 給 /dev/api/auth/erp-sso，cf 驗證後種下
// cf_session cookie（同網域），之後 iframe 內所有請求（含 WebSocket 升級）自動帶 cookie。
// claude-frontend 由反向代理掛在 /dev（見部署設定）；本機未架代理時握手會失敗、顯示提示。
export default function DevAgentPage() {
  const router = useRouter();
  const [state, setState] = useState<"checking" | "ready" | "denied" | "error">("checking");
  const [errMsg, setErrMsg] = useState("");

  useEffect(() => {
    const user = getUser();
    if (!user?.developer) {
      setState("denied");
      return;
    }
    let active = true;
    (async () => {
      try {
        const res = await fetch("/dev/api/auth/erp-sso", {
          method: "POST",
          credentials: "include",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ token: getToken() }),
        });
        if (!active) return;
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          throw new Error(d.error || `SSO 失敗（HTTP ${res.status}）`);
        }
        setState("ready");
      } catch (e) {
        if (active) {
          setErrMsg((e as Error).message);
          setState("error");
        }
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  if (state === "denied") {
    return (
      <div className="container" style={{ padding: 40 }}>
        <h2>開發者 Agent</h2>
        <p className="muted">你目前沒有開發者席次，請洽公司管理員開通。</p>
        <button onClick={() => router.push("/chat")} style={{ marginTop: 12 }}>
          回到對話
        </button>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="container" style={{ padding: 40 }}>
        <h2>開發者 Agent</h2>
        <p className="muted">無法連上開發者工具：{errMsg}</p>
        <p className="muted" style={{ fontSize: 13 }}>
          （需透過反向代理把 claude-frontend 掛在 /dev；請確認部署設定。）
        </p>
      </div>
    );
  }

  if (state === "checking") {
    return (
      <div className="container" style={{ padding: 40 }}>
        <p className="muted">正在進入開發者工具…</p>
      </div>
    );
  }

  return (
    <iframe
      src="/dev/"
      title="開發者 Agent"
      style={{ width: "100%", height: "calc(100vh - 56px)", border: "none", display: "block" }}
    />
  );
}
