/**
 * `domain.ts` 向けの派生値（VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE /
 * VARIABLE_UNIT_FALLBACK）を組み立てる純粋関数。
 *
 * 元々は実行時に `web/src/lib/domain.ts` が `web/src/lib/registry/lookup.ts` の
 * `primaryAlias()` / `allVariables()` / `unitSymbol()` 経由でこれを計算していた。
 * その結果、`domain.ts` を import するだけで variable 85件（description_ja 込み）・
 * variable_alias 117件（stat/grain/unitId 込み）の生テーブルがまるごとクライアント
 * バンドルに乗っていた（レビュー指摘・code-review #4）。
 *
 * このファイルはビルド時（`web/scripts/build-registry-ts.mjs`）に同じ計算を先に
 * 済ませ、結果の Record だけを `web/src/lib/registry/generated-client.ts` に焼き込む
 * ためのロジック置き場。DB もファイルも開かない・副作用を一切持たない純粋関数のみ
 * （`web/src/lib/registry/primary-alias.test.ts` から直接 import してユニットテストする）。
 *
 * `web/src/lib/registry/lookup.ts` の `primaryAlias()`（サーバ側、任意の variableId を
 * 引数に取る一般版）とは別実装だが、規則は同一（同じ入力に同じ結果を返す）。
 * 一般版は D1 の全 variable/alias を対象にした任意引きに使うので、この build 時専用の
 * 実装と統合すると呼び出し方が食い違う（引数の形が違う）ため、あえて分けてある。
 */

/**
 * alias 文字列で重複を除く。CSV（= variable_alias テーブルの id 順）の行順を保ったまま、
 * 同じ alias 文字列の最初の1行だけを残す。
 *
 * Phase B で variable_alias が (dataset, alias) 単位から (dataset, alias, sourceId) 単位に
 * 分かれたため、同じ alias 文字列が複数行（source 違い）になりうる
 * （docs/plans/PHASE_B_INTAKE.md 設計D）。`pickPrimaryAlias()` の
 * 「fiscal_year でない最初の行」判定は alias 単位の判定なので、渡す前にここで
 * 1 alias = 1行に戻す（build_unit_variable.py の `_assert_variable_unit_consistent_per_alias`
 * が保証する「同じ (dataset, alias) は variable_id/unit_id が一致する」ことが前提）。
 */
export function dedupeByAlias(rows) {
  const seen = new Set();
  const out = [];
  for (const row of rows) {
    if (seen.has(row.alias)) continue;
    seen.add(row.alias);
    out.push(row);
  }
  return out;
}

/**
 * variable_alias の行の集まりから「代表エイリアス」を選ぶ。
 *
 *   1. grain が 'fiscal_year' でない行があれば、それを使う
 *      （検体値ベースの表記を年度代表値の別名より優先する）。
 *   2. 無ければ（=その variable の出典表記が年度代表値しか無い）、
 *      `defaultStat` と一致する stat の行を使う（無ければ先頭行）。
 *
 * `rows` は呼び出し側があらかじめ同じ (variableId, dataset) に絞り込み、
 * `dedupeByAlias()` で alias 単位に戻した配列を渡すこと
 * （このファイル自身は variableId や dataset を知らない）。
 */
export function pickPrimaryAlias(rows, defaultStat) {
  if (rows.length === 0) return undefined;
  const nonFiscal = rows.find((a) => a.grain !== "fiscal_year");
  if (nonFiscal) return nonFiscal;
  const wantStat = defaultStat ?? null;
  return rows.find((a) => (a.stat ?? null) === wantStat) ?? rows[0];
}

function unitSymbolOf(unitId, units) {
  if (!unitId) return null;
  const u = units.find((x) => x.unitId === unitId);
  if (!u) return null;
  return u.symbol ?? "";
}

/**
 * `domain.ts` の VARIABLE_SHORT / VARIABLE_NOTE / HIGHER_IS_WORSE / VARIABLE_UNIT_FALLBACK を
 * 組み立てる（値・フィルタ条件は元の `domain.ts` の実装と1つも変えていない）。
 *
 * @param variables `{variableId, nameJa, descriptionJa, higherIsWorse, defaultStat, ...}` の配列
 * @param aliases `{alias, dataset, variableId, unitId, stat, grain}` の配列
 * @param units `{unitId, symbol}` の配列（VARIABLE_UNIT_FALLBACK の unitSymbol 解決に使う）
 * @param dataset domain.ts の元の対象範囲と同じく "measurements" 固定
 */
export function buildClientVariableMaps(variables, aliases, units, dataset = "measurements") {
  const aliasesByVariable = new Map();
  for (const a of aliases) {
    if (!a.variableId) continue;
    const list = aliasesByVariable.get(a.variableId) ?? [];
    list.push(a);
    aliasesByVariable.set(a.variableId, list);
  }

  const primaryByVariable = variables
    .map((variable) => {
      const rows = dedupeByAlias((aliasesByVariable.get(variable.variableId) ?? []).filter((a) => a.dataset === dataset));
      const row = pickPrimaryAlias(rows, variable.defaultStat);
      return row ? { variable, alias: row.alias, grain: row.grain } : null;
    })
    .filter((x) => x !== null);

  const variableShort = Object.fromEntries(
    primaryByVariable
      .filter(({ grain }) => grain !== "fiscal_year")
      .filter(({ variable, alias }) => variable.nameJa && variable.nameJa !== alias)
      .map(({ variable, alias }) => [alias, variable.nameJa]),
  );

  const variableNote = Object.fromEntries(
    primaryByVariable
      .filter(({ grain }) => grain !== "fiscal_year")
      .filter(({ variable }) => variable.descriptionJa)
      .map(({ variable, alias }) => [alias, variable.descriptionJa]),
  );

  const higherIsWorse = Object.fromEntries(
    primaryByVariable
      .filter(({ variable }) => variable.higherIsWorse !== null)
      .map(({ variable, alias }) => [alias, variable.higherIsWorse]),
  );

  const variableUnitFallback = Object.fromEntries(
    aliases
      .filter((a) => a.dataset === dataset && a.unitId)
      .map((a) => [a.alias, unitSymbolOf(a.unitId, units)])
      .filter((pair) => pair[1] === ""),
  );

  return { variableShort, variableNote, higherIsWorse, variableUnitFallback };
}
