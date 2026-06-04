"""PDF 相關工具。"""

from langchain_core.tools import tool
from pypdf import PdfReader

# 擷取文字的字數上限。長 PDF（如上百頁財報）整份塞進對話會撐爆 LLM 的 context
# 上限（gpt-4o-mini 為 128k tokens），導致整個流程報 context_length_exceeded。
# 這裡先截斷成可處理的長度；agent 本來就是做「摘要 / 轉簡報」，前段內容通常已足夠。
MAX_CHARS = 40000


@tool
def extract_pdf_text(file_path: str) -> str:
    """讀取指定路徑的 PDF 檔案，回傳其純文字內容（過長會自動截斷）。

    Args:
        file_path: PDF 檔案的完整路徑。
    """
    reader = PdfReader(file_path)
    pages = [(page.extract_text() or "") for page in reader.pages]
    text = "\n".join(pages).strip()
    if not text:
        return "（這個 PDF 沒有可擷取的文字，可能是掃描檔或圖片型 PDF。）"
    if len(text) > MAX_CHARS:
        return (
            text[:MAX_CHARS]
            + f"\n\n（注意：此 PDF 內容過長，已截斷至前 {MAX_CHARS} 字"
            f"（原文約 {len(text)} 字）。若需後段內容，請只上傳該段落、或拆成多個小檔。）"
        )
    return text
