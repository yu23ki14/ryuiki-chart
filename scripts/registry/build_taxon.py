"""taxon を作る（docs/plans/PHASE_A.md §A-4・最大の難所。ADR-0019）。

## 実測（PHASE_A.md §A-4 に詳しい。ここでは要点だけ）

`organism_records`（823,692行）と `taxa`（8,585行）は**別の母集団**である。
`organism_records` は GBIF/iNaturalist 由来の学名・taxon_key 中心、`taxa` は神奈川県RL・
環境省RL・外来種リスト由来の和名中心の語彙で、`taxa.gbif_taxon_key` を持つのはそのうち
2,643件だけ、かつ `organism_records` の distinct taxon_key（33,604）とは 818件しか重ならない。
このモジュールは両方を taxon の識別子空間に束ねる。

## F1（phase-b/occurrence-registry）: taxon_id の名前空間を出典ごとに分ける

`organism_records.taxon_key` は出典によって**別の数値空間**が入っている
（`scripts/m03_organisms.py` 参照）: GBIF 行は GBIF の `taxonKey`、iNaturalist 行は
iNaturalist 自身の `taxon.id`。以前はどちらも `taxon_id_gbif(key)`（`common:taxon:gbif.<key>`）
に通していたため、両方の空間が偶然同じ数値を発行した **9件が衝突**していた
（実測。例: `8026` は GBIF では科 *Axiidae*（1行）、iNat では *Corvus macrorhynchos*
（515行）——件数の多い iNat 側の学名がレジストリ行を乗っ取り、GBIF 側の Axiidae という
実体は失われていた）。

`organism_records.source_id` で出典を判定し（`SOURCE_NAMESPACE`）、GBIF 由来は
`common.taxon_id_gbif()`、iNaturalist 由来は `common.taxon_id_inat()`
（`common:taxon:inat.<id>`）に振り分ける。`gbif_taxon_key` 列は本物の GBIF taxonKey の
ときだけ埋める（iNat 由来行は常に NULL）。

**ADR-0004「ID は不変」の例外であることの記録**: `taxon_id` を今この時点で組み替えるのは、
occurrence ファクト（O-1、まだ作っていない）が `taxon_id` を参照する前だから安全にできる。
`web/src/lib/registry/index.ts` の `getTaxonById`/`getTaxonByGbifKey`/`getTaxaByScientificNames`
に呼び出し元が無いこと（grep で確認済み。`web/src/lib/ai/tools.ts` 等どこからも呼ばれていない）、
`scripts/`・`web/scripts/` 側にも `taxon_id`/`gbif_taxon_key` を読む消費者が
このレジストリのビルダー自身（本ファイル・`r01_build_registry.py`・
`scripts/tests/test_r01_invariants.py`・`scripts/r02_resolution_report.py`。いずれも
レジストリを作る/検証する側であって、値を業務ロジックとして使う側ではない）以外に無いことを
確認済み。誰も参照していない今が、ID を動かしても参照が壊れない唯一の時点
（詳細は `docs/plans/PHASE_B_OCCURRENCE.md`、ADR-0019 の日付付き追記）。

**F1の機械検証**（`_assert_known_source_ids` / `_assert_taxon_key_maps_to_single_binom`）:
同じ taxon_id が2つの出典から作られないこと（`_insert()` が taxon_id の重複を検知）、
出典内では taxon_key → 二名法キー（binom）が関数であること（実測: 823,692行中
distinct (source_id, taxon_key) 33,613件で違反0件）。

## 方針（このファイルの実装。F1適用後も骨格は同じ）

1. **occurrence 側は (名前空間, taxon_key) で解決する。** `organism_records` の
   distinct (source_id が示す名前空間, taxon_key) の組ごとに taxon を1行作る。
   代表 `scientific_name` / `rank` / 分類列（kingdom/phylum/class/order/family）は、
   同じ組の中で最も件数の多い組み合わせ（最頻値）を採用する。同数の場合は
   `scientific_name` 昇順→`taxon_rank` 昇順で決定論的にタイブレークする（件数差が出る
   組は33,613件中8件のみで、いずれも大差がつく実質的な最頻値なのでこの規則で十分。
   分類列は同じ taxon_key 内で常に一定であることを実測で確認済みなので、この
   タイブレークは実質的に rank の表記ゆれ——'SPECIES'/'species' 等——だけに効く）。
   `taxon_rank` は原本で大文字/小文字が混在するため小文字に統一するが、値の意味は変えない。

2. **`taxa` のうち `gbif_taxon_key` を持ち、かつ `gbif_match_type='EXACT'`
   （種階級での一致）の行だけを、新しい行を作らず対応する `common:taxon:gbif.<key>`
   に寄せる。** `HIGHERRANK`/`FUZZY`（合わせて300件）は方針3の unresolved 側に回す
   （ADR-0019決定4）。`taxa` 行の EXACT グループが `organism_records` にも
   taxon_key として出現する場合（`n_from_both`）は、分類列（kingdom/phylum/class/
   order/family）は **`organism_records` 側の値を優先する**（GBIF backbone が
   その具体的な taxon_key に対して実際に返した値であり、`taxa`（神奈川県RL等、
   別データセット）が独自に持つ分類列より、その taxon_id が指す実体そのものに近い）。
   `organism_records` に出現しない場合（`n_from_taxa_only`）だけ `taxa` 側代表行の
   分類列を使う。

   **なぜ EXACT 限定に直したか**: `registry/README.md`「`status='needs_review'`/
   `'unresolved'` が意味すること」参照。

3. **`gbif_match_type='EXACT'` でない `taxa` 行は捨てず
   `common:taxon:ryuiki-taxa.<taxa.taxon_id>` で `status='unresolved'` として登録する。**

4. **和名は `registry/taxon/vernacular_ja.csv`（54件）だけを、機械結合ではない
   人間確認済みの和名として GBIF/iNat 由来の行に上書きする。** 突き合わせは学名の
   完全一致ではなく `_binom()`（学名の先頭2語）で行い、両方の名前空間を横断して
   件数最多の (ns, taxon_key) を採用先とする。

5. `taxon_key` を持たない `organism_records` 853行は `taxon_id` 解決の対象外。

## F2（phase-b/occurrence-registry）: kingdom/phylum/class/order/family と taxon_group

v1（`web/scripts/build-biota.mjs` の `org_norm`）は **記録ごと**に分類を補完していた:
`class = COALESCE(記録自身の class, 同じ二名法キーの記録の多数決 class, 同じ属の記録の
多数決 class)`、`kingdom = COALESCE(記録自身, 二名法キーの多数決)`、
`phylum = COALESCE(記録自身, 二名法キーの多数決)`。`order`/`family` は補完しない。

本ビルダーは同じ規則を **taxon（(namespace, taxon_key) の単位）ごとに1回**適用する。
これで v1 と結果が一致する前提は「同じ taxon_key の記録は常に同じ分類列を持つ」こと
（GBIF 行では実測で不整合0。iNat 行は分類列が全行 NULL なので自明に一定）。

多数決の母集団は v1 と同じ **`observed_on IS NOT NULL AND length(observed_on)>=4` の
記録**（`_DATED_POPULATION_WHERE`）に揃える。これは v1 の癖（日付の無い記録は
`org_norm` にそもそも入らない）をこの Slice では意図的に温存する——「v1 の値は
変わらない」が受け入れ条件のため。ADR-0007 原則1（occurrence は日付の無い記録も持つ）
の適用は occurrence ファクトそのものを作る O-1 の仕事で、taxon の分類多数決の母集団
とは別の話（occurrence 側は grid01 の解決で日付の無い記録も含める。
`scripts/registry/build_place.py` の grid01 節参照）。

**同数の決め方（明示の規則）**: 件数降順、同数なら値の昇順（class は
class 昇順→kingdom 昇順、genus 多数決は class 昇順）。実測では二名法キー単位の
多数決（`bc`/`bp`）に同数は無いが、**属単位の多数決（`gc`）に3属が同数**
（異界ホモニム: *Martensia* 紅藻/端脚類、*Stilbum* 菌/ハチ、*Sirosporium*）。
このうち実際に影響するのは1 taxon（GBIF `Sirosporium celtidis`。同数解消規則の
選び方次第で class が `Dothideomycetes` にも `Sordariomycetes` にもなりうる——
v1（ROW_NUMBER の暗黙順）は `Sordariomycetes` を選んでいたが、本規則
（class 昇順）は `Dothideomycetes` を選ぶ。taxon_group はどちらでも「菌類」で
変わらない）。同数だった多数決を使って class が決まった taxon は
`status='needs_review'` にする（`accepted` 系のみ。`unresolved` は元々
「照合できていない」を表しているので上書きしない）。

`taxon_group` は `registry/taxon/taxon_group.yaml`（v1 の `TAXON_GROUP` CASE式を
先勝ち順のまま移したデータ）から機械的に生成する。

## `accepted_taxon_id`（方針6・シノニム解決）

`data/processed/taxon_crosswalk.csv` の `status`/`accepted_scientific_name` 列は、
GBIF `/species/match` のレスポンスの `status`/`scientificName` をそのまま転記した
ものだが、**`accepted_scientific_name` は「マッチしたノード自身の学名」であって
「本当の受理名」ではない**（GBIF の応答に `acceptedUsageKey`/真の受理名が別途
必要だが `c24_taxon_crosswalk.py` はそれを取得していない）。実際に
`status='SYNONYM'` な376件を確認すると、`scientific_name` と
`accepted_scientific_name` が食い違う252件はすべて著者引用の有無だけの差
（例: "Pteropus loochoensis" → "Pteropus loochoensis Gray, 1870"）で、
別の分類群を指す受理名ではなかった。つまり `accepted_taxon_id` に使える
「別の taxon_id への受理名情報」は現状のクロスウォークに**存在しない**。
方針6「情報がある場合だけ埋める、無ければ NULL」に従い、Phase A では
`accepted_taxon_id` を全行 NULL のままにする。
"""
import csv
import pathlib
import sqlite3

import yaml

from registry import common

CROSSWALK_CSV = common.ROOT / common.TAXON_CROSSWALK_CSV_RELPATH
VERNACULAR_CSV = common.ROOT / "registry" / "taxon" / "vernacular_ja.csv"
TAXON_GROUP_YAML = common.ROOT / "registry" / "taxon" / "taxon_group.yaml"

# organism_records.source_id -> taxon_id の名前空間（F1）。他の値が出てきたら
# 黙って混ぜず例外を投げる（_assert_known_source_ids / _load_occurrence_representatives
# の CASE 式がここと同じ対応を持つ。宣言をここ1箇所にまとめる）。
SOURCE_NAMESPACE = {
    "gbif_kanagawa_occurrences": "gbif",
    "inaturalist_kanagawa": "inat",
}

# taxon の列（この順で INSERT する。行の組み立ては dict で行い、最後にこの順へ変換する
# ——列の追加・並べ替えのたびにタプルの位置番号を数え直す事故を避けるため）。
TAXON_COLUMNS = [
    "taxon_id", "scientific_name", "canonical_binomial", "rank",
    "kingdom", "phylum", "class", "order", "family",
    "classification_basis", "taxon_group",
    "gbif_taxon_key", "vernacular_name_ja", "status", "accepted_taxon_id",
]

# v1 (web/scripts/build-biota.mjs org_norm) と同じ母集団: 日付の無い記録は
# 分類の多数決に含めない（モジュール docstring F2参照。v1 の値を変えないための温存）。
_DATED_POPULATION_WHERE = "observed_on IS NOT NULL AND length(observed_on) >= 4"


def _namespace_for_source(source_id: str) -> str:
    ns = SOURCE_NAMESPACE.get(source_id)
    if ns is None:
        raise ValueError(
            f"未知の organism_records.source_id: {source_id!r}（SOURCE_NAMESPACE に無い。"
            "原本に新しい出典が増えた可能性がある。taxon_id の名前空間を追加すること）"
        )
    return ns


def _assert_known_source_ids(ryuiki: sqlite3.Connection) -> None:
    """taxon_key を持つ organism_records の source_id が SOURCE_NAMESPACE に無い値を
    含んでいたら止める（F1）。ここで止めないと `_load_occurrence_representatives()` の
    SQL の CASE 式が未知の source_id を黙って ns=NULL に落とし、taxon_id が組み立てられず
    後段で分かりにくいエラーになる。
    """
    rows = ryuiki.execute(
        "SELECT DISTINCT source_id FROM organism_records WHERE taxon_key IS NOT NULL AND taxon_key <> ''"
    ).fetchall()
    unknown = sorted(r[0] for r in rows if r[0] not in SOURCE_NAMESPACE)
    if unknown:
        raise ValueError(
            "organism_records に taxon_id の名前空間が未定義の source_id がある"
            f"（SOURCE_NAMESPACE に追記すること）: {unknown}"
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

    最頻値（同数は scientific_name → taxon_rank の昇順でタイブレーク）。
    SQL 側で集約するので Python 側で 823,692 行をループしない。
    """
    sql = """
        WITH ns_rows AS (
            SELECT
              CASE source_id
                WHEN 'gbif_kanagawa_occurrences' THEN 'gbif'
                WHEN 'inaturalist_kanagawa' THEN 'inat'
              END AS ns,
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
        ranked AS (
            SELECT ns, taxon_key, scientific_name, taxon_rank,
                   kingdom0, phylum0, class0, order0, family0,
                   ROW_NUMBER() OVER (
                       PARTITION BY ns, taxon_key
                       ORDER BY n DESC, scientific_name ASC, taxon_rank ASC
                   ) AS rn
            FROM counted
        )
        SELECT r.ns AS ns, r.taxon_key AS taxon_key, r.scientific_name AS scientific_name,
               r.taxon_rank AS rank_raw, r.kingdom0 AS kingdom0, r.phylum0 AS phylum0,
               r.class0 AS class0, r.order0 AS order0, r.family0 AS family0,
               t.total_n AS total_n
        FROM ranked r JOIN totals t ON t.ns = r.ns AND t.taxon_key = r.taxon_key
        WHERE r.rn = 1
    """
    out = {}
    for row in ryuiki.execute(sql):
        out[(row["ns"], row["taxon_key"])] = {
            "scientific_name": row["scientific_name"],
            "rank_raw": row["rank_raw"],
            "kingdom0": row["kingdom0"],
            "phylum0": row["phylum0"],
            "class0": row["class0"],
            "order0": row["order0"],
            "family0": row["family0"],
            "total_n": row["total_n"],
        }
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
    with open(CROSSWALK_CSV, encoding="utf-8", newline="") as f:
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
    with open(VERNACULAR_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# F2: kingdom/phylum/class/order/family/taxon_group の多数決
# ---------------------------------------------------------------------------

def _load_binom_class_majority(ryuiki: sqlite3.Connection) -> dict[str, dict]:
    """二名法キー(binom) -> 多数決の (class, kingdom, is_tied)。

    v1 (build-biota.mjs の bc CTE) と同じ母集団・同じ集計（グループは
    (binom, class0, kingdom0) の組、件数降順）に、明示の同数処理を足したもの
    （件数降順、同数なら class 昇順→kingdom 昇順）。実測ではこの多数決に同数は0件。
    """
    binom_expr = _binom_sql("scientific_name")
    sql = f"""
        WITH b AS (
            SELECT {binom_expr} AS binom, NULLIF(class,'') AS class0, NULLIF(kingdom,'') AS kingdom0
            FROM organism_records
            WHERE {_DATED_POPULATION_WHERE}
        ),
        counted AS (
            SELECT binom, class0, kingdom0, COUNT(*) AS n
            FROM b WHERE class0 IS NOT NULL
            GROUP BY binom, class0, kingdom0
        ),
        maxn AS (SELECT binom, MAX(n) AS max_n FROM counted GROUP BY binom),
        tie AS (
            SELECT c.binom AS binom, COUNT(*) AS n_at_max
            FROM counted c JOIN maxn m ON m.binom = c.binom AND m.max_n = c.n
            GROUP BY c.binom
        ),
        ranked AS (
            SELECT binom, class0, kingdom0,
                   ROW_NUMBER() OVER (PARTITION BY binom ORDER BY n DESC, class0 ASC, kingdom0 ASC) AS rn
            FROM counted
        )
        SELECT r.binom AS binom, r.class0 AS class, r.kingdom0 AS kingdom,
               COALESCE(t.n_at_max, 1) > 1 AS is_tied
        FROM ranked r LEFT JOIN tie t ON t.binom = r.binom
        WHERE r.rn = 1
    """
    return {
        row["binom"]: {"class": row["class"], "kingdom": row["kingdom"], "is_tied": bool(row["is_tied"])}
        for row in ryuiki.execute(sql)
    }


def _load_genus_class_majority(ryuiki: sqlite3.Connection) -> dict[str, dict]:
    """属(genus) -> 多数決の (class, is_tied)。v1 の gc CTE と同じ母集団・同じ集計。

    実測で3属が同数（*Martensia*・*Stilbum*・*Sirosporium*。異界ホモニム）。
    """
    binom_expr = _binom_sql("scientific_name")
    genus_expr = "substr(binom,1,CASE WHEN instr(binom,' ')>0 THEN instr(binom,' ')-1 ELSE length(binom) END)"
    sql = f"""
        WITH b AS (
            SELECT {binom_expr} AS binom, NULLIF(class,'') AS class0
            FROM organism_records
            WHERE {_DATED_POPULATION_WHERE}
        ),
        g AS (
            SELECT {genus_expr} AS genus, class0 FROM b
        ),
        counted AS (
            SELECT genus, class0, COUNT(*) AS n FROM g WHERE class0 IS NOT NULL
            GROUP BY genus, class0
        ),
        maxn AS (SELECT genus, MAX(n) AS max_n FROM counted GROUP BY genus),
        tie AS (
            SELECT c.genus AS genus, COUNT(*) AS n_at_max
            FROM counted c JOIN maxn m ON m.genus = c.genus AND m.max_n = c.n
            GROUP BY c.genus
        ),
        ranked AS (
            SELECT genus, class0,
                   ROW_NUMBER() OVER (PARTITION BY genus ORDER BY n DESC, class0 ASC) AS rn
            FROM counted
        )
        SELECT r.genus AS genus, r.class0 AS class, COALESCE(t.n_at_max, 1) > 1 AS is_tied
        FROM ranked r LEFT JOIN tie t ON t.genus = r.genus
        WHERE r.rn = 1
    """
    return {row["genus"]: {"class": row["class"], "is_tied": bool(row["is_tied"])} for row in ryuiki.execute(sql)}


def _load_binom_phylum_majority(ryuiki: sqlite3.Connection) -> dict[str, dict]:
    """二名法キー(binom) -> 多数決の (phylum, is_tied)。v1 の bp CTE と同じ母集団・同じ集計。
    実測ではこの多数決に同数は0件。
    """
    binom_expr = _binom_sql("scientific_name")
    sql = f"""
        WITH b AS (
            SELECT {binom_expr} AS binom, NULLIF(phylum,'') AS phylum0
            FROM organism_records
            WHERE {_DATED_POPULATION_WHERE}
        ),
        counted AS (
            SELECT binom, phylum0, COUNT(*) AS n FROM b WHERE phylum0 IS NOT NULL
            GROUP BY binom, phylum0
        ),
        maxn AS (SELECT binom, MAX(n) AS max_n FROM counted GROUP BY binom),
        tie AS (
            SELECT c.binom AS binom, COUNT(*) AS n_at_max
            FROM counted c JOIN maxn m ON m.binom = c.binom AND m.max_n = c.n
            GROUP BY c.binom
        ),
        ranked AS (
            SELECT binom, phylum0,
                   ROW_NUMBER() OVER (PARTITION BY binom ORDER BY n DESC, phylum0 ASC) AS rn
            FROM counted
        )
        SELECT r.binom AS binom, r.phylum0 AS phylum, COALESCE(t.n_at_max, 1) > 1 AS is_tied
        FROM ranked r LEFT JOIN tie t ON t.binom = r.binom
        WHERE r.rn = 1
    """
    return {row["binom"]: {"phylum": row["phylum"], "is_tied": bool(row["is_tied"])} for row in ryuiki.execute(sql)}


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
    """
    binom = _binom(scientific_name)
    genus = _genus(binom)
    needs_review = False

    if own_class is not None:
        cls = own_class
        basis = "source"
    else:
        bc_entry = bc.get(binom) if binom else None
        if bc_entry is not None:
            cls = bc_entry["class"]
            basis = "binomial_match"
            needs_review = needs_review or bc_entry["is_tied"]
        else:
            gc_entry = gc.get(genus) if genus else None
            if gc_entry is not None:
                cls = gc_entry["class"]
                basis = "genus_match"
                needs_review = needs_review or gc_entry["is_tied"]
            else:
                cls = None
                basis = "unresolved"

    if own_kingdom is not None:
        kdm = own_kingdom
    else:
        bc_entry = bc.get(binom) if binom else None
        kdm = bc_entry["kingdom"] if bc_entry is not None else None

    if own_phylum is not None:
        phy = own_phylum
    else:
        bp_entry = bp.get(binom) if binom else None
        if bp_entry is not None:
            phy = bp_entry["phylum"]
            needs_review = needs_review or bp_entry["is_tied"]
        else:
            phy = None

    return kdm, phy, cls, basis, needs_review


def _load_taxon_group_rules() -> tuple[list[dict], str]:
    """registry/taxon/taxon_group.yaml（v1 の TAXON_GROUP CASE 式を先勝ち順のまま
    データ化したもの）を読む。"""
    with open(TAXON_GROUP_YAML, encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc["rules"], doc["default_label_ja"]


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

    bc = _load_binom_class_majority(ryuiki)
    gc = _load_genus_class_majority(ryuiki)
    bp = _load_binom_phylum_majority(ryuiki)
    group_rules, group_default = _load_taxon_group_rules()
    tied_genus_count = sum(1 for v in gc.values() if v["is_tied"])
    print(
        f"  [taxon] F2 多数決テーブル: 二名法キー(class/kingdom) {len(bc):,} / "
        f"属(class) {len(gc):,}（うち同数 {tied_genus_count}） / 二名法キー(phylum) {len(bp):,}"
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
            vernacular = _pick_taxa_representative(taxa_group, crosswalk_rank)["vernacular"]

        rank = rank_raw.lower() if rank_raw else None
        kdm, phy, cls, basis, needs_review = _resolve_classification(
            scientific_name, own_kingdom, own_phylum, own_class, bc, gc, bp
        )
        basis_counts[basis] = basis_counts.get(basis, 0) + 1
        status = "needs_review" if needs_review else "accepted"
        if needs_review:
            n_needs_review += 1

        _insert(taxon_id, (ns, key), {
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
            "gbif_taxon_key": key if ns == "gbif" else None,
            "vernacular_name_ja": vernacular,
            "status": status,
            "accepted_taxon_id": None,
        })

    print(
        f"  [taxon] gbif/inat行 = {len(rows_by_id):,} "
        f"(occurrence のみ {n_from_occurrence_only:,} / occurrence+taxa {n_from_both:,} / "
        f"taxa のみ {n_from_taxa_only:,})"
    )
    print(f"  [taxon] classification_basis 内訳: {basis_counts}")

    # --- taxa の gbif_match_type != 'EXACT' な行（unresolved） ---------------------
    n_unresolved = 0
    n_unresolved_weak_match = 0
    seen_unresolved: dict = {}
    for row in taxa_rows:
        has_key = bool((row["gbif_taxon_key"] or "").strip())
        if has_key and row["gbif_match_type"] == "EXACT":
            continue  # 方針2で対応する gbif.<key> 行に寄せ済み
        taxon_id = common.taxon_id_unresolved(row["taxon_id"], seen=seen_unresolved)
        scientific_name = row["scientific_name"]
        # unresolved 行も分類列の多数決（bc/gc/bp）は共有する。status='unresolved' は
        # 「GBIF backbone と照合できていない」を表す既存の意味を上書きしないので、
        # needs_review（多数決が同数だった）の情報は basis だけに残し status は
        # 変えない（accepted 系との非対称。関数docstring参照）。
        kdm, phy, cls, basis, _needs_review = _resolve_classification(
            scientific_name, row["kingdom0"], row["phylum0"], row["class0"], bc, gc, bp
        )
        _insert(taxon_id, ("ryuiki-taxa", row["taxon_id"]), {
            "taxon_id": taxon_id,
            "scientific_name": scientific_name,
            "canonical_binomial": _binom(scientific_name),
            "rank": None,
            "kingdom": kdm,
            "phylum": phy,
            "class": cls,
            "order": row["order0"],
            "family": row["family0"],
            "classification_basis": basis,
            "taxon_group": _taxon_group_for(cls, phy, kdm, group_rules, group_default),
            "gbif_taxon_key": None,
            "vernacular_name_ja": row["vernacular_name_ja"],
            "status": "unresolved",
            "accepted_taxon_id": None,
        })
        n_unresolved += 1
        if has_key:
            n_unresolved_weak_match += 1
    print(
        f"  [taxon] taxa 由来 unresolved = {n_unresolved:,} / taxa総数 {len(taxa_rows):,}"
        f"（うち gbif_taxon_key はあるが gbif_match_type が EXACT でない弱い一致: "
        f"{n_unresolved_weak_match:,}）"
    )
    print(f"  [taxon] classification_basis の多数決が同数で status='needs_review' = {n_needs_review:,}")

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
