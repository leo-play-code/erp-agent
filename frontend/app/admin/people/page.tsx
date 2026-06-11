"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  adminListUsers,
  adminSetRole,
  adminSetDeveloper,
  adminCreateUser,
  getUser,
  type CompanyUser,
} from "@/lib/api";

// 公司人員管理（限 company_admin）：調整角色、授予/收回開發者席次（顯示 x/上限）。
export default function PeopleAdminPage() {
  const router = useRouter();
  const [users, setUsers] = useState<CompanyUser[]>([]);
  const [quota, setQuota] = useState(0);
  const [used, setUsed] = useState(0);
  const [err, setErr] = useState("");
  const [allowed, setAllowed] = useState(true);

  const load = async () => {
    try {
      const d = await adminListUsers();
      setUsers(d.users);
      setQuota(d.dev_quota);
      setUsed(d.dev_used);
      setErr("");
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  useEffect(() => {
    if (getUser()?.role !== "company_admin") {
      setAllowed(false);
      return;
    }
    load();
  }, []);

  if (!allowed) {
    return (
      <div className="container" style={{ padding: 40 }}>
        <h2>員工管理</h2>
        <p className="muted">需要公司管理員權限。</p>
        <button onClick={() => router.push("/chat")} style={{ marginTop: 12 }}>
          回到對話
        </button>
      </div>
    );
  }

  const setRole = async (sub: string, role: string) => {
    try { await adminSetRole(sub, role); await load(); }
    catch (e) { alert((e as Error).message); }
  };
  const setDev = async (sub: string, on: boolean) => {
    try { await adminSetDeveloper(sub, on); await load(); }
    catch (e) { alert((e as Error).message); }
  };

  const atCap = used >= quota;

  return (
    <div className="container" style={{ padding: "32px 24px", maxWidth: 880 }}>
      <h2>員工管理</h2>
      <CreateEmployee onCreated={load} />

      <p className="muted" style={{ marginBottom: 16 }}>
        開發者席次：{used} / {quota}
        {atCap && <span style={{ color: "#c0392b", marginLeft: 8 }}>（已額滿）</span>}
      </p>
      {err && <p style={{ color: "#c0392b" }}>{err}</p>}
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
        <thead>
          <tr style={{ textAlign: "left", borderBottom: "1px solid var(--border)" }}>
            <th style={{ padding: "8px 6px" }}>姓名</th>
            <th style={{ padding: "8px 6px" }}>Email</th>
            <th style={{ padding: "8px 6px" }}>角色</th>
            <th style={{ padding: "8px 6px" }}>開發者 Agent</th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.sub} style={{ borderBottom: "1px solid var(--border)" }}>
              <td style={{ padding: "8px 6px" }}>{u.name || "—"}</td>
              <td style={{ padding: "8px 6px" }}>{u.email}</td>
              <td style={{ padding: "8px 6px" }}>
                <select value={u.role} onChange={(e) => setRole(u.sub, e.target.value)}>
                  <option value="employee">員工</option>
                  <option value="company_admin">管理員</option>
                </select>
              </td>
              <td style={{ padding: "8px 6px" }}>
                <label style={{ display: "inline-flex", alignItems: "center", gap: 6, cursor: "pointer" }}>
                  <input
                    type="checkbox"
                    checked={u.developer}
                    disabled={!u.developer && atCap}
                    onChange={(e) => setDev(u.sub, e.target.checked)}
                  />
                  {u.developer ? "已開通" : "未開通"}
                </label>
              </td>
            </tr>
          ))}
          {users.length === 0 && (
            <tr><td colSpan={4} className="muted" style={{ padding: 16 }}>尚無人員資料（員工首次登入後會出現）。</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

// 管理員建員工帳號：填密碼＝本地帳密登入；留空＝IMAP/LDAP 允許名單（員工用公司帳密登入）。
function CreateEmployee({ onCreated }: { onCreated: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true); setMsg("");
    try {
      await adminCreateUser(email, name, password, "employee");
      setEmail(""); setName(""); setPassword("");
      setMsg("已建立 ✓");
      onCreated();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center", margin: "12px 0 20px" }}>
      <input placeholder="員工 email（須同公司網域）" value={email} onChange={(e) => setEmail(e.target.value)} style={{ padding: 8, minWidth: 220 }} />
      <input placeholder="姓名" value={name} onChange={(e) => setName(e.target.value)} style={{ padding: 8, width: 120 }} />
      <input placeholder="密碼（留空＝用公司信箱/AD登入）" value={password} onChange={(e) => setPassword(e.target.value)} style={{ padding: 8, minWidth: 200 }} />
      <button disabled={busy || !email}>{busy ? "建立中…" : "新增員工"}</button>
      {msg && <span className="muted" style={{ fontSize: 13 }}>{msg}</span>}
    </form>
  );
}
