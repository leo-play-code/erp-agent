"""簡報（PPT）工具 —— 只走使用者自架的 Presenton（如 http://localhost:5000）。

設計（依使用者要求，2026-06-01 改）：
- 風格/版型完全由 **Presenton 的 template** 決定（general / modern / standard / swift…），
  由 list_ppt_templates 動態向 Presenton 查詢，**不再有任何內建寫死的風格**。
- Presenton 未設定或產生失敗時，**不再退回內建版型**，直接回報錯誤。

需要的環境變數：PRESENTON_URL、PRESENTON_USER / PRESENTON_PASSWORD；
選填 PRESENTON_RETRIES（失敗自動重試次數，預設 2）。
"""

import json
import os
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.tools import tool

load_dotenv()

# 產出的簡報放這裡；後端會把這個資料夾掛在 /files 供前端下載
GENERATED_DIR = Path(__file__).resolve().parent.parent / "generated"

# 輸出格式：用 PDF。Presenton 匯出 .pptx 會把標題/內文框算錯位置而「跑版」重疊；
# PDF 是用跟它網頁預覽「同一個引擎」渲染，所以跨出來跟預覽一模一樣、不會跑版。
# 要可編輯版的人，到 Presenton 網頁（localhost:5000）打開同一份簡報下載 pptx 即可。
EXPORT_AS = "pdf"

# Presenton 內建 template 沒有縮圖 API，補上友善中文名（查不到對應就用 key 本身）
_TEMPLATE_ZH = {
    "general": "通用",
    "modern": "現代",
    "standard": "標準",
    "swift": "簡潔",
}


# ── Presenton 串接 ─────────────────────────────────────────────────────
def _presenton_base():
    return os.getenv("PRESENTON_URL", "").strip().rstrip("/")


def _presenton_login(base):
    """登入 Presenton，回傳 session cookie 字串（presenton_session=…）；失敗回 None。"""
    user, pw = os.getenv("PRESENTON_USER"), os.getenv("PRESENTON_PASSWORD")
    if not user or not pw:
        return None
    try:
        req = urllib.request.Request(
            f"{base}/api/v1/auth/login",
            data=json.dumps({"username": user, "password": pw}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            for c in resp.headers.get_all("Set-Cookie") or []:
                if c.startswith("presenton_session="):
                    return c.split(";", 1)[0]
        return None
    except Exception:
        return None


def _fetch_templates(base, cookie):
    """查 Presenton 有哪些 template，回傳名稱清單；失敗回 None。"""
    try:
        req = urllib.request.Request(
            f"{base}/api/v1/ppt/template/all", headers={"Cookie": cookie}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        names = [t.get("name") or t.get("id") for t in data]
        return [n for n in names if n] or None
    except Exception:
        return None


def _slides_to_outline(slides):
    """把結構化 slides 攤平成文字大綱，餵給 Presenton 當製作依據。"""
    lines = []
    for s in slides:
        t = (s.get("type") or "content").lower()
        h = s.get("heading", "")
        if t == "section":
            lines.append(f"# {h}")
        elif t == "closing":
            lines.append(f"結尾：{h}")
        elif t == "two_column":
            left, right = s.get("left", {}), s.get("right", {})
            lines.append(
                f"{h}（左：{left.get('subheading', '')} "
                f"{' / '.join(left.get('bullets') or [])}；右："
                f"{right.get('subheading', '')} {' / '.join(right.get('bullets') or [])}）"
            )
        else:
            body = "；".join(s.get("bullets") or [])
            lines.append(f"{h}：{body}" if body else h)
    return "\n".join(lines)


def _presenton_generate(title, slides, subtitle, template):
    """呼叫 Presenton 產出可編輯 pptx，回傳 (檔名, 錯誤訊息)。成功時錯誤訊息為 None。"""
    base = _presenton_base()
    if not base:
        return None, "尚未設定 PRESENTON_URL（請在 .env 指定你架設的 Presenton 位址）"
    cookie = _presenton_login(base)
    if not cookie:
        return None, "登入 Presenton 失敗（請確認 PRESENTON_USER / PRESENTON_PASSWORD）"

    payload = {
        "content": f"{title}\n{subtitle}".strip(),
        "n_slides": max(len(slides), 3) + 1,
        "language": "Traditional Chinese",
        "template": template,
        "export_as": EXPORT_AS,
        "tone": "professional",
        "instructions": (
            "請以繁體中文製作，依照以下大綱組織內容：\n"
            + _slides_to_outline(slides)
        ),
    }
    try:
        req = urllib.request.Request(
            f"{base}/api/v1/ppt/presentation/generate",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Cookie": cookie},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=300) as resp:  # 生成可能要數十秒
            data = json.loads(resp.read())
        path = data.get("path")
        if not path:
            return None, "Presenton 回應沒有檔案路徑（可能產生失敗）"
        dl = urllib.request.Request(f"{base}{path}", headers={"Cookie": cookie})
        with urllib.request.urlopen(dl, timeout=120) as resp:
            content = resp.read()
        name = f"{uuid.uuid4().hex[:12]}.{EXPORT_AS}"
        GENERATED_DIR.mkdir(exist_ok=True)
        (GENERATED_DIR / name).write_bytes(content)
        return name, None
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            detail = ""
        return None, f"Presenton 伺服器錯誤（HTTP {e.code}）：{str(detail)[:240] or '無細節'}"
    except Exception as e:
        return None, f"Presenton 連線/處理失敗：{type(e).__name__}: {e}"


def template_cards():
    """給前端風格選擇器用：回傳 Presenton 目前可用的 template 清單；連不到回空陣列。"""
    base = _presenton_base()
    if not base:
        return []
    cookie = _presenton_login(base)
    if not cookie:
        return []
    names = _fetch_templates(base, cookie) or []
    return [{"key": n, "zh": _TEMPLATE_ZH.get(n, n)} for n in names]


# ── 工具 ───────────────────────────────────────────────────────────────
@tool
def list_ppt_templates() -> str:
    """列出你架設的 Presenton 目前可用的簡報 template（風格），回傳給使用者挑選。

    使用者尚未指定 template 時，先呼叫本工具，把可選的 template 列給使用者挑。本工具無參數。
    """
    cards = template_cards()
    if not cards:
        return (
            "無法取得 Presenton 的 template 清單：請確認 PRESENTON_URL 已設定、"
            "Presenton 服務有啟動、且 PRESENTON_USER / PRESENTON_PASSWORD 正確。"
        )
    opts = "、".join(f"{c['key']}（{c['zh']}）" for c in cards)
    return (
        f"你架設的 Presenton 目前可選這些 template：{opts}。\n"
        "請挑一個 template 名稱（例如 modern），我就用它幫你做簡報。"
    )


@tool
def create_pptx(title: str, slides: list[dict], template: str = "general",
                subtitle: str = "") -> str:
    """用你架設的 Presenton 產生 PowerPoint 並回傳下載連結。

    請先讓使用者用 list_ppt_templates 挑 template，再用該名稱呼叫本工具。
    本工具只走 Presenton；若 Presenton 未設定或產生失敗，會回報錯誤（沒有內建版型後備）。

    Args:
        title: 簡報標題。
        slides: 內容頁清單，每項一個 dict，依 "type" 決定結構（用來組織給 Presenton 的大綱）：
            - {"type": "content", "heading": "頁標題", "bullets": ["重點1","重點2"], "lead": "（選填）導言"}
            - {"type": "section", "heading": "章節名"}
            - {"type": "two_column", "heading": "頁標題",
               "left": {"subheading": "左小標", "bullets": [...]},
               "right": {"subheading": "右小標", "bullets": [...]}}
            - {"type": "closing", "heading": "結尾語"}
            未填 type 預設為 content。配圖由 Presenton 自行處理，不需指定。
        template: Presenton 的 template 名稱（需為 list_ppt_templates 列出的其中之一，
            如 general / modern / standard / swift）。
        subtitle: 封面副標（選填）。
    """
    cards = template_cards()
    if not cards:
        return (
            "無法連到 Presenton（PRESENTON_URL 未設定或服務未啟動）。目前 PPT 只支援 Presenton，"
            "請先把它跑起來再試。"
        )
    valid = {c["key"] for c in cards}
    if template not in valid:
        opts = "、".join(sorted(valid))
        return f"找不到 template「{template}」。請從這些擇一：{opts}（可先用 list_ppt_templates 查）。"

    max_tries = max(1, int(os.getenv("PRESENTON_RETRIES", "2")))
    name, err = _presenton_generate(title, slides, subtitle, template)
    tries = 1
    while not name and tries < max_tries:
        name, err = _presenton_generate(title, slides, subtitle, template)
        tries += 1
    if not name:
        return (
            f"用 Presenton 產生簡報失敗（已試 {tries} 次）：{err}\n"
            "這通常是 Presenton 端的問題（多半是它的 LLM 設定），請檢查容器設定後再試。"
        )
    suffix = f"（第 {tries} 次嘗試成功）" if tries > 1 else ""
    # 用 markdown 連結回傳，前端才會渲染成可點的下載按鈕（純文字路徑不會變連結）
    return (
        f"已用 Presenton・「{_TEMPLATE_ZH.get(template, template)}」template 產生簡報"
        f"（{len(slides)} 頁，{EXPORT_AS.upper()} 格式）{suffix}。"
        f"下載連結：[點我下載簡報 {EXPORT_AS.upper()}](/files/{name})\n"
        "（PDF 跟預覽一致、不會跑版；若要可編輯的 PowerPoint，可到 Presenton 網頁開同一份下載 pptx。）"
    )
