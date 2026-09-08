import { describe, expect, it } from "vitest";
import { buildClientVariableMaps, dedupeByAlias, pickPrimaryAlias } from "../../../scripts/lib/registry-codegen.mjs";

/**
 * `web/scripts/lib/registry-codegen.mjs`（`web/scripts/build-registry-ts.mjs` が
 * `generated-client.ts` の VARIABLE_SHORT 等を焼き込むときに使う「代表エイリアス選定」
 * ロジック）の単体テスト。
 *
 * 背景（code-review #4）: この選定ロジックは元々旧 `domain.ts` が実行時に
 * `web/src/lib/registry/lookup.ts` の `primaryAlias()` / `allVariables()` 経由で
 * 行っていた。domain.ts をクライアント安全にするため、この計算をビルド時
 * （このファイルが指す registry-codegen.mjs）に前倒しした結果、旧 `domain.test.ts`
 * （Phase B で撤去。docs/plans/PHASE_B_INTAKE.md #6）は「`generated-client.ts` の
 * 値をそのまま読んでいるだけ」になり、選定ロジック自体の分岐（fiscal_year 優先度・
 * タイブレーク）を検証できなくなった。このファイルがその検証を肩代わりする
 * （実データの固定値の保証は撤去済み。レジストリに語彙を足すたびに赤くなる固定値
 * テストを無くすことが Phase B #6 の目的そのものだった）。
 *
 * 実データに依存しない合成入力だけを使う（data/db/registry.sqlite が無い環境でも動く）。
 *
 * 修正2（`/simplify`）で `web/src/lib/registry/lookup.ts` の実行時版 `primaryAlias()` も
 * `pickPrimaryAlias()` を呼ぶ薄いラッパに統合した。選定ロジックの実装は
 * `web/scripts/lib/registry-codegen.mjs` の1箇所だけになったので、このテストはもはや
 * 「ビルド時実装と実行時実装が一致するか」ではなく、「代表エイリアス選定の規則そのもの」
 * （fiscal_year 優先度・タイブレーク）を検証するテストである。
 *
 * その後（Phase B, 独立 `/code-review high` 指摘）、`lookup.ts` の `primaryAlias()` は
 * 本番の呼び出し元が無い（旧 domain.ts は既にビルド時の `generated-client.ts` を読むだけ
 * だった）うえ、行全体を返すため `variable_alias` が `(dataset, alias, sourceId)` 単位に
 * 分かれた後は `stat`/`grain` が「たまたま CSV で先に来た source_id のもの」という
 * 曖昧な値になってしまっていた（`resolveAlias()` を削除したのと同じ理由）ため削除した。
 * 「代表エイリアス選定」の規則そのものは `web/scripts/build-registry-ts.mjs` が
 * ビルド時に呼ぶ `pickPrimaryAlias()`/`dedupeByAlias()` として引き続き生きており、
 * このテストが検証を継続する。
 */

describe("pickPrimaryAlias", () => {
  it("grain が 'fiscal_year' でない行があれば、それを優先する", () => {
    const rows = [
      { alias: "年度代表値", dataset: "measurements", variableId: "v1", unitId: null, stat: "mean", grain: "fiscal_year" },
      { alias: "検体値", dataset: "measurements", variableId: "v1", unitId: null, stat: "mean", grain: "day" },
    ];
    const picked = pickPrimaryAlias(rows, "mean");
    expect(picked?.alias).toBe("検体値");
  });

  it("grain='fiscal_year' でない行が複数あれば先頭（見つかった順）を使う", () => {
    const rows = [
      { alias: "採水個別値", dataset: "measurements", variableId: "v1", unitId: null, stat: "mean", grain: "mixed" },
      { alias: "別表記", dataset: "measurements", variableId: "v1", unitId: null, stat: "mean", grain: "day" },
    ];
    const picked = pickPrimaryAlias(rows, "mean");
    expect(picked?.alias).toBe("採水個別値");
  });

  it("fiscal_year の行しか無ければ default_stat と一致する stat の行を選ぶ", () => {
    const rows = [
      { alias: "75%値", dataset: "measurements", variableId: "v1", unitId: null, stat: "p75", grain: "fiscal_year" },
      { alias: "平均値", dataset: "measurements", variableId: "v1", unitId: null, stat: "mean", grain: "fiscal_year" },
    ];
    const picked = pickPrimaryAlias(rows, "mean");
    expect(picked?.alias).toBe("平均値");
  });

  it("default_stat と一致する行が無ければ先頭行にフォールバックする", () => {
    const rows = [
      { alias: "75%値", dataset: "measurements", variableId: "v1", unitId: null, stat: "p75", grain: "fiscal_year" },
      { alias: "最大値", dataset: "measurements", variableId: "v1", unitId: null, stat: "max", grain: "fiscal_year" },
    ];
    const picked = pickPrimaryAlias(rows, "mean");
    expect(picked?.alias).toBe("75%値");
  });

  it("stat が null の行と default_stat=null が一致するケース", () => {
    const rows = [
      { alias: "T-N", dataset: "measurements", variableId: "v1", unitId: null, stat: null, grain: "fiscal_year" },
    ];
    const picked = pickPrimaryAlias(rows, null);
    expect(picked?.alias).toBe("T-N");
  });

  it("空配列は undefined", () => {
    expect(pickPrimaryAlias([], "mean")).toBeUndefined();
  });
});

describe("dedupeByAlias", () => {
  it("同じ alias 文字列は最初の1行だけ残す（CSVの行順を保つ）", () => {
    const rows = [
      { alias: "生物化学的酸素要求量 BOD", sourceId: "atsugi", grain: "mixed" },
      { alias: "生物化学的酸素要求量 BOD", sourceId: "env_kousui_sample", grain: "day" },
      { alias: "生物化学的酸素要求量 BOD", sourceId: "env_kousui_annual", grain: "fiscal_year" },
      { alias: "BOD 75%値", sourceId: "env_kousui_annual", grain: "fiscal_year" },
    ];
    const deduped = dedupeByAlias(rows);
    expect(deduped).toHaveLength(2);
    expect(deduped[0]).toEqual(rows[0]);
    expect(deduped[1]).toEqual(rows[3]);
  });

  it("空配列は空配列", () => {
    expect(dedupeByAlias([])).toEqual([]);
  });
});

describe("dedupeByAlias + pickPrimaryAlias（Phase B: 1 alias が複数 source_id 行に分かれても代表選定は変わらない）", () => {
  it("alias の最初の行が非 fiscal_year なら、他の source の fiscal_year 行に埋もれない", () => {
    // registry/variable_alias.csv の並び: 同じ alias の中では fiscal_year の
    // 出典（env_kousui_annual_kanagawa 相当）を最後に置く規約（生成スクリプトのコメント参照）。
    const rows = [
      { alias: "生物化学的酸素要求量 BOD", variableId: "v.bod", dataset: "measurements", stat: "mean", grain: "mixed" },
      { alias: "生物化学的酸素要求量 BOD", variableId: "v.bod", dataset: "measurements", stat: "mean", grain: "day" },
      { alias: "生物化学的酸素要求量 BOD", variableId: "v.bod", dataset: "measurements", stat: "mean", grain: "fiscal_year" },
      { alias: "BOD 75%値", variableId: "v.bod", dataset: "measurements", stat: "p75", grain: "fiscal_year" },
    ];
    const deduped = dedupeByAlias(rows.filter((a) => a.dataset === "measurements"));
    const picked = pickPrimaryAlias(deduped, "mean");
    expect(picked?.alias).toBe("生物化学的酸素要求量 BOD");
    expect(picked?.grain).toBe("mixed");
  });
});

describe("buildClientVariableMaps", () => {
  const units = [
    { unitId: "u.mgl", symbol: "mg/L" },
    { unitId: "u.dimensionless", symbol: null },
  ];
  const variables = [
    {
      variableId: "v.bod",
      nameJa: "BOD",
      descriptionJa: "生物化学的酸素要求量",
      higherIsWorse: true,
      defaultStat: "mean",
    },
    {
      variableId: "v.ph",
      nameJa: "pH",
      descriptionJa: null,
      higherIsWorse: null,
      defaultStat: "mean",
    },
    {
      variableId: "v.tn",
      nameJa: "全窒素",
      descriptionJa: "全窒素T-N",
      higherIsWorse: true,
      defaultStat: "mean",
    },
  ];
  const aliases = [
    { alias: "生物化学的酸素要求量 BOD", dataset: "measurements", variableId: "v.bod", unitId: null, stat: "mean", grain: "mixed" },
    { alias: "pH", dataset: "measurements", variableId: "v.ph", unitId: "u.dimensionless", stat: "point", grain: "mixed" },
    // v.tn は fiscal_year の表記しか無い（全窒素 T-N のような health 系項目を模す）。
    { alias: "全窒素 T-N", dataset: "measurements", variableId: "v.tn", unitId: null, stat: "mean", grain: "fiscal_year" },
  ];

  it("VARIABLE_SHORT: alias と nameJa が同じ（＝短縮の必要が無い）行は含めない", () => {
    const { variableShort } = buildClientVariableMaps(variables, aliases, units);
    // "生物化学的酸素要求量 BOD" -> "BOD" は alias!==nameJa なので短縮対象。
    expect(variableShort["生物化学的酸素要求量 BOD"]).toBe("BOD");
    // "pH" -> "pH" は alias===nameJa なので対象外。
    expect(variableShort.pH).toBeUndefined();
  });

  it("VARIABLE_SHORT / VARIABLE_NOTE: grain='fiscal_year' しか無い variable は対象にしない", () => {
    const { variableShort, variableNote } = buildClientVariableMaps(variables, aliases, units);
    expect(variableShort["全窒素 T-N"]).toBeUndefined();
    expect(variableNote["全窒素 T-N"]).toBeUndefined();
  });

  it("VARIABLE_NOTE: descriptionJa が無い variable は対象にしない", () => {
    const { variableNote } = buildClientVariableMaps(variables, aliases, units);
    expect(variableNote.pH).toBeUndefined();
    expect(variableNote["生物化学的酸素要求量 BOD"]).toBe("生物化学的酸素要求量");
  });

  it("HIGHER_IS_WORSE: higherIsWorse が null の variable は対象にしない", () => {
    const { higherIsWorse } = buildClientVariableMaps(variables, aliases, units);
    expect(higherIsWorse.pH).toBeUndefined();
    expect(higherIsWorse["生物化学的酸素要求量 BOD"]).toBe(true);
  });

  it("VARIABLE_UNIT_FALLBACK: alias 側の unitId が無次元（symbol=null）に解決する行だけを拾う", () => {
    const { variableUnitFallback } = buildClientVariableMaps(variables, aliases, units);
    expect(variableUnitFallback.pH).toBe("");
    expect(variableUnitFallback["生物化学的酸素要求量 BOD"]).toBeUndefined();
  });
});
