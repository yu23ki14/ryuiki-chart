/**
 * 定期刊行物（広報たつごうなど）の出典表記（docs/plans/TATSUGO_KOHO.md §6.3）。
 * `get_records` の record_set=periodical_issues・document_articles が返す行に、`citation`・`pdf_url`・`source_license` を
 * サーバ側で必ず付ける。モデルに任せない。系列の題・発行者・ライセンスは D1 の `periodical_series`（クエリで JOIN 済み）から取り、ここには直書きしない。
 */
import type { RecordRow } from "@/lib/records";

const ymParts = (ym: unknown): [number, number] | null => {
  const m = typeof ym === "string" ? /^(\d{4})-(\d{2})$/.exec(ym) : null;
  return m ? [Number(m[1]), Number(m[2])] : null;
};

/** 号の表記。月刊は「2024年12月号」、合併号は「2019年4・5月合併号」、別冊は「2015年2月 別冊」。年月が読めなければ null。 */
export function issueLabel(issue: { kind?: unknown; year_month?: unknown; year_month_to?: unknown }): string | null {
  const from = ymParts(issue.year_month);
  if (!from) return null;
  const to = ymParts(issue.year_month_to);
  if (issue.kind === "supplement") return `${from[0]}年${from[1]}月 別冊`;
  if (!to) return `${from[0]}年${from[1]}月号`;
  return to[0] === from[0] ? `${from[0]}年${from[1]}・${to[1]}月合併号` : `${from[0]}年${from[1]}月・${to[0]}年${to[1]}月合併号`;
}

/**
 * 出典の文字列。ページは号内通しページ（範囲は p.12–13）。例: 龍郷町「広報たつごう」2024年12月号 p.12。
 * 系列の発行者・題が無い（系列の行が無い）ときは、推測で埋めず null。
 */
export function periodicalCitation(r: {
  publisher?: unknown; title?: unknown; kind?: unknown; year_month?: unknown; year_month_to?: unknown; page_from?: unknown; page_to?: unknown;
}): string | null {
  const label = issueLabel(r);
  if (label === null || typeof r.publisher !== "string" || typeof r.title !== "string") return null;
  const from = typeof r.page_from === "number" ? r.page_from : null;
  const to = typeof r.page_to === "number" ? r.page_to : from;
  const pages = from === null ? "" : to !== null && to !== from ? ` p.${from}–${to}` : ` p.${from}`;
  return `${r.publisher}「${r.title}」${label}${pages}`;
}

/** 元 PDF の URL に該当ページ（ファイル内ページ）を付ける。 */
export function pdfPageUrl(url: unknown, filePage: unknown): string | null {
  if (typeof url !== "string" || url === "") return null;
  return typeof filePage === "number" ? `${url}#page=${filePage}` : url;
}

/** 記事の行に citation・pdf_url・source_license を付け、内部の結合列を外す（`RECORD_TABLES.document_articles.decorate`）。 */
export function decorateArticle(r: RecordRow): RecordRow {
  const { doc_url, series_title, series_publisher, series_license, issue_kind, ...rest } = r;
  return {
    ...rest,
    citation: periodicalCitation({
      publisher: series_publisher, title: series_title, kind: issue_kind, year_month: r.year_month, year_month_to: r.year_month_to,
      page_from: r.issue_page_from, page_to: r.issue_page_to,
    }),
    pdf_url: pdfPageUrl(doc_url, r.page_from),
    source_license: series_license ?? null,
  };
}

/** 号の行に citation を付ける（ページは無い）。 */
export function decorateIssue(r: RecordRow): RecordRow {
  const { series_title, series_publisher, ...rest } = r;
  return { ...rest, citation: periodicalCitation({ publisher: series_publisher, title: series_title, ...r }) };
}
