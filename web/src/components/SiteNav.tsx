"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { EXPLORE_ENABLED } from "@/lib/features";

const NAV = [
  { href: "/", label: "概況", exact: true },
  { href: "/map", label: "流域マップ" },
  { href: "/water", label: "水源マップ" },
  { href: "/timeseries", label: "時系列比較" },
  { href: "/biota", label: "生物相" },
  { href: "/sites", label: "地点カルテ" },
  { href: "/quality", label: "品質と進捗" },
  { href: "/explore", label: "データ探索", flag: EXPLORE_ENABLED },
  { href: "/sources", label: "出典" },
].filter((n) => n.flag !== false);

export function SiteNav() {
  const pathname = usePathname();
  return (
    <header className="no-print sticky top-0 z-50 border-b border-line bg-surface/95 backdrop-blur">
      <div className="flex items-stretch gap-1 px-4 h-12">
        <Link href="/" className="flex items-center gap-2.5 pr-4 shrink-0">
          <RidgeToReefMark />
          <span className="leading-none">
            <span className="block text-[14px] font-bold tracking-tight">流域カルテ</span>
            <span className="block text-[9px] text-muted tracking-[0.14em] uppercase">Watershed Chart</span>
          </span>
        </Link>
        <nav className="flex items-stretch gap-0.5 overflow-x-auto thin-scroll">
          {NAV.map((n) => {
            const active = n.exact ? pathname === n.href : pathname.startsWith(n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                className={`flex items-center px-3 text-[13px] whitespace-nowrap border-b-2 transition-colors ${
                  active
                    ? "border-water text-water-ink font-medium"
                    : "border-transparent text-ink-2 hover:text-ink hover:bg-surface-2"
                }`}
              >
                {n.label}
              </Link>
            );
          })}
        </nav>
        <div className="ml-auto flex items-center gap-2 pl-3 shrink-0">
          <button
            onClick={() => window.print()}
            className="text-[11px] border border-line rounded px-2 py-1 text-ink-2 hover:bg-surface-2"
            title="この画面を1枚のPDF・画像として書き出す（会議に持ち出すため）"
          >
            会議用に書き出す
          </button>
          <span className="text-[10px] text-muted border border-line rounded px-1.5 py-0.5">
            デモ / 神奈川県公開データ
          </span>
        </div>
      </div>
    </header>
  );
}

/** 尾根から海までを一本の線で表したマーク */
function RidgeToReefMark() {
  return (
    <svg width="26" height="26" viewBox="0 0 26 26" aria-hidden="true">
      <rect x="0.5" y="0.5" width="25" height="25" rx="5" fill="var(--water-soft)" stroke="var(--line)" />
      <path d="M3 19 L8 7 L12 13 L16 9 L23 19" fill="none" stroke="var(--zone-1)" strokeWidth="1.7" strokeLinejoin="round" strokeLinecap="round" />
      <path d="M3 21.5 Q7 20 10 21.5 T17 21.5 T23 21.5" fill="none" stroke="var(--zone-5)" strokeWidth="1.7" strokeLinecap="round" />
    </svg>
  );
}
