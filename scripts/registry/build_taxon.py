"""taxon を作る（docs/plans/PHASE_A.md §A-4・最大の難所。ADR-0019）。

## 実測（PHASE_A.md §A-4 に詳しい。ここでは要点だけ）

`organism_records`（823,692行）と `taxa`（8,585行）は**別の母集団**である。
`organism_records` は GBIF 由来の学名・taxon_key 中心、`taxa` は神奈川県RL・環境省RL・
外来種リスト由来の和名中心の語彙で、`taxa.gbif_taxon_key` を持つのはそのうち 2,643件だけ、
かつ `organism_records` の distinct taxon_key（33,604）とは 818件しか重ならない。
このモジュールは両方を `taxon_id = common:taxon:gbif.<key>` という1つの識別子空間に束ねる。

## 方針（このファイルの実装）

1. **occurrence 側は taxon_key で解決する。** `organism_records` の distinct taxon_key
   （taxon_key が NULL/空でない全行）ごとに `common:taxon:gbif.<key>` を1行作る。
   代表 `scientific_name` / `rank` は、同じ taxon_key 内で最も件数の多い
   `(scientific_name, taxon_rank)` の組（最頻値）を採用する。同数の場合は
   `scientific_name` 昇順→`taxon_rank` 昇順で決定論的にタイブレークする（ビルドを
   再実行しても同じ結果になることを保証するため。件数差が出る taxon_key は
   33,604件中8件のみで、いずれも大差がつく実質的な最頻値なのでこの規則で十分）。
   `taxon_rank` は原本で大文字/小文字が混在する（'SPECIES'/'species' 等）ため
   小文字に統一するが、値の意味は変えない。

2. **`taxa` のうち `gbif_taxon_key` を持ち、かつ `gbif_match_type='EXACT'`
   （種階級での一致）の行だけを、新しい行を作らず対応する `common:taxon:gbif.<key>`
   に寄せる。** `HIGHERRANK`/`FUZZY`（合わせて300件。`gbif_taxon_key` はあるが
   種以下まで一致していない）は方針3の unresolved 側に回す（レビュー指摘・
   ADR-0019決定4）。

   **なぜ EXACT 限定に直したか（当初は HIGHERRANK/FUZZY も寄せていた）**:
   同じ gbif_taxon_key を複数の `taxa` 行が指すことがある（`gbif_match_type` が
   `HIGHERRANK`/`FUZZY` のとき、GBIF が種以下まで一致させられず属・科・時に
   kingdom まで遡った結果、別種の `taxa` 行が同じ広いキーに衝突する。例:
   key=1（Animalia, kingdom）に CR/EN の昆虫を含む10件の無関係な `taxa` 行が
   載る）。この300件のうち258件がレッドリストカテゴリを持ち、うち202件は
   そのキーが `organism_records` に出現しないため、寄せた場合レジストリ行の
   `scientific_name`/`rank` が「その taxon_key で GBIF が実際に一致させた階級
   （属・科…）」ではなく「たまたま `taxon_id` 昇順で先頭だった `taxa` 行の
   種名」になり、**ID の実体（属・科）と名前（種）が矛盾する**
   （例: `common:taxon:gbif.3123761` は GBIF では属 *Nabalus* だが、寄せると
   `scientific_name='Nabalus tanakae …', rank='genus'` のような矛盾した行に
   なっていた）。ADR-0019決定4「`gbif_match_type` が弱いものは捨てずに
   `status='unresolved'` で保持する」に反するため、EXACT 限定に直した。

   **`vernacular_name_ja` をこの行に持たせてよいのは、EXACT 行同士で
   和名が完全に一致するときだけ。** 和名が食い違う場合は和名を持たせない。
   理由: `domain.ts` の `NAME_JA` コメントが警告する「学名の広い一致に和名を
   機械結合すると別種・別個体群の和名が付く」事故（Plecoglossus altivelis に
   リュウキュウアユ）と、原理的に同じ危険が `taxa`→GBIF 側でも起きるため
   （実測で確認済み: 同じキーに複数の EXACT 行が載るのは8グループで、
   これらは学名の表記ゆれ（著者引用の有無）による同一種の重複であり
   和名も完全に一致していた）。
   `scientific_name`/`rank` の代表選びは、EXACT 限定にした後は同じキーを指す
   EXACT 行全体の中で `taxon_id`（taxa の主キー文字列）昇順の先頭を採用する
   （決定論的タイブレーク）。
   `rank` は `taxa` 自身の列には無いため、既存の
   `data/processed/taxon_crosswalk.csv`（c24_taxon_crosswalk.py の成果。
   gbif_taxon_key を持つ taxa 全2,643件がここに taxon_id で引ける）の
   `rank` 列を使う。

3. **`gbif_match_type='EXACT'` でない `taxa` 行は捨てず
   `common:taxon:ryuiki-taxa.<taxa.taxon_id>` で `status='unresolved'` として登録する。**
   内訳は次の2種類（合計 6,242件。方針2の見直しで従来の5,942件から300件増えた）:
   - `gbif_taxon_key` を持たない行（5,942件）。`taxa.taxon_id` は学名の正規化文字列
     （`c25_taxa_table.py` 参照。和名のみの行は `wamei:<和名>`）であり、整数の
     主キーではない。PHASE_A.md は「5,908件（`gbif_match_type` が NULL）」と
     書いているが、実測では `gbif_taxon_key` が空/NULL の行は 5,942件ある。
     差の34件は `gbif_match_type='NONE'`（GBIF に照会はしたが一致しなかった）の
     行で、これも「GBIF に無い」という点で NULL 行と同じく解決していないので、
     5,942件を母数として扱う（5,908 は「照会すらできていない」件数、34 は
     その内数の「照会したが不一致」件数）。
   - `gbif_taxon_key` を持つが `gbif_match_type` が `HIGHERRANK`/`FUZZY`
     （合わせて300件。方針2参照）。GBIF に照会でき、広い階級までは一致したが、
     「その GBIF taxon_key が指す概念そのもの」ではないため、対応する
     `gbif.<key>` 行には寄せず、`taxa` 行1件ごとに個別の unresolved 行として残す
     （同じキーに複数の `taxa` 行が衝突していても、unresolved 側では
     `taxa.taxon_id` ごとに別々の ID になるので、別種の和名・レッドリストカテゴリが
     混ざることはない）。

   いずれの場合も `vernacular_name_ja` は `taxa` 自身の列をそのまま転記する
   （`taxa` 行そのものが持つ属性であり、学名を介した別行への機械結合ではないため、
   方針2の制限は掛からない）。

4. **和名は `registry/taxon/vernacular_ja.csv`（`domain.ts` の `NAME_JA` 54件を
   1件も増減せずに複製したもの）だけを、機械結合ではない人間確認済みの和名として
   GBIF 由来の行に上書きする。** 突き合わせは学名の完全一致ではなく、
   `web/scripts/build-biota.mjs` の `BINOM`（学名の先頭2語）と同じ規則で行う。
   `organism_records.scientific_name` は著者引用・亜種小名を含むため
   （例: "Corvus corone Linnaeus, 1758" / "Corvus corone orientalis"）、
   54件のうち52件は完全一致する taxon_key が存在しない。実測では54件すべてで
   先頭2語が一致する taxon_key が複数存在し（同一種の表記ゆれ・亜種違いで
   GBIF キーが分かれているだけで、別種が混ざる例は無いことを確認済み）、
   その中で**件数最多の taxon_key**（`organism_records` での出現件数。同数なら
   taxon_key 昇順）を採用先とする。これは新しい名寄せルールを作っているのではなく、
   `NAME_JA` の54件はもともと「代表種1件に対する人間確認済みの和名」であり、
   その代表種を`organism_records`内で最も使われている表記に対応付けているだけ。
   `taxa` 由来の和名を学名で結合する操作は一切していない
   （54件は `taxa` を経由せず `organism_records` 側に直接載る。既存の `taxa` 由来
   和名と重なる7件は実測すべて内容が一致していたため上書きしても値は変わらない）。

5. `taxon_key` を持たない `organism_records` 853行は `taxon_id` 解決の対象外
   （どの taxon 行にも現れない）。853行は全件 `scientific_name` が空文字で
   （`inaturalist_kanagawa` 561件・`gbif_kanagawa_occurrences` 292件）、
   照合材料そのものが無いため次段階で埋めようがないことをここに記録しておく。

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

from registry import common

CROSSWALK_CSV = common.ROOT / "data" / "processed" / "taxon_crosswalk.csv"
VERNACULAR_CSV = common.ROOT / "registry" / "taxon" / "vernacular_ja.csv"


def _binom(name: str | None) -> str | None:
    """学名の先頭2語（属+種）。web/scripts/build-biota.mjs の BINOM と同じ規則。"""
    if not name:
        return None
    toks = name.split(" ")
    if len(toks) < 2:
        return name
    return f"{toks[0]} {toks[1]}"


def _load_occurrence_representatives(ryuiki: sqlite3.Connection) -> dict[str, dict]:
    """distinct taxon_key ごとの代表 (scientific_name, rank) と全体件数。

    最頻値（同数は scientific_name → taxon_rank の昇順でタイブレーク）。
    SQL 側で集約するので Python 側で 823,692 行をループしない。
    """
    sql = """
        WITH counted AS (
            SELECT taxon_key, scientific_name, taxon_rank, COUNT(*) AS n
            FROM organism_records
            WHERE taxon_key IS NOT NULL AND taxon_key <> ''
            GROUP BY taxon_key, scientific_name, taxon_rank
        ),
        totals AS (
            SELECT taxon_key, SUM(n) AS total_n FROM counted GROUP BY taxon_key
        ),
        ranked AS (
            SELECT taxon_key, scientific_name, taxon_rank, n,
                   ROW_NUMBER() OVER (
                       PARTITION BY taxon_key
                       ORDER BY n DESC, scientific_name ASC, taxon_rank ASC
                   ) AS rn
            FROM counted
        )
        SELECT r.taxon_key AS taxon_key, r.scientific_name AS scientific_name,
               r.taxon_rank AS rank_raw, t.total_n AS total_n
        FROM ranked r JOIN totals t ON t.taxon_key = r.taxon_key
        WHERE r.rn = 1
    """
    out = {}
    for row in ryuiki.execute(sql):
        out[row["taxon_key"]] = {
            "scientific_name": row["scientific_name"],
            "rank_raw": row["rank_raw"],
            "total_n": row["total_n"],
        }
    return out


def _load_taxa(ryuiki: sqlite3.Connection) -> list[sqlite3.Row]:
    return ryuiki.execute(
        "SELECT taxon_id, scientific_name, vernacular_name_ja, gbif_taxon_key, "
        "gbif_match_type FROM taxa"
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
    「EXACT で寄せられる taxa 行が無い」とみなす。
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
            }
        )
    return groups


def _pick_taxa_representative(rows: list[dict], crosswalk_rank: dict[str, str]):
    """EXACT の taxa 行の集まり（`_group_taxa_by_gbif_key` の出力）から、
    代表 (scientific_name, rank) と、和名が食い違っていない場合だけの
    vernacular_name_ja を選ぶ（モジュール docstring 方針2）。
    全行が EXACT である前提だが、タイブレークは `taxon_id` 昇順の先頭。
    """
    rep = min(rows, key=lambda r: r["taxon_id"])
    rank_raw = crosswalk_rank.get(rep["taxon_id"])

    vernaculars = {r["vernacular_name_ja"] for r in rows if r["vernacular_name_ja"]}
    vernacular = next(iter(vernaculars)) if len(vernaculars) == 1 else None
    return rep["scientific_name"], rank_raw, vernacular


def _load_vernacular_overrides() -> list[dict]:
    if not VERNACULAR_CSV.exists():
        raise FileNotFoundError(
            f"人手確認済み和名 CSV が無い: {VERNACULAR_CSV}\n"
            "domain.ts の NAME_JA 54件をそのまま複製したもの。新規に増減しない。"
        )
    with open(VERNACULAR_CSV, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション。
    src: {'ryuiki': ..., 'cells': ..., 'derived': ...} の読み取り専用コネクション。
    戻り値: {'taxon': 挿入した行数}。診断情報は print で出す（r01 の合計行数計算を
    汚さないため、返り値には含めない）。
    """
    ryuiki = src["ryuiki"]

    occ = _load_occurrence_representatives(ryuiki)
    taxa_rows = _load_taxa(ryuiki)
    crosswalk_rank = _load_crosswalk_rank()
    taxa_by_key = _group_taxa_by_gbif_key(taxa_rows)

    # --- 診断: organism_records の taxon_key 解決率 -------------------------------
    total_org = ryuiki.execute("SELECT COUNT(*) FROM organism_records").fetchone()[0]
    unresolved_org = ryuiki.execute(
        "SELECT COUNT(*) FROM organism_records WHERE taxon_key IS NULL OR taxon_key=''"
    ).fetchone()[0]
    resolved_org = total_org - unresolved_org
    unresolved_by_source = dict(
        ryuiki.execute(
            "SELECT source_id, COUNT(*) FROM organism_records "
            "WHERE taxon_key IS NULL OR taxon_key='' GROUP BY source_id"
        ).fetchall()
    )
    print(
        f"  [taxon] organism_records {total_org:,}行 -> taxon_key解決 {resolved_org:,}行 "
        f"({resolved_org / total_org * 100:.2f}%)。未解決 {unresolved_org:,}行 "
        f"内訳: {unresolved_by_source}"
    )
    print(f"  [taxon] distinct taxon_key = {len(occ):,}")

    # --- 行の組み立て --------------------------------------------------------------
    rows_by_id: dict[str, list] = {}

    all_keys = sorted(set(occ.keys()) | set(taxa_by_key.keys()))
    n_from_occurrence_only = 0
    n_from_both = 0
    n_from_taxa_only = 0
    for key in all_keys:
        taxon_id = common.taxon_id_gbif(key)
        taxa_group = taxa_by_key.get(key)

        if key in occ:
            scientific_name = occ[key]["scientific_name"]
            rank_raw = occ[key]["rank_raw"]
            if taxa_group is not None:
                n_from_both += 1
            else:
                n_from_occurrence_only += 1
        else:
            scientific_name, rank_raw, _ = _pick_taxa_representative(taxa_group, crosswalk_rank)
            n_from_taxa_only += 1

        vernacular = None
        if taxa_group is not None:
            _, _, vernacular = _pick_taxa_representative(taxa_group, crosswalk_rank)

        rank = rank_raw.lower() if rank_raw else None
        rows_by_id[taxon_id] = [
            taxon_id, scientific_name, rank, key, vernacular, "accepted", None
        ]

    print(
        f"  [taxon] gbif行 = {len(rows_by_id):,} "
        f"(occurrence のみ {n_from_occurrence_only:,} / occurrence+taxa {n_from_both:,} / "
        f"taxa のみ {n_from_taxa_only:,})"
    )

    # --- taxa の gbif_match_type != 'EXACT' な行（unresolved） ---------------------
    # 内訳: gbif_taxon_key を持たない（NONE/NULL）5,942件 + 持つが弱い一致
    # （HIGHERRANK/FUZZY）300件（モジュール docstring 方針3。レビュー指摘で
    # 従来の「キー無しだけ unresolved」から広げた）。
    n_unresolved = 0
    n_unresolved_weak_match = 0
    seen_unresolved: dict = {}
    for row in taxa_rows:
        has_key = bool((row["gbif_taxon_key"] or "").strip())
        if has_key and row["gbif_match_type"] == "EXACT":
            continue  # 方針2で対応する gbif.<key> 行に寄せ済み
        taxon_id = common.taxon_id_unresolved(row["taxon_id"], seen=seen_unresolved)
        if taxon_id in rows_by_id:
            raise ValueError(
                f"taxon_id 衝突: unresolved 側で組み立てた {taxon_id!r} が"
                "既存の行（gbif 側 or 別の taxa 行）と衝突した"
            )
        rows_by_id[taxon_id] = [
            taxon_id, row["scientific_name"], None, None,
            row["vernacular_name_ja"], "unresolved", None,
        ]
        n_unresolved += 1
        if has_key:
            n_unresolved_weak_match += 1
    print(
        f"  [taxon] taxa 由来 unresolved = {n_unresolved:,} / taxa総数 {len(taxa_rows):,}"
        f"（うち gbif_taxon_key はあるが gbif_match_type が EXACT でない弱い一致: "
        f"{n_unresolved_weak_match:,}）"
    )

    # --- NAME_JA（人手確認済み54件）を binom で上書き -------------------------------
    overrides = _load_vernacular_overrides()
    total_by_key = {k: v["total_n"] for k, v in occ.items()}
    binom_index: dict[str, list[str]] = {}
    for key, info in occ.items():
        b = _binom(info["scientific_name"])
        if b:
            binom_index.setdefault(b, []).append(key)

    n_applied = 0
    for ov in overrides:
        name = ov["scientific_name"]
        candidates = binom_index.get(name, [])
        if not candidates:
            print(f"  [taxon][WARN] NAME_JA '{name}' に一致する taxon_key が無い（未適用）")
            continue
        winner = max(candidates, key=lambda k: (total_by_key[k], k))
        taxon_id = common.taxon_id_gbif(winner)
        rows_by_id[taxon_id][4] = ov["vernacular_name_ja"]
        n_applied += 1
    print(f"  [taxon] NAME_JA 適用 = {n_applied:,} / {len(overrides):,}")

    n_vernacular = sum(1 for r in rows_by_id.values() if r[4])
    print(f"  [taxon] 和名が付いた行 = {n_vernacular:,}")

    n = common.insert_many(
        conn,
        "taxon",
        ["taxon_id", "scientific_name", "rank", "gbif_taxon_key",
         "vernacular_name_ja", "status", "accepted_taxon_id"],
        rows_by_id.values(),
    )
    return {"taxon": n}
