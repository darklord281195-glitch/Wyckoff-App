import type { Metadata } from "next";
import Link from "next/link";
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
        <div className="wrap">
          <nav className="nav">
            <Link href="/" className="brand">📊 Wyckoff Scanner</Link>
            <Link href="/" className="link">Tổng quan</Link>
            <Link href="/watchlist" className="link">Danh mục</Link>
            <Link href="/dong-tien" className="link">Dòng tiền</Link>
            <Link href="/ket-qua" className="link">Kết quả</Link>
            <Link href="/symbol/VNINDEX" className="link">VNINDEX</Link>
          </nav>
          {children}
          <p className="muted" style={{ fontSize: 12.5 }}>
            Bộ lọc tự động theo Wyckoff, cần xem lại biểu đồ trước khi quyết định. Không phải khuyến nghị đầu tư.
          </p>
        </div>
      </body>
    </html>
  );
}
