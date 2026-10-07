/**
 * 応答のバイト数が予算に収まるまで、行を「先頭から残して」減らす（等間隔に間引かない）。
 *
 * 続きを取る手段（offset / next_after）が「返した最後の行」の次を指すツール（get_records・find_datasets）用。
 * 等間隔に間引くと、返さなかった行が途中に散って続きが取れなくなる。`more` は呼び出し側が「元の応答に続きがあるか」を渡し、
 * 減らしたときは true になる。`build` は（残した行, more）から応答の `data` を組み直す（next_after のような、行に依存する値はここで計算する）。
 */
export function byteLength(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).length;
}

export interface HeadRowsFit<R, T> {
  rows: R[];
  data: T;
  /** 続きがある（元から or 行を減らした）。 */
  more: boolean;
  /** 行を減らした。 */
  shrunk: boolean;
  /** 1 行まで減らしても予算を超えている（行の途中は削らずにそのまま返す）。 */
  oversize: boolean;
}

export function fitHeadRows<R, T>(rows: readonly R[], more: boolean, build: (rows: R[], more: boolean) => T, budget: number): HeadRowsFit<R, T> {
  let cur = [...rows];
  let m = more;
  let data = build(cur, m);
  let shrunk = false;
  while (cur.length > 1 && byteLength(data) > budget) {
    cur = cur.slice(0, Math.max(1, Math.floor(cur.length * 0.7)));
    m = true;
    shrunk = true;
    data = build(cur, m);
  }
  return { rows: cur, data, more: m, shrunk, oversize: byteLength(data) > budget };
}
