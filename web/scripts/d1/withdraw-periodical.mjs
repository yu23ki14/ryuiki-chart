#!/usr/bin/env node
/**
 * 定期刊行物（広報たつごう）の号・記事を本番 D1 から取り下げる（docs/plans/TATSUGO_KOHO.md §9 手順 3）。
 *   node withdraw-periodical.mjs --issue <issue_id> [--issue ...] [--article <article_id> ...]            # dry-run
 *   node withdraw-periodical.mjs --issue <issue_id> ... --execute                                          # 本番で実行
 *
 * 既定は dry-run（本番を読むだけ。消す行数と、Vectorize から外すための article_id の一覧を出す）。
 * `--execute` は子から親の順に DELETE する:
 *   document_article_places・document_article_topics → document_articles → periodical_issue_files → periodical_issues
 *   →（号の）notes・cells・documents。
 * 号を外すと、その号の記事と PDF（documents）も消える。記事だけ外すときは document_articles と子だけ。
 * 事前に scripts/data/tatsugo_koho_withdrawn.yaml へ追記して m13 → db:setup（ローカル）を済ませておく
 * （最後にローカル D1 と表ごとの件数を突き合わせるため。違えば終了コード 1）。
 * CLOUDFLARE_ACCOUNT_ID を付ける。ID は 100 個以内に区切って流す（D1 の上限と SQL の長さ）。
 * 注意: Vectorize（#132）の入れ直しは別。dry-run が出す article_id の一覧は、D1 を消す前に取る。
 */
import { Database, findLocalD1, qi, wranglerRemote } from "./common.mjs";
import { pathToFileURL } from "node:url";

const CHUNK = 100;
// 子から親の順（消す順）。`kind` は ID の取り方。
const TABLES_BY_ARTICLE = ["document_article_places", "document_article_topics"];
const ID_PATTERN = /^[A-Za-z0-9_.:#-]+$/;

/** 引数を読む。--issue / --article は繰り返せる。 */
export function parseArgs(argv) {
  const issues = [];
  const articles = [];
  let execute = false;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--execute") execute = true;
    else if (a === "--issue" || a === "--article") {
      const v = argv[++i];
      if (!v || v.startsWith("--")) throw new Error(`${a} に値が要る`);
      (a === "--issue" ? issues : articles).push(v);
    } else throw new Error(`知らない引数: ${a}`);
  }
  if (!issues.length && !articles.length) throw new Error("使い方: withdraw-periodical.mjs (--issue <issue_id> | --article <article_id>)... [--execute]");
  for (const id of [...issues, ...articles]) if (!ID_PATTERN.test(id)) throw new Error(`ID に使えない文字が入っている: ${id}`);
  return { issues: [...new Set(issues)], articles: [...new Set(articles)], execute };
}

/** 配列を n 個ずつに区切る。 */
export const chunks = (xs, n = CHUNK) => Array.from({ length: Math.ceil(xs.length / n) }, (_, i) => xs.slice(i * n, i * n + n));
const inList = (ids) => `(${ids.map((x) => `'${x}'`).join(",")})`;

/** 1 文を本番に流して行を返す（SELECT）。 */
const select = (sql) => wranglerRemote(sql)[0].results ?? [];
/** ID の集合ごとに区切って SELECT し、列 `col` の値を集める。 */
function selectIds(table, whereCol, ids, col) {
  const out = [];
  for (const c of chunks(ids)) out.push(...select(`SELECT ${qi(col)} AS v FROM ${qi(table)} WHERE ${qi(whereCol)} IN ${inList(c)}`).map((r) => r.v));
  return out;
}
function countIn(table, whereCol, ids) {
  let n = 0;
  for (const c of chunks(ids)) n += select(`SELECT count(*) AS c FROM ${qi(table)} WHERE ${qi(whereCol)} IN ${inList(c)}`)[0].c;
  return n;
}
function deleteIn(table, whereCol, ids) {
  let n = 0;
  for (const c of chunks(ids)) n += wranglerRemote(`DELETE FROM ${qi(table)} WHERE ${qi(whereCol)} IN ${inList(c)}`)[0].meta?.changes ?? 0;
  return n;
}

/** 消す対象を本番から集める。号を外すと、その号の記事・ファイル・文書が全部入る。 */
function plan({ issues, articles }) {
  const issueArticles = issues.length ? selectIds("document_articles", "issue_id", issues, "article_id") : [];
  const docIds = issues.length ? selectIds("periodical_issue_files", "issue_id", issues, "doc_id") : [];
  const articleIds = [...new Set([...issueArticles, ...articles])];
  return { articleIds, docIds, issues };
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  const p = plan(args);
  const rows = [
    ...TABLES_BY_ARTICLE.map((t) => [t, "article_id", p.articleIds]),
    ["document_articles", "article_id", p.articleIds],
    ["periodical_issue_files", "issue_id", p.issues],
    ["periodical_issues", "issue_id", p.issues],
    ["notes", "doc_id", p.docIds],
    ["cells", "doc_id", p.docIds],
    ["documents", "doc_id", p.docIds],
  ].filter(([, , ids]) => ids.length);

  console.log(`# ${args.execute ? "実行" : "dry-run"}: 号 ${p.issues.length} / 記事 ${p.articleIds.length} / 文書 ${p.docIds.length}`);
  const before = rows.map(([t, c, ids]) => [t, c, ids, countIn(t, c, ids)]);
  for (const [t, , , n] of before) console.log(`- ${t}: ${n.toLocaleString()} 行を消す`);
  // 指定した ID が本番に無いのは、綴りの誤りか取り下げ済み。黙って 0 行にしない
  const missingIssues = p.issues.length ? p.issues.filter((i) => countIn("periodical_issues", "issue_id", [i]) === 0) : [];
  const missingArticles = args.articles.length ? args.articles.filter((a) => !p.articleIds.includes(a) || countIn("document_articles", "article_id", [a]) === 0) : [];
  if (missingIssues.length || missingArticles.length) {
    console.error(`本番に無い ID: ${[...missingIssues, ...missingArticles].join(" ")}（綴りの誤りか取り下げ済み）`);
    process.exit(1);
  }
  console.log("\n# Vectorize から外す article_id（D1 を消す前に取る。号全体なら接頭辞 <doc_id>: のもの）");
  for (const id of p.articleIds) console.log(id);

  if (!args.execute) {
    console.log("\n(dry-run。--execute を付けると本番で実行する)");
    return;
  }

  console.log("");
  for (const [t, c, ids] of before) console.log(`  ${t}: ${deleteIn(t, c, ids).toLocaleString()} 行削除`);

  // 確認: 本番に残っていないこと、ローカル D1（m13 → db:setup 済み）と表ごとの件数が一致すること
  const local = new Database(findLocalD1(), { readonly: true, fileMustExist: true });
  let bad = 0;
  for (const [t, c, ids] of before) {
    const left = countIn(t, c, ids);
    if (left) bad++;
    console.log(`${left === 0 ? "✔" : "✗"} ${t}: 取り下げ対象の残り ${left} 行`);
  }
  for (const t of ["periodical_issues", "periodical_issue_files", "document_articles", "document_article_topics", "document_article_places", "documents"]) {
    const l = local.prepare(`SELECT count(*) AS c FROM ${qi(t)}`).get().c;
    const r = select(`SELECT count(*) AS c FROM ${qi(t)}`)[0].c;
    if (l !== r) bad++;
    console.log(`${l === r ? "✔" : "✗"} ${t}: ローカル ${l.toLocaleString()} / 本番 ${r.toLocaleString()}`);
  }
  local.close();
  process.exit(bad ? 1 : 0);
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    main();
  } catch (e) {
    console.error(String(e?.message ?? e));
    process.exit(2);
  }
}
