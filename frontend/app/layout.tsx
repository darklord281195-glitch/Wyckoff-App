import type { Metadata } from "next";
import Link from "next/link";
import NavLinks from "@/components/NavLinks";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wyckoff Scanner",
  description: "Quét cổ phiếu Việt Nam theo phương pháp Wyckoff mỗi cuối ngày",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <head>
        <link
          rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap"
        />
      </head>
      <body>
        <header className="topbar">
          <nav className="nav">
            <Link href="/" className="brand"><span className="logo" aria-hidden>W</span>Wyckoff Scanner</Link>
            <NavLinks />
          </nav>
        </header>
        <div className="wrap">
          {children}
          <p className="foot">
            Bộ lọc tự động theo Wyckoff, cần xem lại biểu đồ trước khi quyết định. Không phải khuyến nghị đầu tư.
          </p>
        </div>
      </body>
    </html>
  );
}
