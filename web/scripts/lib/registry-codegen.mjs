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
 * variable_alias の行の集まりから「代表エイリアス」を選ぶ。
 *
 *   1. grain が 'fiscal_year' でない行があれば、それを使う
 *      （検体値ベースの表記を年度代表値の別名より優先する）。
 *   2. 無ければ（=その variable の出典表記が年度代表値しか無い）、
 *      `defaultStat` と一致する stat の行を使う（無ければ先頭行）。
 *
 * `rows` は呼び出し側があらかじめ同じ (variableId, sourceScope) に絞り込んだ配列を渡すこと
 * （このファイル自身は variableId や sourceScope を知らない）。
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
 * @param aliases `{alias, sourceScope, variableId, unitId, stat, grain}` の配列
 * @param units `{unitId, symbol}` の配列（VARIABLE_UNIT_FALLBACK の unitSymbol 解決に使う）
 * @param sourceScope domain.ts の元の対象範囲と同じく "measurements" 固定
 */
export function buildClientVariableMaps(variables, aliases, units, sourceScope = "measurements") {
  const aliasesByVariable = new Map();
  for (const a of aliases) {
    if (!a.variableId) continue;
    const list = aliasesByVariable.get(a.variableId) ?? [];
    list.push(a);
    aliasesByVariable.set(a.variableId, list);
  }

  const primaryByVariable = variables
    .map((variable) => {
      const rows = (aliasesByVariable.get(variable.variableId) ?? []).filter((a) => a.sourceScope === sourceScope);
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
      .filter((a) => a.sourceScope === sourceScope && a.unitId)
      .map((a) => [a.alias, unitSymbolOf(a.unitId, units)])
      .filter((pair) => pair[1] === ""),
  );

  return { variableShort, variableNote, higherIsWorse, variableUnitFallback };
}
