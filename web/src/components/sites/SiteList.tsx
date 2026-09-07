"use client";

import * as React from "react";
import Link from "next/link";
import { ZONE_COLORS, ZONE_LABELS } from "@/components/viz/palette";
import { Btn, inputCls, nf } from "@/components/ui";
import { caveatBody } from "@/lib/registry/lookup-client";
import { MUNICIPALITY_LABEL } from "@/lib/municipality";

interface Site {
  site_id: string;
  name: string | null;
  zone: number | null;
  lat: number;
  lon: number;
  elevation_m: number | null;
  municipality: string | null;
  operator: string | null;
  water_system_name: string | null;
  source_id: string | null;
  treatment: string | null;
  established_on: string | null;
  n_meas: number;
  n_var: number;
}

type SortKey = "name" | "zone" | "elevation_m" | "n_meas" | "municipality";

export function SiteList({ sites }: { sites: Site[] }) {
  const [q, setQ] = React.useState("");
  const [zone, setZone] = React.useState<number | null>(null);
  const [onlyData, setOnlyData] = React.useState(true);
  const [sort, setSort] = React.useState<SortKey>("elevation_m");
  const [desc, setDesc] = React.useState(true);

  const rows = React.useMemo(() => {
    const needle = q.trim();
    let r = sites.filter((s) => {
      if (onlyData && s.n_meas === 0) return false;
      if (zone !== null && s.zone !== zone) return false;
      if (
        needle &&
        !`${s.name ?? ""} ${s.municipality ?? ""} ${s.water_system_name ?? ""} ${s.site_id}`.includes(needle)
      )
        return false;
      return true;
    });
    r = [...r].sort((a, b) => {
      const av = a[sort] as string | number | null;
      const bv = b[sort] as string | number | null;
      if (av === bv) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      const c = typeof av === "number" && typeof bv === "number" ? av - bv : String(av).localeCompare(String(bv), "ja");
      return desc ? -c : c;
    });
    return r;
  }, [sites, q, zone, onlyData, sort, desc]);

  const byZone = React.useMemo(() => {
    const m = new Map<number | null, number>();
    for (const s of sites) m.set(s.zone, (m.get(s.zone) ?? 0) + 1);
    return m;
  }, [sites]);

  const th = (k: SortKey, label: string) => (
    <th>
      <button
        className="hover:text-water-ink"
        onClick={() => {
          if (sort === k) setDesc(!desc);
          else {
            setSort(k);
            setDesc(true);
          }
        }}
      >
        {label} {sort === k ? (desc ? "▼" : "▲") : ""}
      </button>
    </th>
  );

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="no-print border-b border-line bg-surface px-4 py-2.5">
        <div className="flex items-end gap-3 flex-wrap">
          <div>
            <h1 className="text-[15px] font-bold">地点カルテ</h1>
            <p className="text-[11px] text-muted">
              観測地点 {nf(sites.length)} 件。うち測定値があるのは {nf(sites.filter((s) => s.n_meas > 0).length)} 件
            </p>
          </div>
          <input
            className={inputCls + " w-56"}
            placeholder="地点名・水域名で探す"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="flex items-center gap-0.5">
            <Btn active={zone === null} onClick={() => setZone(null)}>
              全ゾーン
            </Btn>
            {[1, 2, 3, 4, 5].map((z) => (
              <Btn key={z} active={zone === z} onClick={() => setZone(z)} title={ZONE_LABELS[z]}>
                <span className="inline-flex items-center gap-1">
                  <span className="w-2 h-2 rounded-full" style={{ background: ZONE_COLORS[z] }} />
                  {z}
                  <span className="opacity-60">({byZone.get(z) ?? 0})</span>
                </span>
              </Btn>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-[12px] cursor-pointer">
            <input type="checkbox" checked={onlyData} onChange={(e) => setOnlyData(e.target.checked)} />
            測定値のある地点だけ
          </label>
          <span className="ml-auto text-[11px] text-muted tnum">{nf(rows.length)} 件表示</span>
        </div>
      </div>

      <div className="flex-1 overflow-auto thin-scroll">
        <table className="dtable">
          <thead>
            <tr>
              {th("name", "地点名")}
              {th("zone", "ゾーン")}
              {th("elevation_m", "標高")}
              {th("municipality", MUNICIPALITY_LABEL)}
              <th>水系</th>
              {th("n_meas", "測定値")}
              <th>項目数</th>
              <th>運用</th>
              <th>設置</th>
              <th>区分</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((s) => (
              <tr key={s.site_id}>
                <td>
                  <Link href={`/sites/${encodeURIComponent(s.site_id)}`} className="text-water-ink hover:underline">
                    {s.name ?? s.site_id}
                  </Link>
                </td>
                <td>
                  {s.zone != null ? (
                    <span className="inline-flex items-center gap-1.5">
                      <span className="w-2.5 h-2.5 rounded-full" style={{ background: ZONE_COLORS[s.zone] }} />
                      {s.zone}. {ZONE_LABELS[s.zone]}
                    </span>
                  ) : (
                    <span className="text-muted">–</span>
                  )}
                </td>
                <td className="num">{s.elevation_m != null ? `${Math.round(s.elevation_m)} m` : "–"}</td>
                <td>{s.municipality ?? "–"}</td>
                <td className="text-muted">{s.water_system_name ?? "–"}</td>
                <td className="num">{nf(s.n_meas)}</td>
                <td className="num">{s.n_var}</td>
                <td className="text-muted">{s.operator ?? "–"}</td>
                <td className="num text-muted">{s.established_on ?? "–"}</td>
                <td>{s.treatment ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="no-print border-t border-line bg-surface px-4 py-2 text-[10.5px] text-muted leading-relaxed">
        {caveatBody("zone")}　「{MUNICIPALITY_LABEL}」列は原本では municipality という列名だが、
        環境省の水質測定点 290 件では水域名（河川名・湖沼名）が、それ以外の 62 件では市区町村名が入っている。
      </div>
    </div>
  );
}
