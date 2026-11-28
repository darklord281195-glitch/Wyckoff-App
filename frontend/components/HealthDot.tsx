"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { api, type Health } from "@/lib/api";

const COLOR: Record<Health["level"], string> = { ok: "var(--green)", warn: "var(--yellow)", error: "var(--red)" };
const TITLE: Record<Health["level"], string> = { ok: "Hệ thống bình thường", warn: "Có mục cần xem", error: "Có lỗi cần xử lý" };

/** Mục "Hệ thống" trên thanh điều hướng, chấm màu theo mức tệ nhất của /api/health (tải lại mỗi 10 phút). */
export default function HealthDot() {
  const [lv, setLv] = useState<Health["level"] | null>(null);
  useEffect(() => {
    const load = () => api<Health>("/api/health").then((h) => setLv(h.level)).catch(() => setLv("error"));
    load();
    const id = setInterval(load, 600_000);
    return () => clearInterval(id);
  }, []);
  return (
    <Link href="/he-thong" className="link" title={lv ? TITLE[lv] : "Sức khỏe hệ thống"}>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        {lv && <span aria-hidden style={{ width: 9, height: 9, borderRadius: "50%", background: COLOR[lv] }} />}
        Hệ thống
      </span>
    </Link>
  );
}
