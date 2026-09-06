/**
 * 最小限の RFC4180 準拠 CSV パーサ（引用符・引用符内カンマ・引用符内改行・
 * ""エスケープに対応）。依存追加を避けるため自前で書く。
 *
 * 元は `web/scripts/build-registry-ts.mjs` の `parseCsvRows` / `parseCsvRecords` だった
 * （`scripts/registry/build_taxon.py` / `build_place.py` が `csv.DictReader` を使うのと
 * 同じ厳密さ。列数が想定と違えば例外を投げる＝黙って壊れない）。
 * `web/scripts/build-geo.mjs` の `parseCsvLine`（引用符・""エスケープ対応の手書きパーサ）と
 * 「同じアルゴリズムの再実装」だったため、ここに1本化した（/simplify 修正3）。
 * 違いは build-geo.mjs 側が「引用符内の改行には対応しない・1行ずつ渡す」だった点だが、
 * この共通実装はその上位互換（複数行を一括処理でき、引用符内改行にも対応する）なので
 * 両方から呼んでも動作は変わらない。
 */

/**
 * CSV 全文を行×列の文字列配列に分解する。
 *
 * 戻り値: `string[][]`（1行目はヘッダを含む生データ。呼び出し側で必要なら分離する）。
 * 末尾の空行（末尾の改行の後の空行）は無視する。
 */
export function parseCsvRows(text) {
  const rows = [];
  let field = "";
  let row = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (inQuotes) {
      if (c === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += c;
      }
      continue;
    }
    if (c === '"') {
      inQuotes = true;
      continue;
    }
    if (c === ",") {
      row.push(field);
      field = "";
      continue;
    }
    if (c === "\r") {
      continue; // \r\n の \r を読み飛ばす（\n 側で行を確定する）
    }
    if (c === "\n") {
      row.push(field);
      field = "";
      rows.push(row);
      row = [];
      continue;
    }
    field += c;
  }
  if (inQuotes) {
    throw new Error("parseCsvRows: 引用符が閉じられないまま CSV が終端した");
  }
  // 最終行（末尾に改行が無い場合）も確定させる。空文字列1個だけの残骸（末尾の
  // 改行の後の空行）は無視する。
  if (field !== "" || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows.filter((r) => !(r.length === 1 && r[0] === ""));
}

/**
 * `parseCsvRows` の結果をヘッダ検証つきでオブジェクト配列にする。
 * ヘッダが `expectedHeader` と一致しない、または行の列数がヘッダと違う場合は例外を投げる
 * （黙って壊れない。列がずれたまま読み進めない）。
 */
export function parseCsvRecords(text, expectedHeader) {
  const rows = parseCsvRows(text);
  if (rows.length === 0) {
    throw new Error("parseCsvRecords: CSV が空（ヘッダ行すら無い）");
  }
  const [header, ...dataRows] = rows;
  const headerStr = header.join(",");
  const expectedStr = expectedHeader.join(",");
  if (headerStr !== expectedStr) {
    throw new Error(
      `parseCsvRecords: ヘッダが想定と違う。期待: ${expectedStr} / 実際: ${headerStr}`,
    );
  }
  return dataRows.map((cols, idx) => {
    if (cols.length !== header.length) {
      throw new Error(
        `parseCsvRecords: ${idx + 2}行目の列数が想定と違う` +
          `（期待 ${header.length}列、実際 ${cols.length}列）: ${JSON.stringify(cols)}`,
      );
    }
    const record = {};
    header.forEach((key, i) => {
      record[key] = cols[i];
    });
    return record;
  });
}
