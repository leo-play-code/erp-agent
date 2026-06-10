"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getAuthConfig, getToken } from "@/lib/api";

// 路由守衛：啟用登入(auth_enabled)且未登入時，把使用者導到 /login。
// 單人模式(未設 GOOGLE_CLIENT_ID)則完全放行，行為與之前一樣。
export default function AuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    let active = true;
    getAuthConfig().then((cfg) => {
      if (!active) return;
      if (cfg.auth_enabled && !getToken() && pathname !== "/login") {
        router.replace("/login");
      } else {
        setReady(true);
      }
    });
    return () => {
      active = false;
    };
  }, [pathname, router]);

  // 驗證完成前不顯示內容（避免未登入閃過受保護畫面）；登入頁本身直接放行。
  if (!ready && pathname !== "/login") return null;
  return <>{children}</>;
}
