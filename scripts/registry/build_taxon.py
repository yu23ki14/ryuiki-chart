"""taxon を作る（docs/plans/PHASE_A.md §A-4・最大の難所。ADR-0019）。

`organism_records`（823,692行）と `taxa`（8,585行）は**別の母集団**である。
`organism_records` は GBIF/iNaturalist 由来の学名・taxon_key 中心、`taxa` は神奈川県RL・
環境省RL・外来種リスト由来の和名中心の語彙で、`taxa.gbif_taxon_key` を持つのはそのうち
2,643件だけ、かつ `organism_records` の distinct taxon_key（33,604）とは 818件しか重ならない。
このモジュールは両方を taxon の識別子空間に束ねる。

**taxon_id の名前空間分割（F1）と分類補完（F2）の決定・理由の正は
`docs/adr/0019-taxon-registry.md` の日付付き追記、実測の正は
`docs/plans/PHASE_B_OCCURRENCE.md`。ここには実装に必要な最小限だけを書く**
（同じ経緯があちこちに全文コピーされていた指摘を受けて集約した。/simplify 指摘14）。

## 方針（要点）

1. **occurrence 側は (名前空間, taxon_key) で解決する。** `organism_records.source_id`
   から名前空間を判定する対応表は `scripts/common.py` の `TAXON_KEY_SOURCE_NAMESPACE`
   （収集系の共有モジュール側が正。`scripts/x01_dwca.py` 等レジストリを経由しない
   読み手にも届くようにするため。/code-review 指摘5）。`organism_records` の
   distinct (namespace, taxon_key) の組ごとに taxon を1行作る。代表
   `scientific_name`/`rank`/分類列は、同じ組の中で最も件数の多い組み合わせ
   （最頻値）を採用する。同数の場合は分類列も含めた全タイブレーク列の昇順で
   決定論的に決める（`_load_occurrence_representatives()` docstring参照）。

2. **`taxa` のうち `gbif_taxon_key` を持ち、かつ `gbif_match_type='EXACT'`
   （種階級での一致）の行だけを、新しい行を作らず対応する `common:taxon:gbif.<key>`
   に寄せる。** `HIGHERRANK`/`FUZZY`（合わせて300件）は方針3の unresolved 側に回す
   （ADR-0019決定4）。`organism_records` にも taxon_key として出現する場合
   （`n_from_both`）は、分類列は `organism_records` 側の値を優先する（GBIF backbone
   がその具体的な taxon_key に実際に返した値であり、`taxa` 独自の分類列より実体に
   近いため）。出現しない場合（`n_from_taxa_only`）だけ `taxa` 側代表行の分類列を使う。

3. **`gbif_match_type='EXACT'` でない `taxa` 行は捨てず
   `common:taxon:ryuiki-taxa.<taxa.taxon_id>` で `status='unresolved'` として登録する。**

4. **和名は `registry/taxon/vernacular_ja.csv`（54件）だけを、機械結合ではない
   人間確認済みの和名として GBIF/iNat 由来の行に上書きする。** 突き合わせは学名の
   完全一致ではなく `_binom()`（学名の先頭2語）で行い、両方の名前空間を横断して
   件数最多の (ns, taxon_key) を採用先とする。

5. `taxon_key` を持たない `organism_records` 853行は `taxon_id` 解決の対象外。

## 分類の補完（F2。要点）

v1（`web/scripts/build-biota.mjs` の `org_norm`）は**記録ごと**に分類を補完していた:
`class = COALESCE(記録自身, 二名法キーの多数決, 属の多数決)`、`kingdom`/`phylum` は
`COALESCE(記録自身, 二名法キーの多数決)`。`order`/`family` は補完しない。本ビルダーは
同じ規則を taxon（(namespace, taxon_key) の単位）ごとに1回適用する（前提: 同じ
taxon_key の記録は常に同じ分類列を持つ——実測で確認済み）。多数決の母集団は v1 と
同じ「`observed_on` がある記録」（`_DATED_POPULATION_WHERE`。v1 の値を変えないための
意図的な温存）。

`classification_basis` は `class` の解決経路: `source`（出典が直接持つ）/
`binomial_match`（同じ二名法キーの多数決）/ `genus_match`（同じ属の多数決）/
`no_match`（どちらからも決まらない）。**`status='unresolved'`（GBIF backbone未照合）
とは別の軸の値なので、意味の重複を避けて `no_match` と名付けている**
（旧実装は両方とも文字列 `'unresolved'` で紛らわしかった。/simplify 指摘11）。

**同数の決め方**: 件数降順、同数なら値の昇順。属単位の多数決（`genus_match`）で
選んだ taxon は、次のいずれかに該当すると `status='needs_review'` にする
（`status='unresolved'` の行も対象——backbone未照合と多数決の不確かさは独立の事実
なので、両方起きていれば両方分かるべきだが `status` は単一値のため、より新しい
判定であるこちらを優先する。/code-review 指摘1・6）:
- その属単位の多数決が同数だった（実測で3属。詳細は `docs/plans/PHASE_B_OCCURRENCE.md`）。
- その属自体が複数の class にまたがる（同数でなくても、属という単位が複数の class を
  含む時点で「多数決で選んだ class」の信頼性が低いため。実測件数は
  `docs/plans/PHASE_B_OCCURRENCE.md` 参照）。

`taxon_group` は `registry/taxon/taxon_group.yaml`（v1 の `TAXON_GROUP` CASE式を
先勝ち順のまま移したデータ）から機械的に生成する。

## `accepted_taxon_id`（方針6・シノニム解決）

`data/processed/taxon_crosswalk.csv` の `accepted_scientific_name` は「マッチした
ノード自身の学名」であって「本当の受理名」ではない（`c24_taxon_crosswalk.py` が
GBIF の `acceptedUsageKey` を取得していないため）。使える「別の taxon_id への
受理名情報」が現状存在しないため、`accepted_taxon_id` は全行 NULL のままにする
（詳細は `docs/plans/PHASE_A.md` §A-4）。
"""
import csv
import sqlite3

import yaml

from common import TAXON_KEY_SOURCE_NAMESPACE
from registry import common

CROSSWALK_CSV = common.ROOT / common.TAXON_CROSSWALK_CSV_RELPATH
VERNACULAR_CSV = common.ROOT / "registry" / "taxon" / "vernacular_ja.csv"
TAXON_GROUP_YAML = common.ROOT / "registry" / "taxon" / "taxon_group.yaml"

# taxon の列（この順で INSERT する。行の組み立ては dict で行い、最後にこの順へ変換する
# ——列の追加・並べ替えのたびにタプルの位置番号を数え直す事故を避けるため）。
TAXON_COLUMNS = [
    "taxon_id", "scientific_name", "canonical_binomial", "rank",
    "kingdom", "phylum", "class", "order", "family",
    "classification_basis", "taxon_group",
    "gbif_taxon_key", "vernacular_name_ja", "status", "accepted_taxon_id",
]

# v1 (web/scripts/build-biota.mjs org_norm) と同じ母集団: 日付の無い記録は
# 分類の多数決に含めない（モジュール docstring参照。v1 の値を変えないための温存）。
_DATED_POPULATION_WHERE = "observed_on IS NOT NULL AND length(observed_on) >= 4"


def _namespace_for_source(source_id: str) -> str:
    ns = TAXON_KEY_SOURCE_NAMESPACE.get(source_id)
    if ns is None:
        raise ValueError(
            f"未知の organism_records.source_id: {source_id!r}"
            "（scripts/common.py の TAXON_KEY_SOURCE_NAMESPACE に無い。"
            "原本に新しい出典が増えた可能性がある。taxon_id の名前空間を追加すること）"
        )
    return ns


def _namespace_case_sql(column: str) -> str:
    """`column`（例: `source_id`）から taxon_id の名前空間を引く SQL の CASE 式を、
    `TAXON_KEY_SOURCE_NAMESPACE`（正）から組み立てる（SQL 側にハードコードした
    対応が Python 側の辞書とズレる事故を防ぐ。/code-review 指摘5）。
    """
    branches = " ".join(
        f"WHEN '{src.replace(chr(39), chr(39) * 2)}' THEN '{ns}'"
        for src, ns in TAXON_KEY_SOURCE_NAMESPACE.items()
    )
    return f"CASE {column} {branches} END"


def _assert_known_source_ids(ryuiki: sqlite3.Connection) -> None:
    """taxon_key を持つ organism_records の source_id が TAXON_KEY_SOURCE_NAMESPACE に
    無い値を含んでいたら止める（F1）。ここで止めないと `_load_occurrence_representatives()`
    の SQL の CASE 式が未知の source_id を黙って ns=NULL に落とし、taxon_id が組み立て
    られず後段で分かりにくいエラーになる。
    """
    rows = ryuiki.execute(
        "SELECT DISTINCT source_id FROM organism_records WHERE taxon_key IS NOT NULL AND taxon_key <> ''"
    ).fetchall()
    unknown = sorted(r[0] for r in rows if r[0] not in TAXON_KEY_SOURCE_NAMESPACE)
    if unknown:
        raise ValueError(
            "organism_records に taxon_id の名前空間が未定義の source_id がある"
            f"（scripts/common.py の TAXON_KEY_SOURCE_NAMESPACE に追記すること）: {unknown}"
        )


def _binom(name: str | None) -> str | None:
    """学名の先頭2語（属+種）。web/scripts/build-biota.mjs の BINOM と同じ規則。"""
    if not name:
        return None
    toks = name.split(" ")
    if len(toks) < 2:
        return name
    return f"{toks[0]} {toks[1]}"


def _genus(binom: str | None) -> str | None:
    """binom の先頭語（属）。web/scripts/build-biota.mjs の gc CTE の g と同じ規則。"""
    if not binom:
        return None
    return binom.split(" ")[0]


def _binom_sql(col: str) -> str:
    """SQL 版の `_binom()`。web/scripts/build-biota.mjs の `BINOM(col)` と同じ式
    （Python 側と SQL 側で規則がズレないよう、どちらも「先頭2語」を同じ手順で組み立てる）。
    """
    return (
        f"CASE WHEN instr({col},' ')=0 THEN {col} "
        f"ELSE substr({col},1,instr({col},' ')-1)||' '||"
        f"CASE WHEN instr(substr({col},instr({col},' ')+1),' ')=0 "
        f"THEN substr({col},instr({col},' ')+1) "
        f"ELSE substr(substr({col},instr({col},' ')+1),1,"
        f"instr(substr({col},instr({col},' ')+1),' ')-1) END END"
    )


def _assert_taxon_key_maps_to_single_binom(ryuiki: sqlite3.Connection) -> None:
    """出典内では taxon_key -> 二名法キー(binom) が関数であることを機械検証する（F1）。

    実測（823,692行、distinct (source_id, taxon_key) 33,613件）では違反0件。
    この前提が崩れると「同じ taxon_key なのに代表の学名が記録によって違う」ことになり、
    `_load_occurrence_representatives()` の最頻値選びが「本当は複数の実体が同じキーに
    衝突している」ことを黙って隠してしまう。将来データが増えて崩れた場合に黙って通さない
    ためのガード（`docs/COLLECTOR_CONTRACT.md`）。
    """
    rows = ryuiki.execute(
        "SELECT DISTINCT source_id, taxon_key, scientific_name FROM organism_records "
        "WHERE taxon_key IS NOT NULL AND taxon_key <> ''"
    ).fetchall()
    binoms_by_key: dict[tuple[str, str], set] = {}
    for source_id, taxon_key, scientific_name in rows:
        ns = _namespace_for_source(source_id)
        binoms_by_key.setdefault((ns, taxon_key), set()).add(_binom(scientific_name))
    violations = {k: v for k, v in binoms_by_key.items() if len(v) > 1}
    if violations:
        sample = "; ".join(
            f"{k}: {sorted(x for x in v if x is not None)[:3]}" for k, v in list(violations.items())[:5]
        )
        raise AssertionError(
            f"出典内で taxon_key -> 二名法キーが関数でない組が {len(violations):,} 件ある"
            f"（F1の前提が崩れている）。例: {sample}"
        )
    print(f"  [taxon] F1機械検証OK: 出典内で taxon_key→二名法キーが関数（{len(binoms_by_key):,}組）")


def _load_occurrence_representatives(ryuiki: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """distinct (名前空間, taxon_key) ごとの代表 (scientific_name, rank, 分類列) と全体件数。

    最頻値（同数は scientific_name → taxon_rank → 分類列（kingdom/phylum/class/order/
    family）の昇順でタイブレーク）。タイブレーク列は `counted` の GROUP BY キーと
    完全に一致する（`ns`/`taxon_key` を除く全列）ため、同じ (ns, taxon_key) 内で
    2つの `counted` 行が全タイブレーク列で一致することは無く、順序は必ず一意に決まる
    （/code-review 指摘3）。

    それでも「最頻値の件数そのものが複数の候補で並ぶ」（=選択に実質的な理由が無い
    状態）が無いことを別途 assert する。実測0件。

    SQL 側で集約するので Python 側で 823,692 行をループしない。
    """
    ns_case = _namespace_case_sql("source_id")
    sql = f"""
        WITH ns_rows AS (
            SELECT
              {ns_case} AS ns,
              taxon_key, scientific_name, taxon_rank,
              NULLIF(kingdom,'') AS kingdom0, NULLIF(phylum,'') AS phylum0,
              NULLIF(class,'') AS class0, NULLIF("order",'') AS order0,
              NULLIF(family,'') AS family0
            FROM organism_records
            WHERE taxon_key IS NOT NULL AND taxon_key <> ''
        ),
        counted AS (
            SELECT ns, taxon_key, scientific_name, taxon_rank,
                   kingdom0, phylum0, class0, order0, family0, COUNT(*) AS n
            FROM ns_rows
            GROUP BY ns, taxon_key, scientific_name, taxon_rank,
                     kingdom0, phylum0, class0, order0, family0
        ),
        totals AS (
            SELECT ns, taxon_key, SUM(n) AS total_n FROM counted GROUP BY ns, taxon_key
        ),
        maxn AS (SELECT ns, taxon_key, MAX(n) AS max_n FROM counted GROUP BY ns, taxon_key),
        tie AS (
            SELECT c.ns AS ns, c.taxon_key AS taxon_key, COUNT(*) AS n_at_max
            FROM counted c JOIN maxn m ON m.ns = c.ns AND m.taxon_key = c.taxon_key AND m.max_n = c.n
            GROUP BY c.ns, c.taxon_key
        ),
        ranked AS (
            SELECT ns, taxon_key, scientific_name, taxon_rank,
                   kingdom0, phylum0, class0, order0, family0,
                   ROW_NUMBER() OVER (
                       PARTITION BY ns, taxon_key
                       ORDER BY n DESC, scientific_name ASC, taxon_rank ASC,
                                kingdom0 ASC, phylum0 ASC, class0 ASC, order0 ASC, family0 ASC
                   ) AS rn
            FROM counted
        )
        SELECT r.ns AS ns, r.taxon_key AS taxon_key, r.scientific_name AS scientific_name,
               r.taxon_rank AS rank_raw, r.kingdom0 AS kingdom0, r.phylum0 AS phylum0,
               r.class0 AS class0, r.order0 AS order0, r.family0 AS family0,
               t.total_n AS total_n, tie.n_at_max AS n_at_max
        FROM ranked r
        JOIN totals t ON t.ns = r.ns AND t.taxon_key = r.taxon_key
        JOIN tie ON tie.ns = r.ns AND tie.taxon_key = r.taxon_key
        WHERE r.rn = 1
    """
    out = {}
    top_count_ties: list[tuple[str, str, int]] = []
    for row in ryuiki.execute(sql):
        key = (row["ns"], row["taxon_key"])
        out[key] = {
            "scientific_name": row["scientific_name"],
            "rank_raw": row["rank_raw"],
            "kingdom0": row["kingdom0"],
            "phylum0": row["phylum0"],
            "class0": row["class0"],
            "order0": row["order0"],
            "family0": row["family0"],
            "total_n": row["total_n"],
        }
        if row["n_at_max"] > 1:
            top_count_ties.append((row["ns"], row["taxon_key"], row["n_at_max"]))
    if top_count_ties:
        sample = ", ".join(f"{ns}.{key}(候補{n}件)" for ns, key, n in top_count_ties[:10])
        raise AssertionError(
            f"taxon_key ごとの代表選びで最頻値の件数が同数の候補が並ぶものが "
            f"{len(top_count_ties):,} 件ある（分類列を含めた並びで決定的に選んではいるが、"
            f"選択に実質的な理由が無い状態。例: {sample}）"
        )
    print(f"  [taxon] F2機械検証OK: taxon_key ごとの代表選びに件数同数の候補は無い（{len(out):,}件確認）")
    return out


def _load_taxa(ryuiki: sqlite3.Connection) -> list[sqlite3.Row]:
    return ryuiki.execute(
        "SELECT taxon_id, scientific_name, vernacular_name_ja, gbif_taxon_key, "
        "gbif_match_type, NULLIF(kingdom,'') AS kingdom0, NULLIF(phylum,'') AS phylum0, "
        'NULLIF(class,\'\') AS class0, NULLIF("order",\'\') AS order0, '
        "NULLIF(family,'') AS family0 FROM taxa"
    ).fetchall()


def _load_crosswalk_rank() -> dict[str, str]:
    """data/processed/taxon_crosswalk.csv の taxon_id -> rank（GBIF が実際に一致させた階級）。

    taxa.gbif_taxon_key を持つ全2,643行がここに taxon_id で引ける（実測で確認済み）。
    """
    if not CROSSWALK_CSV.exists():
        raise FileNotFoundError(
            f"taxon_crosswalk.csv が無い: {CROSSWALK_CSV}\n"
            "scripts/c24_taxon_crosswalk.py の成果物。再生成するにはそのスクリプトを実行する"
            "（GBIF API 呼び出しを伴うため、通常はリポジトリの成果物をそのまま使う）。"
        )
    out = {}
    with CROSSWALK_CSV.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            out[row["taxon_id"]] = row.get("rank") or None
    return out


def _group_taxa_by_gbif_key(taxa_rows) -> dict[str, list[dict]]:
    """`gbif_match_type='EXACT'` の taxa 行だけを gbif_taxon_key でグループ化する。

    HIGHERRANK/FUZZY（キーはあるが種以下まで一致していない）はここに含めない
    （モジュール docstring 方針2）。呼び出し側はこの辞書に無いキーを
    「EXACT で寄せられる taxa 行が無い」とみなす。分類列（kingdom0 等）も保持する
    （`organism_records` にキーが出現しない taxa-only のケースだけがこれを使う）。
    """
    groups: dict[str, list[dict]] = {}
    for row in taxa_rows:
        if row["gbif_match_type"] != "EXACT":
            continue
        key = (row["gbif_taxon_key"] or "").strip()
        if not key:
            continue
        groups.setdefault(key, []).append(
            {
                "taxon_id": row["taxon_id"],
                "scientific_name": row["scientific_name"],
                "vernacular_name_ja": row["vernacular_name_ja"],
                "gbif_match_type": row["gbif_match_type"],
                "kingdom0": row["kingdom0"],
                "phylum0": row["phylum0"],
                "class0": row["class0"],
                "order0": row["order0"],
                "family0": row["family0"],
            }
        )
    return groups


def _pick_taxa_representative(rows: list[dict], crosswalk_rank: dict[str, str]) -> dict:
    """EXACT の taxa 行の集まり（`_group_taxa_by_gbif_key` の出力）から、
    代表 (scientific_name, rank, 分類列) と、和名が食い違っていない場合だけの
    vernacular_name_ja を選ぶ（モジュール docstring 方針2）。
    全行が EXACT である前提だが、タイブレークは `taxon_id` 昇順の先頭。
    """
    rep = min(rows, key=lambda r: r["taxon_id"])
    rank_raw = crosswalk_rank.get(rep["taxon_id"])

    vernaculars = {r["vernacular_name_ja"] for r in rows if r["vernacular_name_ja"]}
    vernacular = next(iter(vernaculars)) if len(vernaculars) == 1 else None
    return {
        "scientific_name": rep["scientific_name"],
        "rank_raw": rank_raw,
        "kingdom0": rep["kingdom0"],
        "phylum0": rep["phylum0"],
        "class0": rep["class0"],
        "order0": rep["order0"],
        "family0": rep["family0"],
        "vernacular": vernacular,
    }


def _load_vernacular_overrides() -> list[dict]:
    if not VERNACULAR_CSV.exists():
        raise FileNotFoundError(
            f"人手確認済み和名 CSV が無い: {VERNACULAR_CSV}\n"
            "domain.ts の NAME_JA 54件をそのまま複製したもの。新規に増減しない。"
        )
    with VERNACULAR_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# F2: kingdom/phylum/class/order/family/taxon_group の多数決
# ---------------------------------------------------------------------------

# 3つの多数決（二名法キー×class、属×class、二名法キー×phylum）が共有する一時テーブル。
# 以前は3つの関数がそれぞれ独立に organism_records をスキャンし、二名法キー(binom)を
# 計算し直していた（実測: フルビルド時間の半分近くを占めていた）。ここで1回だけ
# 作り、3つの多数決はこのテーブルから集計する（/code-review 指摘8）。
_POPULATION_TEMP_TABLE = "_classification_population"


def _create_classification_population(ryuiki: sqlite3.Connection) -> None:
    """`_POPULATION_TEMP_TABLE` を作る。母集団は v1 と同じ「`observed_on` がある記録」
    （モジュール docstring 参照）。二名法キー(binom)と属(genus)をここで1回だけ計算する。
    """
    ryuiki.execute(f"DROP TABLE IF EXISTS temp.{_POPULATION_TEMP_TABLE}")
    binom_expr = _binom_sql("scientific_name")
    genus_expr = "substr(binom,1,CASE WHEN instr(binom,' ')>0 THEN instr(binom,' ')-1 ELSE length(binom) END)"
    ryuiki.execute(f"""
        CREATE TEMP TABLE {_POPULATION_TEMP_TABLE} AS
        SELECT binom, {genus_expr} AS genus, class0, kingdom0, phylum0
        FROM (
            SELECT {binom_expr} AS binom, NULLIF(class,'') AS class0,
                   NULLIF(kingdom,'') AS kingdom0, NULLIF(phylum,'') AS phylum0
            FROM organism_records
            WHERE {_DATED_POPULATION_WHERE}
        )
    """)


def _majority_vote(
    ryuiki: sqlite3.Connection,
    *,
    group_col: str,
    vote_col: str,
    companion_cols: tuple[str, ...] = (),
) -> dict[str, dict]:
    """`_POPULATION_TEMP_TABLE` を `group_col` でグループ化し、`vote_col` の最頻値を
    多数決で選ぶ（v1 の bc/gc/bp の3つの CTE を1つの関数に統合したもの。
    /simplify 指摘9）。同数は件数降順のあと `vote_col`→`companion_cols` の昇順で
    決定論的にタイブレークする。`companion_cols` は `vote_col` と同じグループ化キー
    （同じ `(group_col, vote_col, *companion_cols)` の組）で件数を数える同伴列
    （例: kingdom は class と同じ (binom, class0, kingdom0) の組で数える。v1 の
    bc CTE と同じ挙動）。

    戻り値: `{group値: {vote_col: 値, **companion_colsの値, "is_tied": bool}}`。
    """
    cols = (vote_col,) + companion_cols
    collist = ", ".join(cols)
    tie_break = ", ".join(f"{c} ASC" for c in cols)
    sql = f"""
        WITH counted AS (
            SELECT {group_col} AS g, {collist}, COUNT(*) AS n
            FROM {_POPULATION_TEMP_TABLE}
            WHERE {vote_col} IS NOT NULL
            GROUP BY {group_col}, {collist}
        ),
        maxn AS (SELECT g, MAX(n) AS max_n FROM counted GROUP BY g),
        tie AS (
            SELECT c.g AS g, COUNT(*) AS n_at_max
            FROM counted c JOIN maxn m ON m.g = c.g AND m.max_n = c.n
            GROUP BY c.g
        ),
        ranked AS (
            SELECT g, {collist},
                   ROW_NUMBER() OVER (PARTITION BY g ORDER BY n DESC, {tie_break}) AS rn
            FROM counted
        )
        SELECT r.g AS g, {", ".join(f"r.{c} AS {c}" for c in cols)},
               COALESCE(t.n_at_max, 1) > 1 AS is_tied
        FROM ranked r LEFT JOIN tie t ON t.g = r.g
        WHERE r.rn = 1
    """
    out = {}
    for row in ryuiki.execute(sql):
        entry = {c: row[c] for c in cols}
        entry["is_tied"] = bool(row["is_tied"])
        out[row["g"]] = entry
    return out


def _load_multi_class_genera(ryuiki: sqlite3.Connection) -> set[str]:
    """属の多数決（genus_match）で使う属のうち、複数の class にまたがるものを返す。

    同数でなくても、属という単位そのものが複数の class を含む場合（例: *Pieris* は
    チョウ目 Insecta が優勢だが被子植物 Magnoliopsida も一定数混ざる、異名同属の
    ホモニム）、多数決で選んだ class の信頼性は低い。該当する taxon は
    `status='needs_review'` にする（/code-review 指摘6。件数は build() が print する）。
    """
    sql = f"""
        SELECT genus FROM {_POPULATION_TEMP_TABLE}
        WHERE class0 IS NOT NULL
        GROUP BY genus
        HAVING COUNT(DISTINCT class0) > 1
    """
    return {row["genus"] for row in ryuiki.execute(sql)}


def _resolve_classification(
    scientific_name: str | None,
    own_kingdom: str | None,
    own_phylum: str | None,
    own_class: str | None,
    bc: dict[str, dict],
    gc: dict[str, dict],
    bp: dict[str, dict],
) -> tuple[str | None, str | None, str | None, str, bool]:
    """(kingdom, phylum, class, classification_basis, needs_review) を返す。

    v1 (org_norm) の COALESCE 規則（own -> 二名法多数決 -> 属多数決[class のみ]）を
    taxon 単位で適用する。`classification_basis` は class の解決経路。kingdom/phylum は
    それぞれ独立の COALESCE チェーンを持つ（v1 と同じ——kingdom は bc からしか
    補完されず gc からは補完されない。phylum は bp からのみ）。

    `bc.get(binom)` は class と kingdom の両方の解決に使うので1回だけ計算する
    （/simplify 指摘12）。bc の多数決が同数だった場合、class・kingdom どちらの
    解決経路で使っても needs_review を立てる（/code-review 指摘2。以前は
    own_class が無く own_kingdom も無いときしか bc の tie を見ておらず、
    「class は自前・kingdom だけ bc 頼り」のケースで kingdom 側の同数を見逃していた）。
    """
    binom = _binom(scientific_name)
    genus = _genus(binom)
    needs_review = False
    bc_entry = bc.get(binom) if binom else None

    if own_class is not None:
        cls = own_class
        basis = "source"
    elif bc_entry is not None:
        cls = bc_entry["class0"]
        basis = "binomial_match"
        needs_review = needs_review or bc_entry["is_tied"]
    else:
        gc_entry = gc.get(genus) if genus else None
        if gc_entry is not None:
            cls = gc_entry["class0"]
            basis = "genus_match"
            needs_review = needs_review or gc_entry["is_tied"] or gc_entry["multi_class"]
        else:
            cls = None
            basis = "no_match"

    if own_kingdom is not None:
        kdm = own_kingdom
    elif bc_entry is not None:
        kdm = bc_entry["kingdom0"]
        needs_review = needs_review or bc_entry["is_tied"]
    else:
        kdm = None

    if own_phylum is not None:
        phy = own_phylum
    else:
        bp_entry = bp.get(binom) if binom else None
        if bp_entry is not None:
            phy = bp_entry["phylum0"]
            needs_review = needs_review or bp_entry["is_tied"]
        else:
            phy = None

    return kdm, phy, cls, basis, needs_review


def _load_taxon_group_rules() -> tuple[list[dict], str]:
    """registry/taxon/taxon_group.yaml（v1 の TAXON_GROUP CASE 式を先勝ち順のまま
    データ化したもの）を読む。先勝ちの表なので、同じ条件(match)が2回登場すると
    片方が黙って無効になる——`build_place._load_zone_yaml()`/
    `build_caveat._load_caveat_yaml()` と同じ流儀で重複を検知する（/simplify 指摘13）。
    """
    with TAXON_GROUP_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    rules = doc["rules"]
    keys = [_match_key(rule["match"]) for rule in rules]
    dupes = sorted({k for k in keys if keys.count(k) > 1}, key=repr)
    assert not dupes, f"registry/taxon/taxon_group.yaml の match が重複している: {dupes}"
    return rules, doc["default_label_ja"]


def _match_key(match: dict) -> tuple:
    """taxon_group.yaml の `match` 辞書を、重複検知用の比較可能なタプルに変える。
    値が配列の場合は要素の並びに意味が無い（IN 相当）ので、ソートして正規化する
    （`None` は文字列と比較できないため `(値がNoneか, 値)` をキーにする）。
    """
    def norm(v):
        if isinstance(v, list):
            return tuple(sorted(v, key=lambda x: (x is None, x)))
        return v

    return tuple((k, norm(v)) for k, v in sorted(match.items()))


def _rule_matches(value: str | None, cond) -> bool:
    """cond が配列なら「そのいずれかに一致（IN 相当）」。配列内の None は
    「NULL または空文字」を表す（呼び出し側で既に空文字を None に正規化済みなので、
    ここでの None は「値が無い」の1通りだけを指す）。配列でなければ単一値の一致。
    """
    if isinstance(cond, list):
        return value in cond
    return value == cond


def _taxon_group_for(cls_: str | None, phy_: str | None, kdm_: str | None, rules, default_label: str) -> str:
    ctx = {"class": cls_, "phylum": phy_, "kingdom": kdm_}
    for rule in rules:
        match = rule["match"]
        if all(_rule_matches(ctx[key], cond) for key, cond in match.items()):
            return rule["label_ja"]
    return default_label


def _build_taxon_row(
    taxon_id: str,
    scientific_name: str | None,
    kdm: str | None,
    phy: str | None,
    cls: str | None,
    own_order: str | None,
    own_family: str | None,
    basis: str,
    group_rules,
    group_default: str,
    *,
    rank: str | None,
    gbif_taxon_key: str | None,
    vernacular_name_ja: str | None,
    status: str,
) -> dict:
    """taxon 行の共通構築（occurrence/taxa 両ループが使う。/simplify 指摘10）。
    2箇所でほぼ同じ15キーの dict リテラルを書いていたのをここに集約した。
    """
    return {
        "taxon_id": taxon_id,
        "scientific_name": scientific_name,
        "canonical_binomial": _binom(scientific_name),
        "rank": rank,
        "kingdom": kdm,
        "phylum": phy,
        "class": cls,
        "order": own_order,
        "family": own_family,
        "classification_basis": basis,
        "taxon_group": _taxon_group_for(cls, phy, kdm, group_rules, group_default),
        "gbif_taxon_key": gbif_taxon_key,
        "vernacular_name_ja": vernacular_name_ja,
        "status": status,
        "accepted_taxon_id": None,
    }


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {'taxon': 挿入した行数}。診断情報は print で出す（r01 の合計行数計算を
    汚さないため、返り値には含めない）。
    """
    ryuiki = src["ryuiki"]

    _assert_known_source_ids(ryuiki)
    _assert_taxon_key_maps_to_single_binom(ryuiki)

    occ = _load_occurrence_representatives(ryuiki)
    taxa_rows = _load_taxa(ryuiki)
    crosswalk_rank = _load_crosswalk_rank()
    taxa_by_key = _group_taxa_by_gbif_key(taxa_rows)

    _create_classification_population(ryuiki)
    bc = _majority_vote(ryuiki, group_col="binom", vote_col="class0", companion_cols=("kingdom0",))
    gc = _majority_vote(ryuiki, group_col="genus", vote_col="class0")
    bp = _majority_vote(ryuiki, group_col="binom", vote_col="phylum0")
    multi_class_genera = _load_multi_class_genera(ryuiki)
    for genus, entry in gc.items():
        entry["multi_class"] = genus in multi_class_genera
    group_rules, group_default = _load_taxon_group_rules()

    tied_genus_count = sum(1 for v in gc.values() if v["is_tied"])
    print(
        f"  [taxon] F2 多数決テーブル: 二名法キー(class/kingdom) {len(bc):,} / "
        f"属(class) {len(gc):,}（うち同数 {tied_genus_count} / 複数classにまたがる "
        f"{len(multi_class_genera):,}） / 二名法キー(phylum) {len(bp):,}"
    )

    # --- 診断: organism_records の taxon_key 解決率 -------------------------------
    total_org = ryuiki.execute("SELECT COUNT(*) FROM organism_records").fetchone()[0]
    unresolved_org, unresolved_by_source_rows = common.count_and_breakdown(
        ryuiki, "organism_records", "taxon_key IS NULL OR taxon_key=''", "source_id"
    )
    resolved_org = total_org - unresolved_org
    unresolved_by_source = dict(unresolved_by_source_rows)
    print(
        f"  [taxon] organism_records {total_org:,}行 -> taxon_key解決 {resolved_org:,}行 "
        f"({resolved_org / total_org * 100:.2f}%)。未解決 {unresolved_org:,}行 "
        f"内訳: {unresolved_by_source}"
    )
    n_by_ns = {"gbif": 0, "inat": 0}
    for ns, _key in occ.keys():
        n_by_ns[ns] += 1
    print(f"  [taxon] distinct (namespace, taxon_key) = {len(occ):,}（gbif {n_by_ns['gbif']:,} / inat {n_by_ns['inat']:,}）")

    # --- 行の組み立て --------------------------------------------------------------
    rows_by_id: dict[str, dict] = {}
    origin_by_id: dict[str, tuple] = {}

    def _insert(taxon_id: str, origin: tuple, fields: dict) -> None:
        if taxon_id in rows_by_id:
            raise ValueError(
                f"taxon_id 衝突: {taxon_id!r} が複数の出典から作られた"
                f"（{origin_by_id[taxon_id]!r} と {origin!r}）。F1の名前空間分離が破れている。"
            )
        rows_by_id[taxon_id] = fields
        origin_by_id[taxon_id] = origin

    all_keys = sorted(set(occ.keys()) | {("gbif", k) for k in taxa_by_key.keys()})
    n_from_occurrence_only = 0
    n_from_both = 0
    n_from_taxa_only = 0
    n_needs_review = 0
    basis_counts: dict[str, int] = {}

    for ns, key in all_keys:
        taxon_id = common.taxon_id_gbif(key) if ns == "gbif" else common.taxon_id_inat(key)
        taxa_group = taxa_by_key.get(key) if ns == "gbif" else None

        occ_info = occ.get((ns, key))
        rep = None
        if occ_info is not None:
            # organism_records 側の分類列を優先する（GBIF backbone がその taxon_key に
            # 実際に返した値。taxa 側の分類列より実体に近い。モジュール docstring 方針2）。
            scientific_name = occ_info["scientific_name"]
            rank_raw = occ_info["rank_raw"]
            own_kingdom, own_phylum, own_class = occ_info["kingdom0"], occ_info["phylum0"], occ_info["class0"]
            own_order, own_family = occ_info["order0"], occ_info["family0"]
            if taxa_group is not None:
                n_from_both += 1
            else:
                n_from_occurrence_only += 1
        else:
            rep = _pick_taxa_representative(taxa_group, crosswalk_rank)
            scientific_name, rank_raw = rep["scientific_name"], rep["rank_raw"]
            own_kingdom, own_phylum, own_class = rep["kingdom0"], rep["phylum0"], rep["class0"]
            own_order, own_family = rep["order0"], rep["family0"]
            n_from_taxa_only += 1

        vernacular = None
        if taxa_group is not None:
            # rep は occ_info が None のときだけ計算済み（上の分岐）。occ_info が
            # あるとき（n_from_both）は taxa 側の代表をここで初めて要る
            # （/simplify 指摘12。同じ引数での2回呼び出しを避ける）。
            vernacular = (rep or _pick_taxa_representative(taxa_group, crosswalk_rank))["vernacular"]

        rank = rank_raw.lower() if rank_raw else None
        kdm, phy, cls, basis, needs_review = _resolve_classification(
            scientific_name, own_kingdom, own_phylum, own_class, bc, gc, bp
        )
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        status = "needs_review" if needs_review else "accepted"
        if needs_review:
            n_needs_review += 1

        _insert(taxon_id, (ns, key), _build_taxon_row(
            taxon_id, scientific_name, kdm, phy, cls, own_order, own_family, basis,
            group_rules, group_default,
            rank=rank, gbif_taxon_key=(key if ns == "gbif" else None),
            vernacular_name_ja=vernacular, status=status,
        ))

    print(
        f"  [taxon] gbif/inat行 = {len(rows_by_id):,} "
        f"(occurrence のみ {n_from_occurrence_only:,} / occurrence+taxa {n_from_both:,} / "
        f"taxa のみ {n_from_taxa_only:,})"
    )
    print(f"  [taxon] classification_basis 内訳: {basis_counts}")

    # --- taxa の gbif_match_type != 'EXACT' な行（unresolved） ---------------------
    n_unresolved = 0
    n_unresolved_weak_match = 0
    n_unresolved_needs_review = 0
    seen_unresolved: dict = {}
    for row in taxa_rows:
        has_key = bool((row["gbif_taxon_key"] or "").strip())
        if has_key and row["gbif_match_type"] == "EXACT":
            continue  # 方針2で対応する gbif.<key> 行に寄せ済み
        taxon_id = common.taxon_id_unresolved(row["taxon_id"], seen=seen_unresolved)
        scientific_name = row["scientific_name"]
        kdm, phy, cls, basis, needs_review = _resolve_classification(
            scientific_name, row["kingdom0"], row["phylum0"], row["class0"], bc, gc, bp
        )
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        # unresolved（GBIF backbone未照合）と needs_review（分類の多数決が不確か）は
        # 別軸の事実だが status は単一値なので、より新しい判定である needs_review を
        # 優先する（/code-review 指摘1。以前は無条件で 'unresolved' にしており、
        # 例えば *Martensia flabelliformis*（属の多数決が紅藻2件/端脚類2件の同数）
        # のような taxon_group が丸ごと変わりうるケースが可視化されていなかった）。
        status = "needs_review" if needs_review else "unresolved"
        if needs_review:
            n_unresolved_needs_review += 1
        _insert(taxon_id, ("ryuiki-taxa", row["taxon_id"]), _build_taxon_row(
            taxon_id, scientific_name, kdm, phy, cls, row["order0"], row["family0"], basis,
            group_rules, group_default,
            rank=None, gbif_taxon_key=None,
            vernacular_name_ja=row["vernacular_name_ja"], status=status,
        ))
        n_unresolved += 1
        if has_key:
            n_unresolved_weak_match += 1
    print(
        f"  [taxon] taxa 由来 unresolved = {n_unresolved:,} / taxa総数 {len(taxa_rows):,}"
        f"（うち gbif_taxon_key はあるが gbif_match_type が EXACT でない弱い一致: "
        f"{n_unresolved_weak_match:,} / 分類の多数決が不確かで status='needs_review' に"
        f"なったもの: {n_unresolved_needs_review:,}）"
    )
    n_needs_review += n_unresolved_needs_review
    print(f"  [taxon] classification_basis 内訳（unresolved含む全体）: {basis_counts}")
    print(f"  [taxon] status='needs_review'（accepted系 + unresolved系）合計 = {n_needs_review:,}")

    # --- NAME_JA（人手確認済み54件）を binom で上書き（gbif/inat 両方の名前空間を横断） ---
    overrides = _load_vernacular_overrides()
    total_by_key = {k: v["total_n"] for k, v in occ.items()}
    binom_index: dict[str, list[tuple[str, str]]] = {}
    for (ns, key), info in occ.items():
        b = _binom(info["scientific_name"])
        if b:
            binom_index.setdefault(b, []).append((ns, key))

    n_applied = 0
    for ov in overrides:
        name = ov["scientific_name"]
        candidates = binom_index.get(name, [])
        if not candidates:
            print(f"  [taxon][WARN] NAME_JA '{name}' に一致する taxon_key が無い（未適用）")
            continue
        winner = max(candidates, key=lambda k: (total_by_key[k], k))
        winner_taxon_id = common.taxon_id_gbif(winner[1]) if winner[0] == "gbif" else common.taxon_id_inat(winner[1])
        rows_by_id[winner_taxon_id]["vernacular_name_ja"] = ov["vernacular_name_ja"]
        n_applied += 1
    print(f"  [taxon] NAME_JA 適用 = {n_applied:,} / {len(overrides):,}")

    n_vernacular = sum(1 for r in rows_by_id.values() if r["vernacular_name_ja"])
    print(f"  [taxon] 和名が付いた行 = {n_vernacular:,}")

    n = common.insert_many(
        conn,
        "taxon",
        TAXON_COLUMNS,
        ([r[col] for col in TAXON_COLUMNS] for r in rows_by_id.values()),
    )
    return {"taxon": n}
