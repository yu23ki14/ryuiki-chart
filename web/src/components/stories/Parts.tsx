import type { DamageTable, StoryDoc } from "@/lib/stories/amami";
import { nf } from "@/components/ui";

/** 注記の文面（DB の `notes.text`）をそのまま並べる。 */
export function NoteList({ title, notes }: { title?: string; notes: { key: string; text: string }[] }) {
  if (notes.length === 0) return null;
  return (
    <div className="card p-3.5">
      {title && <h3 className="text-[12.5px] font-semibold mb-1.5">{title}</h3>}
      <ul className="space-y-1.5 text-[12px] leading-relaxed text-ink-2">
        {notes.map((n) => (
          <li key={n.key}>{n.text}</li>
        ))}
      </ul>
    </div>
  );
}

/** 章末の出典。題名・出典元・リンク・ライセンスを `documents` の値のまま表示する。 */
export function SourceList({ docs }: { docs: StoryDoc[] }) {
  return (
    <div className="text-[11px] text-muted leading-relaxed">
      <div className="font-semibold text-ink-2 mb-1">出典</div>
      <ul className="space-y-1">
        {docs.map((d) => (
          <li key={d.docId}>
            {d.url ? (
              <a href={d.url} target="_blank" rel="noreferrer" className="text-water underline">
                {d.title ?? d.docId}
              </a>
            ) : (
              <span>{d.title ?? d.docId}</span>
            )}
            {d.publisher && <span>　{d.publisher}</span>}
            {d.license && <span className="block">ライセンス: {d.license}</span>}
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 出典ごとの被害。1つの表に列で並べ、合算も寄せもしない。 */
export function DamageTableView({ table }: { table: DamageTable }) {
  const agreed = table.agreed;
  return (
    <div className="card overflow-hidden">
      <div className="px-3.5 pt-2.5 pb-2">
        <h3 className="text-[13px] font-semibold">被害（出典ごと）</h3>
        <p className="text-[11px] text-muted mt-0.5 leading-snug">
          {agreed.length > 0
            ? `確定しているのは${agreed.map((a) => `${a.label}${nf(a.value)}${a.unit ?? ""}`).join("・")}のみ。`
            : "全出典で一致する項目はない。"}
          他は出典ごとに異なり、どれにも寄せていない。
        </p>
      </div>
      <div className="overflow-auto thin-scroll px-2.5 pb-2">
        <table className="dtable text-[11.5px]">
          <thead>
            <tr>
              <th>項目</th>
              {table.columns.map((c) => (
                <th key={c.key}>{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.items.map((it) => (
              <tr key={it.key}>
                <td>{it.label}</td>
                {table.columns.map((c) => {
                  const v = c.values[it.key];
                  const sure = agreed.some((a) => a.key === it.key);
                  return (
                    <td key={c.key} className={v === null ? "null" : "num"}>
                      {v === null ? "–" : `${nf(v.value)}${v.unit ?? ""}`}
                      {sure && v !== null ? "（一致）" : ""}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <ul className="px-3.5 py-2 space-y-1.5 text-[10.5px] text-muted leading-relaxed border-t border-line">
        {table.columns.map((c) => (
          <li key={c.key}>
            <span className="font-semibold text-ink-2">{c.label}: </span>
            {c.note}
          </li>
        ))}
      </ul>
    </div>
  );
}
