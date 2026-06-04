import Link from "next/link";

export default function Home() {
  return (
    <>
      <section className="hero">
        <div className="container">
          <span className="eyebrow">LangChain · LangGraph</span>
          <h1>
            ERP AI 助理
            <br />
            把工作交給對的 Agent
          </h1>
          <p>
            用單一 Agent 快速處理單一任務，或用對話讓多個 Agent 自動協作完成複雜需求 ——
            背後由 LangGraph 的 supervisor 流程統一調度。
          </p>
          <div className="hero-cta" style={{ display: "flex", gap: 12 }}>
            <Link href="/single" className="btn btn-white btn-lg">
              使用單一 Agent
            </Link>
            <Link href="/chat" className="btn btn-ghost btn-lg">
              開始多 Agent 對話
            </Link>
          </div>
        </div>
      </section>

      <section
        className="container"
        style={{ marginTop: -64, paddingBottom: 80, position: "relative", zIndex: 1 }}
      >
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))",
            gap: 24,
          }}
        >
          <Link href="/single" className="card card-link">
            <span className="badge badge-pdf" style={{ marginBottom: 14 }}>
              單一 Agent
            </span>
            <h3 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 8px" }}>
              指定一個 Agent 直接處理
            </h3>
            <p className="muted" style={{ margin: 0, lineHeight: 1.6 }}>
              挑選 PDF 分析或庫存查詢等專責 Agent，輸入需求（可附上檔案），立即得到結果。
            </p>
          </Link>

          <Link href="/chat" className="card card-link">
            <span className="badge badge-inventory" style={{ marginBottom: 14 }}>
              多 Agent 協作
            </span>
            <h3 style={{ fontSize: 22, fontWeight: 700, margin: "0 0 8px" }}>
              對話式，讓 Agent 自動接力
            </h3>
            <p className="muted" style={{ margin: 0, lineHeight: 1.6 }}>
              用聊天描述需求，supervisor 會自動判斷該派哪些 Agent、依序協作，直到完成。
            </p>
          </Link>
        </div>
      </section>
    </>
  );
}
