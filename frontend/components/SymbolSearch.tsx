"use client";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { useRouter } from "next/navigation";
import { api } from "@/lib/api";

type Item = { sym: string; name: string | null; floor: string | null };
let cache: Item[] | null = null;                       // danh sách mã: tải một lần cho cả phiên làm việc

/** bỏ dấu tiếng Việt để gõ "hoa phat" vẫn ra "Hòa Phát" */
const plain = (s: string) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/g, "d").replace(/Đ/g, "D").toLowerCase();

/** Ô tìm mã: gõ mã hoặc tên công ty, ↑/↓ chọn gợi ý, Enter mở trang mã, Esc đóng. */
export default function SymbolSearch({ current }: { current?: string }) {
  const router = useRouter();
  const [all, setAll] = useState<Item[]>(cache ?? []);
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!cache) api<Item[]>("/api/listing").then((x) => { cache = x; setAll(x); }).catch(() => {});
    const close = (e: MouseEvent) => { if (box.current && !box.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  // ưu tiên: mã khớp đúng > mã bắt đầu bằng chuỗi gõ > tên công ty chứa chuỗi gõ (không dấu)
  const hits = useMemo(() => {
    const t = q.trim();
    if (!t) return [];
    const up = t.toUpperCase(), p = plain(t);
    const exact = all.filter((x) => x.sym === up);
    const prefix = all.filter((x) => x.sym !== up && x.sym.startsWith(up));
    const byName = t.length >= 2 ? all.filter((x) => !x.sym.startsWith(up) && x.name && plain(x.name).includes(p)) : [];
    return [...exact, ...prefix, ...byName].slice(0, 8);
  }, [q, all]);

  const go = (sym: string) => {
    setQ(""); setOpen(false); setHi(0);
    if (sym && sym !== current) router.push(`/symbol/${sym}`);
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setOpen(true); setHi((h) => Math.min(h + 1, hits.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); const s = hits[hi]?.sym ?? q.trim().toUpperCase(); if (s) go(s); }
    else if (e.key === "Escape") { setOpen(false); (e.target as HTMLInputElement).blur(); }
  };

  return (
    <div ref={box} style={{ position: "relative" }}>
      <input type="search" placeholder="🔍 Tìm mã khác" value={q} autoComplete="off" aria-label="Tìm mã cổ phiếu"
        aria-expanded={open && hits.length > 0} aria-controls="symbol-search-list" role="combobox"
        style={{ width: 190, maxWidth: "100%" }}
        onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }} onFocus={() => setOpen(true)} onKeyDown={onKey} />
      {open && hits.length > 0 && (
        <ul id="symbol-search-list" role="listbox" className="search-pop">
          {hits.map((x, i) => (
            <li key={x.sym} role="option" aria-selected={i === hi} className={i === hi ? "on" : ""}
              onMouseEnter={() => setHi(i)} onMouseDown={(e) => { e.preventDefault(); go(x.sym); }}>
              <b>{x.sym}</b> <span className="muted">{x.name ?? ""}{x.floor ? ` · ${x.floor}` : ""}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
