import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // dev 模式下，允許從反向代理 / 臨時通道的網域存取 /_next 資源（Next 16 預設擋跨來源，
  // 否則經 trycloudflare 或自訂網域開時，HTML 載得到但 JS/CSS chunk 被擋 → 空白頁）。
  // 僅影響 next dev；正式 build/start 無此限制。可用環境變數 CF_DEV_ORIGINS 追加自家網域。
  allowedDevOrigins: [
    "*.trycloudflare.com",
    "*.gs.com.tw",
    ...(process.env.CF_DEV_ORIGINS ? process.env.CF_DEV_ORIGINS.split(",") : []),
  ],
  // 把後端 API 與產出檔案的路徑「同源代理」到 FastAPI(8000)。
  // 這樣前端、API、檔案全部走同一個來源(3005),整個 app 才能塞進
  // 單一網址後面 —— 不論是區網 IP、還是 Cloudflare 臨時通道,都只需開一個 port。
  async rewrites() {
    const backend = process.env.BACKEND_ORIGIN || "http://127.0.0.1:8000";
    return [
      { source: "/api/:path*", destination: `${backend}/api/:path*` },
      { source: "/files/:path*", destination: `${backend}/files/:path*` },
    ];
  },
};

export default nextConfig;
