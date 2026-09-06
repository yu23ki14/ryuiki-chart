"use client";

import * as React from "react";
import { DataGrid } from "./DataGrid";
import { Btn, inputCls, Spinner, nf } from "@/components/ui";
import { SAMPLE_QUERIES } from "@/lib/table-meta";

interface SqlResult {
  columns: string[];
  rows: unknown[][];
  rowCount: number;
  truncated: boolean;
  elapsedMs: number;
  sql: string;
}

const STORAGE_KEY = "ryuiki.sql.history";

export function SqlConsole({ initialSql }: { initialSql?: string } = {}) {
  const [sql, setSql] = React.useState(initialSql ?? SAMPLE_QUERIES[0].sql);
  const [res, setRes] = React.useState<SqlResult | null>(null);
  const [err, setErr] = React.useState<string | null>(null);
  const [loading, setLoading] = React.useState(false);
  const [limit, setLimit] = React.useState(1000);
  // localStorage が使えない環境（プライベートウィンドウ等）でも動くようにする
  const [history, setHistory] = React.useState<string[]>(() => {
    if (typeof window === "undefined") return [];
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? (JSON.parse(raw) as string[]) : [];
    } catch {
      return [];
    }
  });

  const run = React.useCallback(
    async (text?: string) => {
      const body = (text ?? sql).trim();
      if (!body) return;
      setLoading(true);
      setErr(null);
      try {
        const r = await fetch("/api/sql", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ sql: body, limit }),
        });
        const j = (await r.json()) as SqlResult & { error?: string };
        if (!r.ok) throw new Error(j.error ?? "実行に失敗しました");
        setRes(j);
        setHistory((h) => {
          const next = [body, ...h.filter((x) => x !== body)].slice(0, 30);
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
          } catch {
            /* noop */
          }
          return next;
        });
      } catch (e) {
        setErr(e instanceof Error ? e.message : String(e));
        setRes(null);
      } finally {
        setLoading(false);
      }
    },
    [sql, limit],
  );

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      void run();
    }
  };

  return (
    <div className="flex-1 flex min-h-0">
      <div className="flex-1 flex flex-col min-w-0">
        <div className="p-3 border-b border-line bg-surface">
          <textarea
            value={sql}
            onChange={(e) => setSql(e.target.value)}
            onKeyDown={onKeyDown}
            spellCheck={false}
            rows={8}
            className="w-full font-mono text-[12.5px] leading-relaxed p-2.5 rounded border border-line bg-surface-2 focus:outline-none focus:ring-2 focus:ring-water/30 focus:border-water resize-y"
          />
          <div className="flex items-center gap-2 mt-2">
            <Btn active onClick={() => run()} disabled={loading}>
              実行 <span className="opacity-70 ml-1">⌘/Ctrl + Enter</span>
            </Btn>
            <select className={inputCls + " w-auto"} value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[100, 1000, 5000, 20000].map((n) => (
                <option key={n} value={n}>
                  上限 {nf(n)} 行
                </option>
              ))}
            </select>
            {res && (
              <button
                className="text-[12px] px-2.5 py-1 rounded border border-line bg-surface hover:bg-surface-2 text-ink-2"
                onClick={async () => {
                  const r = await fetch("/api/sql", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ sql: res.sql, limit: 100000, format: "csv" }),
                  });
                  const blob = await r.blob();
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = "query.csv";
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                CSV ダウンロード
              </button>
            )}
            <div className="ml-auto text-[11px] text-muted">
              {loading ? (
                <Spinner label="実行中" />
              ) : err ? (
                <span className="text-bad">{err}</span>
              ) : res ? (
                <span className="tnum">
                  {nf(res.rowCount)} 行{res.truncated && "（表示は上限まで）"} / {res.elapsedMs.toFixed(0)} ms
                </span>
              ) : (
                <span>
                  参照系のみ実行できます。<code className="font-mono">c.</code> は行政文書DB、
                  <code className="font-mono">d.</code> は集計DB。
                </span>
              )}
            </div>
          </div>
        </div>
        <div className="flex-1 min-h-0">
          {res && <DataGrid columns={res.columns.map((n) => ({ name: n }))} rows={res.rows} />}
          {!res && !err && (
            <div className="p-6 text-[12px] text-muted">
              右のサンプルから選ぶか、SQL を書いて実行してください。
            </div>
          )}
        </div>
      </div>

      <aside className="w-64 shrink-0 border-l border-line bg-surface overflow-y-auto thin-scroll">
        <div className="px-3 py-2 border-b border-line text-[12px] font-semibold">サンプルクエリ</div>
        <div className="p-2 space-y-1">
          {SAMPLE_QUERIES.map((s) => (
            <button
              key={s.title}
              className="w-full text-left p-2 rounded hover:bg-water-soft border border-transparent hover:border-water/30"
              onClick={() => {
                setSql(s.sql);
                void run(s.sql);
              }}
            >
              <div className="text-[12px] font-medium">{s.title}</div>
              <div className="text-[10.5px] text-muted leading-snug mt-0.5">{s.note}</div>
            </button>
          ))}
        </div>
        {history.length > 0 && (
          <>
            <div className="px-3 py-2 border-y border-line text-[12px] font-semibold flex items-center">
              実行履歴
              <button
                className="ml-auto text-[10px] text-muted underline font-normal"
                onClick={() => {
                  setHistory([]);
                  try {
                    localStorage.removeItem(STORAGE_KEY);
                  } catch {
                    /* noop */
                  }
                }}
              >
                消去
              </button>
            </div>
            <div className="p-2 space-y-1">
              {history.map((h, i) => (
                <button
                  key={i}
                  className="w-full text-left p-1.5 rounded hover:bg-surface-2 font-mono text-[10.5px] text-ink-2 line-clamp-3 leading-snug"
                  onClick={() => setSql(h)}
                >
                  {h.replace(/\s+/g, " ").slice(0, 120)}
                </button>
              ))}
            </div>
          </>
        )}
      </aside>
    </div>
  );
}
