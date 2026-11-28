"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import HealthDot from "./HealthDot";

const LINKS = [
  { href: "/", label: "Tổng quan" },
  { href: "/top", label: "Top 10" },
  { href: "/watchlist", label: "Danh mục" },
  { href: "/dong-tien", label: "Dòng tiền" },
  { href: "/ket-qua", label: "Kết quả" },
  { href: "/symbol/VNINDEX", label: "VNINDEX" },
];

/** Thanh điều hướng: tô sáng mục đang mở. */
export default function NavLinks() {
  const path = usePathname() ?? "/";
  const on = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <div className="links">
      {LINKS.map((l) => (
        <Link key={l.href} href={l.href} className={`link${on(l.href) ? " on" : ""}`} aria-current={on(l.href) ? "page" : undefined}>
          {l.label}
        </Link>
      ))}
      <HealthDot active={path.startsWith("/he-thong")} />
    </div>
  );
}
