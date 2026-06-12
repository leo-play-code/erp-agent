"use client";

import { useEffect, useState } from "react";
import {
  mailboxInbox,
  mailboxSend,
  mailboxMarkRead,
  mailboxAnnounce,
  mailboxNotifications,
  mailboxMarkNotificationsRead,
  getUser,
  type MailMessage,
  type Notification,
} from "@/lib/api";

// 公司站內信箱：收件匣（員工間訊息 + 公告）、系統通知，管理員可發公司公告。
export default function MailboxPage() {
  const [tab, setTab] = useState<"inbox" | "notifications">("inbox");
  const [messages, setMessages] = useState<MailMessage[]>([]);
  const [notifs, setNotifs] = useState<Notification[]>([]);
  const [composing, setComposing] = useState(false);
  const [announcing, setAnnouncing] = useState(false);
  const isAdmin = getUser()?.role === "company_admin";

  const load = async () => {
    try {
      setMessages(await mailboxInbox());
      setNotifs(await mailboxNotifications());
    } catch { /* 後端/DB 未就緒時略過 */ }
  };
  useEffect(() => { load(); }, []);

  const openMessage = async (m: MailMessage) => {
    if (!m.read_at) { await mailboxMarkRead(m.recipient_id); await load(); }
  };
  const markAllNotifs = async () => { await mailboxMarkNotificationsRead(); await load(); };

  return (
    <div className="container" style={{ padding: "32px 24px", maxWidth: 860 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>公司信箱</h2>
        <div style={{ display: "flex", gap: 8 }}>
          <button className={tab === "inbox" ? "active" : ""} onClick={() => setTab("inbox")}>收件匣</button>
          <button className={tab === "notifications" ? "active" : ""} onClick={() => setTab("notifications")}>
            通知{notifs.some((n) => !n.read_at) ? " ●" : ""}
          </button>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <button onClick={() => setComposing(true)}>寫信</button>
          {isAdmin && <button onClick={() => setAnnouncing(true)}>發公告</button>}
        </div>
      </div>

      {tab === "inbox" && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {messages.map((m) => (
            <li
              key={m.recipient_id}
              onClick={() => openMessage(m)}
              style={{ padding: "12px 10px", borderBottom: "1px solid var(--border)", cursor: "pointer", background: m.read_at ? "transparent" : "rgba(0,120,255,0.06)" }}
            >
              <div style={{ display: "flex", justifyContent: "space-between" }}>
                <strong>
                  {m.kind === "announcement" && <span style={{ color: "#c0392b", marginRight: 6 }}>[公告]</span>}
                  {m.subject || "(無主旨)"}
                </strong>
                <span className="muted" style={{ fontSize: 12 }}>{new Date(m.created_at).toLocaleString()}</span>
              </div>
              <div className="muted" style={{ fontSize: 13 }}>寄件：{m.sender_name || m.sender_email || "系統"}</div>
              <div style={{ whiteSpace: "pre-wrap", marginTop: 4 }}>{m.body}</div>
            </li>
          ))}
          {messages.length === 0 && <li className="muted" style={{ padding: 16 }}>沒有信件。</li>}
        </ul>
      )}

      {tab === "notifications" && (
        <>
          {notifs.some((n) => !n.read_at) && (
            <button onClick={markAllNotifs} style={{ marginBottom: 12 }}>全部標為已讀</button>
          )}
          <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {notifs.map((n) => (
              <li key={n.id} style={{ padding: "10px", borderBottom: "1px solid var(--border)", background: n.read_at ? "transparent" : "rgba(0,120,255,0.06)" }}>
                <div style={{ display: "flex", justifyContent: "space-between" }}>
                  <strong>{n.title}</strong>
                  <span className="muted" style={{ fontSize: 12 }}>{new Date(n.created_at).toLocaleString()}</span>
                </div>
                {n.body && <div className="muted" style={{ fontSize: 13 }}>{n.body}</div>}
              </li>
            ))}
            {notifs.length === 0 && <li className="muted" style={{ padding: 16 }}>沒有通知。</li>}
          </ul>
        </>
      )}

      {composing && <ComposeModal announce={false} onClose={() => setComposing(false)} onSent={load} />}
      {announcing && <ComposeModal announce onClose={() => setAnnouncing(false)} onSent={load} />}
    </div>
  );
}

// 寫信 / 發公告共用對話框。announce=true 時不需收件者（fan-out 全公司，限管理員）。
function ComposeModal({ announce, onClose, onSent }: { announce: boolean; onClose: () => void; onSent: () => void }) {
  const [recipients, setRecipients] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  const submit = async () => {
    setBusy(true); setErr("");
    try {
      if (announce) {
        await mailboxAnnounce(subject, body);
      } else {
        const list = recipients.split(",").map((s) => s.trim()).filter(Boolean);
        await mailboxSend(list, subject, body);
      }
      onSent();
      onClose();
    } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <div onClick={onClose} style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}>
      <div onClick={(e) => e.stopPropagation()} style={{ background: "var(--bg, #fff)", padding: 24, borderRadius: 12, width: 480, maxWidth: "90vw" }}>
        <h3 style={{ marginTop: 0 }}>{announce ? "發布公司公告" : "寫站內信"}</h3>
        {!announce && (
          <input
            placeholder="收件者 email（逗號分隔，須為同公司成員）"
            value={recipients}
            onChange={(e) => setRecipients(e.target.value)}
            style={{ width: "100%", marginBottom: 8, padding: 8 }}
          />
        )}
        <input placeholder="主旨" value={subject} onChange={(e) => setSubject(e.target.value)} style={{ width: "100%", marginBottom: 8, padding: 8 }} />
        <textarea placeholder="內容" value={body} onChange={(e) => setBody(e.target.value)} rows={6} style={{ width: "100%", marginBottom: 8, padding: 8 }} />
        {err && <p style={{ color: "#c0392b" }}>{err}</p>}
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <button onClick={onClose}>取消</button>
          <button onClick={submit} disabled={busy || (!announce && !recipients.trim())}>
            {busy ? "送出中…" : announce ? "發布" : "寄出"}
          </button>
        </div>
      </div>
    </div>
  );
}
