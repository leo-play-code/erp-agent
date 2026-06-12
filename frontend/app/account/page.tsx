"use client";

import { useState } from "react";
import { changePassword, getUser } from "@/lib/api";

// 個人帳號：修改登入密碼（本地帳密帳號用）。
export default function AccountPage() {
  const user = getUser();
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [newPw2, setNewPw2] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(""); setMsg("");
    if (newPw !== newPw2) { setErr("兩次新密碼不一致"); return; }
    if (newPw.length < 6) { setErr("新密碼至少 6 個字元"); return; }
    setBusy(true);
    try {
      await changePassword(oldPw, newPw);
      setMsg("密碼已更新 ✓");
      setOldPw(""); setNewPw(""); setNewPw2("");
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div className="container" style={{ padding: "32px 24px", maxWidth: 420 }}>
      <h2>個人帳號</h2>
      <p className="muted" style={{ fontSize: 14, marginBottom: 16 }}>{user?.email}</p>
      <form onSubmit={submit} style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <input type="password" placeholder="目前密碼" value={oldPw} autoComplete="current-password"
          onChange={(e) => setOldPw(e.target.value)} style={{ padding: 10, borderRadius: 10, border: "1px solid var(--border)" }} />
        <input type="password" placeholder="新密碼（至少 6 字）" value={newPw} autoComplete="new-password"
          onChange={(e) => setNewPw(e.target.value)} style={{ padding: 10, borderRadius: 10, border: "1px solid var(--border)" }} />
        <input type="password" placeholder="再次輸入新密碼" value={newPw2} autoComplete="new-password"
          onChange={(e) => setNewPw2(e.target.value)} style={{ padding: 10, borderRadius: 10, border: "1px solid var(--border)" }} />
        <button disabled={busy || !oldPw || !newPw} style={{ padding: 10, borderRadius: 10, border: "none", background: "#2d6cdf", color: "#fff", fontWeight: 600, cursor: "pointer" }}>
          {busy ? "更新中…" : "修改密碼"}
        </button>
        {msg && <p style={{ color: "#1a9d5a", fontSize: 13 }}>{msg}</p>}
        {err && <p style={{ color: "#c0392b", fontSize: 13 }}>{err}</p>}
      </form>
      <p className="muted" style={{ fontSize: 12, marginTop: 16 }}>
        （用 Google 或公司信箱/AD 登入的帳號請在原本的服務改密碼,此頁僅適用本地帳密帳號。）
      </p>
    </div>
  );
}
