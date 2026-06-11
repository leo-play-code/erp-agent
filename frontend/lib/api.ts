// 後端走「同源相對路徑」：前端只呼叫 /api/... 與 /files/...，由 Next 的 rewrites
// 代理到 FastAPI(8000)。如此不論用 localhost、區網 IP 或 Cloudflare 臨時網址，
// 都只需單一來源(3005)即可，瀏覽器永遠打自己這個網域，不會打錯主機或 port。
// 若後端在別處，仍可用 NEXT_PUBLIC_API_URL 覆蓋成完整網址。
const BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

// ── 登入 token：存 localStorage，每個 API 自動帶上 Authorization ───────────
export function getToken(): string | null {
  return typeof window !== "undefined" ? localStorage.getItem("erp_token") : null;
}
export type AuthUser = {
  email: string;
  name: string;
  role?: string; // company_admin | employee
  developer?: boolean; // 是否擁有開發者席次（顯示「開發者 Agent」分頁）
};
export function getUser(): AuthUser | null {
  if (typeof window === "undefined") return null;
  const s = localStorage.getItem("erp_user");
  return s ? (JSON.parse(s) as AuthUser) : null;
}
export function logout() {
  localStorage.removeItem("erp_token");
  localStorage.removeItem("erp_user");
  if (typeof window !== "undefined") location.href = "/login";
}

// 所有 API 都走這個：帶上 token；遇 401（未登入/過期）清掉並導回登入頁。
async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const t = getToken();
  const headers = { ...(init.headers || {}), ...(t ? { Authorization: `Bearer ${t}` } : {}) };
  const res = await globalThis.fetch(input, { ...init, headers });
  if (res.status === 401 && typeof window !== "undefined" && location.pathname !== "/login") {
    logout();
  }
  return res;
}

export type AuthConfig = {
  auth_enabled: boolean;
  google_client_id: string;
  modes?: string[];
  google_login?: boolean;
  password_login?: boolean;
};
export async function getAuthConfig(): Promise<AuthConfig> {
  try {
    const res = await globalThis.fetch(`${BASE}/api/auth/config`);
    return res.ok ? res.json() : { auth_enabled: false, google_client_id: "" };
  } catch {
    return { auth_enabled: false, google_client_id: "" };
  }
}

// 修改自己的密碼（僅本地帳密帳號）。
export async function changePassword(oldPassword: string, newPassword: string): Promise<void> {
  const form = new FormData();
  form.append("old_password", oldPassword);
  form.append("new_password", newPassword);
  const res = await apiFetch(`${BASE}/api/auth/change-password`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "修改密碼失敗"));
}

// 帳密登入（模式 A 本地 / B IMAP・LDAP）。成功後存 token+user，行為同 loginWithGoogle。
export async function loginWithPassword(email: string, password: string): Promise<AuthUser> {
  const form = new FormData();
  form.append("email", email);
  form.append("password", password);
  const res = await globalThis.fetch(`${BASE}/api/auth/login`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "登入失敗"));
  const data = await res.json();
  localStorage.setItem("erp_token", data.token);
  localStorage.setItem("erp_user", JSON.stringify(data.user));
  return data.user as AuthUser;
}

// Google ID token → 自家 JWT；存起來（首次登入即註冊）。
export async function loginWithGoogle(credential: string): Promise<AuthUser> {
  const form = new FormData();
  form.append("credential", credential);
  const res = await globalThis.fetch(`${BASE}/api/auth/google`, { method: "POST", body: form });
  if (!res.ok) throw new Error("登入失敗，請重試");
  const data = await res.json();
  localStorage.setItem("erp_token", data.token);
  localStorage.setItem("erp_user", JSON.stringify(data.user));
  return data.user as AuthUser;
}

export type FileLink = {
  url: string; // 可直接點的絕對網址
  download: boolean; // true=下載（如 .pdf/.pptx）；false=在新分頁開啟（如 .html）
  ext: string; // 副檔名（小寫，如 pdf / pptx / html）；給檔案卡片決定圖示與配色
};

// 從 agent 回覆中找出 /files/... 連結，並依副檔名決定要「下載」還是「開啟預覽」。
// .html 用開啟，其餘（簡報 .pdf/.pptx 等）用下載；找不到回 null。
export function extractFileLink(text: string): FileLink | null {
  const m = text.match(/\/files\/[A-Za-z0-9._-]+/);
  if (!m) return null;
  const ext = (m[0].split(".").pop() || "").toLowerCase();
  const isHtml = /^html?$/.test(ext);
  return { url: `${BASE}${m[0]}`, download: !isHtml, ext };
}

export type AgentInfo = {
  name: string;
  desc: string;
  accepts_file: boolean;
  needs_text: boolean;
};

export type ChatMessage = {
  agent: string | null; // 哪個 Agent 產出（使用者訊息為 null）
  role: string; // "human" | "ai"
  content: string;
};

export async function listAgents(): Promise<AgentInfo[]> {
  const res = await apiFetch(`${BASE}/api/agents`);
  if (!res.ok) throw new Error("無法取得 Agent 清單");
  return res.json();
}

export type PptTemplate = {
  key: string; // Presenton template 名稱（如 modern）
  zh: string; // 中文名
};

export async function listPptTemplates(): Promise<PptTemplate[]> {
  const res = await apiFetch(`${BASE}/api/ppt/templates`);
  if (!res.ok) throw new Error("無法取得 Presenton template 清單");
  return res.json();
}

// ppt-workflow 的可選參數（對象/風格/篇幅/語氣），給單一 agent 頁做成按鈕。
export type PptOption = { key: string; zh: string };
export type PptOptions = {
  groups: Record<string, PptOption[]>; // audience / style / pages / tone
  labels: Record<string, string>; // 各組的中文標題
};

export async function listPptOptions(): Promise<PptOptions> {
  const res = await apiFetch(`${BASE}/api/ppt/options`);
  if (!res.ok) throw new Error("無法取得簡報選項");
  return res.json();
}

export async function runAgent(
  name: string,
  message: string,
  file: File | null
): Promise<string> {
  const form = new FormData();
  form.append("name", name);
  form.append("message", message);
  if (file) form.append("file", file);
  const res = await apiFetch(`${BASE}/api/agent`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.text()) || "執行失敗");
  return (await res.json()).reply;
}

export async function sendChat(
  message: string,
  sessionId: string,
  file: File | null
): Promise<ChatMessage[]> {
  const form = new FormData();
  form.append("message", message);
  form.append("session_id", sessionId);
  if (file) form.append("file", file);
  const res = await apiFetch(`${BASE}/api/chat`, { method: "POST", body: form });
  if (!res.ok) throw new Error((await res.text()) || "執行失敗");
  return (await res.json()).messages;
}

// ── 後台知識庫管理（RAG 訓練）────────────────────────────────────────
// 前端 RAG 只做問答；建索引/訓練走這幾支後台 API（後端直接呼叫 rag 工具，不經 LLM）。

export type KbSource = { name: string; segments: number };
export type KbSummary = {
  total_segments: number;
  source_count: number;
  sources: KbSource[];
};

// 取出後端錯誤訊息：FastAPI 的 HTTPException 回 {"detail": "..."}，優先用它。
async function errText(res: Response, fallback: string): Promise<string> {
  const raw = await res.text().catch(() => "");
  try {
    return JSON.parse(raw).detail || fallback;
  } catch {
    return raw || fallback;
  }
}

export async function ragStats(): Promise<KbSummary> {
  const res = await apiFetch(`${BASE}/api/rag/stats`);
  if (!res.ok) throw new Error("無法取得知識庫現況");
  return res.json();
}

export async function ragSyncFolder(folderPath: string): Promise<string> {
  const form = new FormData();
  form.append("folder_path", folderPath);
  const res = await apiFetch(`${BASE}/api/rag/sync`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "同步資料夾失敗"));
  return (await res.json()).text;
}

export async function ragUpload(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`${BASE}/api/rag/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "上傳建索引失敗"));
  return (await res.json()).text;
}

// ── 知識庫 vault 流程：上傳 → AI 編譯草稿 → 審核 → 發布 ────────────────
export type WikiDraft = { name: string; content: string };

// 上傳檔案 → 後端存進 raw/ 並用 LLM 編譯成原子筆記草稿（進 .drafts/），回傳產生的草稿檔名。
export async function wikiUpload(
  file: File
): Promise<{ drafts: string[]; text: string }> {
  const form = new FormData();
  form.append("file", file);
  const res = await apiFetch(`${BASE}/api/wiki/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "上傳/編譯失敗"));
  return res.json();
}

// 指定資料夾 → 把裡面所有文件批次 AI 編譯成草稿（進 .drafts/ 待審）。
export async function wikiCompileFolder(
  folderPath: string
): Promise<{ files: number; drafts: number; text: string }> {
  const form = new FormData();
  form.append("folder_path", folderPath);
  const res = await apiFetch(`${BASE}/api/wiki/compile-folder`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "資料夾編譯失敗"));
  return res.json();
}

// 取得目前所有待審草稿（檔名 + 內容）。
export async function wikiDrafts(): Promise<WikiDraft[]> {
  const res = await apiFetch(`${BASE}/api/wiki/drafts`);
  if (!res.ok) throw new Error("無法取得草稿清單");
  return res.json();
}

// 刪除一篇草稿。
export async function wikiDeleteDraft(name: string): Promise<string> {
  const form = new FormData();
  form.append("name", name);
  const res = await apiFetch(`${BASE}/api/wiki/draft/delete`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "刪除草稿失敗"));
  return (await res.json()).text;
}

// 發布草稿（帶最後編輯內容）到 wiki/ 並重新索引。
export async function wikiPublish(name: string, content: string): Promise<string> {
  const form = new FormData();
  form.append("name", name);
  form.append("content", content);
  const res = await apiFetch(`${BASE}/api/wiki/publish`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "發布失敗"));
  return (await res.json()).text;
}

// 一次發布多篇草稿（帶各自當前內容），後端寫入 wiki/ 後只重新索引一次。
export async function wikiPublishAll(items: WikiDraft[]): Promise<string> {
  const form = new FormData();
  form.append("payload", JSON.stringify(items));
  const res = await apiFetch(`${BASE}/api/wiki/publish-all`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "全部發布失敗"));
  return (await res.json()).text;
}

// ── 後台：公司人員管理（RBAC，限 company_admin）────────────────────────
export type CompanyUser = {
  sub: string;
  email: string;
  name: string;
  role: string; // company_admin | employee
  developer: boolean;
};
export type AdminUsers = { users: CompanyUser[]; dev_quota: number; dev_used: number };

export async function adminListUsers(): Promise<AdminUsers> {
  const res = await apiFetch(`${BASE}/api/admin/users`);
  if (!res.ok) throw new Error(await errText(res, "無法取得人員清單"));
  return res.json();
}

export async function adminCreateUser(
  email: string, name: string, password: string, role = "employee"
): Promise<CompanyUser> {
  const form = new FormData();
  form.append("email", email);
  form.append("name", name);
  if (password) form.append("password", password);
  form.append("role", role);
  const res = await apiFetch(`${BASE}/api/admin/users`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "建立員工失敗"));
  return res.json();
}

export async function adminSetAuthMethod(method: string, config?: object): Promise<void> {
  const form = new FormData();
  form.append("method", method);
  if (config) form.append("config", JSON.stringify(config));
  const res = await apiFetch(`${BASE}/api/admin/auth-method`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "設定登入方式失敗"));
}

export async function adminSetRole(sub: string, role: string): Promise<CompanyUser> {
  const form = new FormData();
  form.append("role", role);
  const res = await apiFetch(`${BASE}/api/admin/users/${encodeURIComponent(sub)}/role`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "設定角色失敗"));
  return res.json();
}

export async function adminSetDeveloper(sub: string, on: boolean): Promise<CompanyUser> {
  const form = new FormData();
  form.append("on", String(on));
  const res = await apiFetch(`${BASE}/api/admin/users/${encodeURIComponent(sub)}/developer`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "設定開發者席次失敗"));
  return res.json();
}

// ── 公司站內信箱 ──────────────────────────────────────────────────────
export type MailMessage = {
  id: number;
  subject: string;
  body: string;
  kind: string; // message | announcement
  sender_sub: string | null;
  sender_name: string | null;
  sender_email: string | null;
  recipient_id: number;
  read_at: string | null;
  created_at: string;
};
export type Notification = {
  id: number;
  kind: string;
  title: string;
  body: string;
  link: string;
  read_at: string | null;
  created_at: string;
};

export async function mailboxInbox(): Promise<MailMessage[]> {
  const res = await apiFetch(`${BASE}/api/mailbox/inbox`);
  if (!res.ok) throw new Error("無法取得信箱");
  return (await res.json()).messages;
}

export async function mailboxSend(recipients: string[], subject: string, body: string): Promise<void> {
  const form = new FormData();
  form.append("recipients", JSON.stringify(recipients));
  form.append("subject", subject);
  form.append("body", body);
  const res = await apiFetch(`${BASE}/api/mailbox/send`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "寄信失敗"));
}

export async function mailboxMarkRead(recipientId: number): Promise<void> {
  const form = new FormData();
  form.append("recipient_id", String(recipientId));
  await apiFetch(`${BASE}/api/mailbox/mark-read`, { method: "POST", body: form });
}

export async function mailboxAnnounce(subject: string, body: string): Promise<void> {
  const form = new FormData();
  form.append("subject", subject);
  form.append("body", body);
  const res = await apiFetch(`${BASE}/api/mailbox/announcement`, { method: "POST", body: form });
  if (!res.ok) throw new Error(await errText(res, "發布公告失敗"));
}

export async function mailboxNotifications(): Promise<Notification[]> {
  const res = await apiFetch(`${BASE}/api/mailbox/notifications`);
  if (!res.ok) throw new Error("無法取得通知");
  return (await res.json()).notifications;
}

export async function mailboxMarkNotificationsRead(notifId?: number): Promise<void> {
  const form = new FormData();
  if (notifId != null) form.append("notif_id", String(notifId));
  await apiFetch(`${BASE}/api/mailbox/notifications/mark-read`, { method: "POST", body: form });
}

// 串流事件：supervisor 派 Agent(status)、某 Agent 的產出(message)、結束(done)、錯誤(error)
export type ChatStreamEvent =
  | { type: "status"; agent: string }
  | { type: "message"; agent: string; content: string }
  | { type: "action"; action: string } // 例：open_dev_agent → 前端切到開發者分頁
  | { type: "done" }
  | { type: "error"; detail: string };

// 串流版多 Agent 對話：邊跑邊把事件丟給 onEvent。用 POST + 讀 response stream
// （瀏覽器 EventSource 只支援 GET，無法帶上傳檔，故自己讀 NDJSON）。
// opts.history：編輯/重跑分支時，把該點之前的對話當脈絡種子送給後端（不重跑舊回合）。
// opts.signal：用 AbortController 隨時終止串流。
export async function streamChat(
  message: string,
  sessionId: string,
  file: File | null,
  onEvent: (ev: ChatStreamEvent) => void,
  opts?: { history?: ChatMessage[]; signal?: AbortSignal }
): Promise<void> {
  const form = new FormData();
  form.append("message", message);
  form.append("session_id", sessionId);
  if (file) form.append("file", file);
  if (opts?.history?.length) form.append("history", JSON.stringify(opts.history));
  const res = await apiFetch(`${BASE}/api/chat/stream`, {
    method: "POST",
    body: form,
    signal: opts?.signal,
  });
  if (!res.ok || !res.body) {
    throw new Error((await res.text().catch(() => "")) || "執行失敗");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  const flush = (line: string) => {
    const s = line.trim();
    if (s) onEvent(JSON.parse(s) as ChatStreamEvent);
  };
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      flush(buf.slice(0, nl));
      buf = buf.slice(nl + 1);
    }
  }
  flush(buf); // 收尾最後一行（若無換行結尾）
}
