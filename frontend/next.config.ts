import type { NextConfig } from "next";

const nextConfig: NextConfig = {
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
