"""taxon_assessment を作る（ADR-0019 の最小形。P-2、2026-09-23）。

v1 は「あるリストがある分類群に付けた評価」を2つの別々の派生表として持っている:
`redlist_map`（44行、`raw -> label/code/rank` の手書き辞書。web/scripts/build-biota.mjs
262-289行）と `redlist_change`（2,884行、`ryuiki.redlist_assessments` を
`redlist_map` で正規化しただけの版間比較。同291-314行）、そして `ias_species`
（173行、`ryuiki.taxa.ias_category` を二名法で `org_norm` に結合したもの。
同234-257行）。このモジュールは後者2つ（redlist_change の元データ・ias_species の
元データ）を、同じ構造（`taxon_assessment` = list_id × taxon の評価）に統合する。
`redlist_map`（コードリストそのもの）は `registry/taxon/redlist_category.yaml` +
`redlist_category_alias.csv` に分けた（`registry/variable.yaml`/`variable_alias.csv`
と同じ「正準＋出典表記」の二層。`scripts/registry/build_unit_variable.py` 参照）。

## 入力

- `ryuiki.redlist_assessments`（2,884行）: 神奈川県レッドリスト2020（植物編）/
  レッドデータブック2022（植物編）/ レッドリスト2026（昆虫類・クモ類）の3版。
  list_id は `assessment_id` の接頭辞（`_` 区切りの先頭語。例:
  `rl2020_00001` -> `rl2020`）をそのまま使う——新しい主キーを発行し直すと
  redlist_assessments 側と縁が切れるため。`registry/taxon/assessment_list.yaml`
  にこの3件の list_id/list_name/list_year を宣言し、実データと一致することを
  ビルド時に検証する（新しい版が増えたときに黙って気づかないことを防ぐ）。
- `data/processed/moe_ias_list.csv`（429行、環境省 生態系被害防止外来種リスト）:
  **`ryuiki.taxa` ではなくこの L1 を直接読む**。`scripts/c25_taxa_table.py` が
  `taxa` 行を組み立てる際に `origin_ja`（国内由来/国外由来の区別。P-2決定3の
  除外7種の根拠）を落としているため、`taxa.ias_category` からは origin を
  復元できない。`data/processed/taxon_crosswalk.csv` を build_taxon.py が
  直読みしているのと同じ扱い（指紋にも同様に足す。`scripts/registry/common.py`
  の `MOE_IAS_LIST_CSV_RELPATH`）。list_id は固定で `moe_ias_2015`。
  assessment_id は CSV の行順から `moe_ias_2015_00001`... を機械的に発行する
  （moe_ias_list.csv 自身に安定した主キー列が無いため。CSV は
  `scripts/c21_moe_ias_list.py` が決定論的な順序〔原本 xls の行順〕で書き出す
  ので、再生成しても同じ行には同じ assessment_id が振られる）。

## カテゴリーの正規化

`category_raw`（今回の区分）・`prev_category_raw`（前回の区分。その版の文書
自身が書いている値で、版どうしを JOIN して導いたものではない——ADR-0019 決定5
への例外。理由は `docs/adr/0019-taxon-registry.md` の追記参照）は
`registry/taxon/redlist_category_alias.csv` で `category_code`/
`prev_category_code` に正規化する。**正規化（改行・半角/全角空白の除去）は
alias を引くキーにだけ使い、`*_raw` 列は原表記を無加工で残す**
（実測: 正規化で変わる行は今回側0・前回側8。`docs/plans/PHASE_B_TAXON_ASSESSMENT.md`
参照）。`'―'`（前回に247件）は v1 では「redlist_map に無い raw -> LEFT JOIN で
一致なし -> prev_rank IS NULL -> 前回記載なし」に落ちる。ここでは
`redlist_category_alias.csv` に `'―' -> not_listed` を明示的に宣言し、
黙って未知の値として落とさない（`registry/taxon/redlist_category.yaml` の
`not_listed`（rank=null）を参照）。v1 互換の射影（`scripts/b12_project_taxon_v1.py`）
は `not_listed` を出力直前に NULL へ戻す——**v1 が実際に一致なしだった事実は、
projection 側の「v1 互換に戻す」変換として残す**（このモジュール〔registry〕の
責務は「'―' を黙って落とさない」ところまで、b12 の責務は「v1 のバイト列を
再現する」ところ）。`national_category_raw` は v1（redlist_change の SELECT）も
一切正規化・コード化していないため、ここでも無加工のまま carry する
（`（ハマカキラン：\n絶滅危惧Ⅱ類）` のような自由記述も混ざるため、これを
コード化しようとすること自体が誤り）。`moe_ias_2015` のカテゴリー
（`category_ja`）は `redlist_category` とは別体系（侵入予防外来種 等）なので
コード化しない（`category_code=NULL`。`registry/taxon/assessment_list.yaml`
の `moe_ias_2015.codelist: null`、P-2決定3）。

## taxon_id 解決

学名の完全一致（`taxon.scientific_name`、複数 taxon が同じ学名を持つ場合は
曖昧なので解決しない） → 二名法一致（`taxon.canonical_binomial`、同様に複数
候補があれば解決しない）の順。解決できない行は `taxon_id=NULL` のまま
（Phase B の再現には不要な診断用の列——v1（`redlist_change`/`ias_species`）は
名前を文字列で運ぶので、`taxon_id` を一切参照しない。`scripts/b12_project_taxon_v1.py`/
`ias_species` 射影〔scripts/b08_project_occurrence_v1.py〕もこの列を使わない）。

## 除外7種（P-2 オーナー決定A）

`registry/taxon/assessment_scope_exclusions.yaml` に宣言した7種は、**このモジュール
（taxon_assessment の構築）では一切除外しない**——`taxon_assessment` は
moe_ias_list.csv の429行をそのまま持つ「正の記録」であり、v1 の静的な除外は
`ias_species`（v1 互換の集計射影）だけの都合（「宣言済み差分 > データを曲げる」
——除外という判断そのものをデータから消さず、射影側で理由つきに適用する）。
`load_assessment_scope_exclusions()` はこのファイルの構造検証（reasons が既知の
コードリスト・実測件数〔domestic_origin 6件・subspecies_binomial_contraction 2件・
distinct 7種〕と一致すること）を行う——ここで検証しておけば
`scripts/b08_project_occurrence_v1.py` の `_build_ias_species()` は import して
そのまま使ってよい（同じ検証を2箇所に書かない。`b08` が `b07` の `GRAIN_VALUES`
を import するのと同じ形の再利用）。
"""
import csv
import sqlite3

import yaml

from registry import common

REDLIST_CATEGORY_YAML = common.ROOT / "registry" / "taxon" / "redlist_category.yaml"
REDLIST_CATEGORY_ALIAS_CSV = common.ROOT / "registry" / "taxon" / "redlist_category_alias.csv"
ASSESSMENT_LIST_YAML = common.ROOT / "registry" / "taxon" / "assessment_list.yaml"
ASSESSMENT_SCOPE_EXCLUSIONS_YAML = common.ROOT / "registry" / "taxon" / "assessment_scope_exclusions.yaml"
MOE_IAS_LIST_CSV = common.ROOT / common.MOE_IAS_LIST_CSV_RELPATH

TAXON_ASSESSMENT_COLUMNS = [
    "assessment_id", "list_id", "list_year", "taxon_id",
    "scientific_name_raw", "vernacular_name_ja_raw",
    "taxon_group_ja", "taxon_subgroup_ja", "family_ja",
    "category_raw", "category_code",
    "prev_category_raw", "prev_category_code",
    "national_category_raw", "origin", "source_id",
]

_KNOWN_LIST_KINDS = frozenset({"red_list", "invasive"})
_REDLIST_LIST_IDS = ("rl2020", "rdb2022p", "rl2026")
_IAS_LIST_ID = "moe_ias_2015"

_KNOWN_EXCLUSION_REASONS = frozenset({"domestic_origin", "subspecies_binomial_contraction"})
# 実測件数（docs/plans/PHASE_B_TAXON_ASSESSMENT.md 参照）。将来この宣言ファイルの
# 中身を編集した人が、既知の7種以外を意図せず増減させていないかを機械で確認する。
_EXPECTED_EXCLUSION_TOTAL = 7
_EXPECTED_EXCLUSION_REASON_COUNTS = {"domestic_origin": 6, "subspecies_binomial_contraction": 2}


# ---------------------------------------------------------------------------
# 語彙の読み込み・構造検証
# ---------------------------------------------------------------------------

def _assert_unique(keys: list, label: str) -> None:
    dupes = sorted({k for k in keys if keys.count(k) > 1})
    assert not dupes, f"{label} が重複している: {dupes}"


def load_redlist_category_codes() -> set[str]:
    with REDLIST_CATEGORY_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["categories"]
    _assert_unique([e["code"] for e in entries], f"{REDLIST_CATEGORY_YAML} の code")
    return {e["code"] for e in entries}


def load_redlist_category_alias() -> dict[str, str]:
    with REDLIST_CATEGORY_ALIAS_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    _assert_unique([r["raw"] for r in rows], f"{REDLIST_CATEGORY_ALIAS_CSV} の raw")
    codes = load_redlist_category_codes()
    unknown = sorted({r["code"] for r in rows} - codes)
    assert not unknown, (
        f"{REDLIST_CATEGORY_ALIAS_CSV} の code に {REDLIST_CATEGORY_YAML} に無い値がある: {unknown}"
    )
    return {r["raw"]: r["code"] for r in rows}


def load_assessment_lists() -> dict[str, dict]:
    with ASSESSMENT_LIST_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["lists"]
    _assert_unique([e["list_id"] for e in entries], f"{ASSESSMENT_LIST_YAML} の list_id")
    for e in entries:
        assert e["kind"] in _KNOWN_LIST_KINDS, (
            f"{ASSESSMENT_LIST_YAML}: 未知の kind={e['kind']!r} list_id={e['list_id']!r}"
            f"（コードリスト: {sorted(_KNOWN_LIST_KINDS)}）"
        )
    return {e["list_id"]: e for e in entries}


def load_assessment_scope_exclusions(path=ASSESSMENT_SCOPE_EXCLUSIONS_YAML) -> list[dict]:
    """P-2 オーナー決定A（v1 の `ias_species` が静的にハードコードしていた7種の
    除外を宣言化したもの）。構造（reasons が既知のコードリストの部分集合）と
    実測件数（domestic_origin 6件・subspecies_binomial_contraction 2件・
    distinct 7種）の両方を検証する。`scripts/b08_project_occurrence_v1.py` の
    `_build_ias_species()` がこの関数をそのまま import して使う（モジュール
    docstring「除外7種」参照。検証を2箇所に複製しない）。
    """
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["exclusions"]
    _assert_unique(
        [(e["list_id"], e["scientific_name"]) for e in entries],
        f"{path} の (list_id, scientific_name)",
    )
    reason_counts = {k: 0 for k in _KNOWN_EXCLUSION_REASONS}
    for e in entries:
        reasons = e.get("reasons") or []
        assert reasons, f"{path}: {e['scientific_name']!r} の reasons が空"
        unknown = sorted(set(reasons) - _KNOWN_EXCLUSION_REASONS)
        assert not unknown, (
            f"{path}: {e['scientific_name']!r} の reasons に未知の値 {unknown} "
            f"（コードリスト: {sorted(_KNOWN_EXCLUSION_REASONS)}）"
        )
        for r in reasons:
            reason_counts[r] += 1
    assert len(entries) == _EXPECTED_EXCLUSION_TOTAL, (
        f"{path}: 除外種の総数が実測({_EXPECTED_EXCLUSION_TOTAL}件)と違う: {len(entries)}件"
        "（P-2 決定Aの前提が変わった。docs/plans/PHASE_B_TAXON_ASSESSMENT.md を確認・更新すること）"
    )
    for reason, expected in _EXPECTED_EXCLUSION_REASON_COUNTS.items():
        actual = reason_counts[reason]
        assert actual == expected, (
            f"{path}: reasons={reason!r} の件数が実測({expected}件)と違う: {actual}件"
        )
    return entries


# ---------------------------------------------------------------------------
# カテゴリーの正規化（alias を引くキーだけに使う。*_raw は無加工のまま）
# ---------------------------------------------------------------------------

def _normalize_category(raw: str | None) -> str | None:
    """v1（web/scripts/build-biota.mjs の redlist_change、300行付近）と同じ
    正規化規則: 改行(LF/CR)・半角空白・全角空白の除去。
    """
    if raw is None:
        return None
    return raw.replace("\n", "").replace("\r", "").replace(" ", "").replace("　", "")


def _category_code_for(raw: str | None, alias: dict[str, str], *, context: str) -> str | None:
    norm = _normalize_category(raw)
    if not norm:
        return None
    code = alias.get(norm)
    if code is None:
        raise ValueError(
            f"未知の{context}の原表記: {raw!r}（正規化後 {norm!r}）。"
            f"{REDLIST_CATEGORY_ALIAS_CSV} に追加すること（黙って落とさない）。"
        )
    return code


# ---------------------------------------------------------------------------
# taxon_id 解決（学名完全一致 -> 二名法一致。曖昧なら解決しない）
# ---------------------------------------------------------------------------

def _binom(name: str | None) -> str | None:
    """学名の先頭2語（属+種）。scripts/registry/build_taxon.py._binom() /
    web/scripts/build-biota.mjs の BINOM と同じ規則（意図的な重複。モジュール
    docstring 参照）。
    """
    if not name:
        return None
    toks = name.split(" ")
    if len(toks) < 2:
        return name
    return f"{toks[0]} {toks[1]}"


def _load_taxon_lookup(conn: sqlite3.Connection) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """`conn`（ビルド中の registry.sqlite。taxon は build_taxon.py が既に
    書き込み・commit 済み——r01 の実行順で taxon (A-4) の後に置く）から、
    学名完全一致辞書・二名法一致辞書を作る。
    """
    by_name: dict[str, list[str]] = {}
    by_binom: dict[str, list[str]] = {}
    for taxon_id, sci, binom in conn.execute(
        "SELECT taxon_id, scientific_name, canonical_binomial FROM taxon"
    ):
        if sci:
            by_name.setdefault(sci.strip(), []).append(taxon_id)
        if binom:
            by_binom.setdefault(binom, []).append(taxon_id)
    return by_name, by_binom


def _resolve_taxon_id(
    scientific_name: str | None, by_name: dict[str, list[str]], by_binom: dict[str, list[str]]
) -> str | None:
    if not scientific_name:
        return None
    sci = scientific_name.strip()
    candidates = by_name.get(sci)
    if candidates and len(candidates) == 1:
        return candidates[0]
    b = _binom(sci)
    if b:
        candidates = by_binom.get(b)
        if candidates and len(candidates) == 1:
            return candidates[0]
    return None


# ---------------------------------------------------------------------------
# 行の組み立て
# ---------------------------------------------------------------------------

def _load_redlist_assessment_rows(ryuiki: sqlite3.Connection) -> list[sqlite3.Row]:
    return ryuiki.execute(
        "SELECT assessment_id, list_name, list_year, taxon_group_ja, taxon_subgroup_ja, "
        "family_ja, vernacular_name_ja, scientific_name, category_ja, category_prev_ja, "
        "national_category_ja, source_id FROM redlist_assessments"
    ).fetchall()


def _list_id_for_redlist_row(row: sqlite3.Row, assessment_lists: dict[str, dict]) -> str:
    prefix = row["assessment_id"].split("_", 1)[0]
    entry = assessment_lists.get(prefix)
    if entry is None:
        raise ValueError(
            f"redlist_assessments.assessment_id={row['assessment_id']!r} の接頭辞 {prefix!r} が "
            f"{ASSESSMENT_LIST_YAML} に無い（新しい版が増えた可能性。list_id を追加すること）"
        )
    if entry["name"] != row["list_name"] or entry["year"] != row["list_year"]:
        raise ValueError(
            f"{ASSESSMENT_LIST_YAML} の list_id={prefix!r} と redlist_assessments の実データが"
            f"食い違う: yaml=(name={entry['name']!r}, year={entry['year']!r}) "
            f"実データ=(name={row['list_name']!r}, year={row['list_year']!r})"
        )
    return prefix


def _build_redlist_rows(
    ryuiki: sqlite3.Connection,
    assessment_lists: dict[str, dict],
    alias: dict[str, str],
    by_name: dict[str, list[str]],
    by_binom: dict[str, list[str]],
) -> list[dict]:
    rows = []
    for r in _load_redlist_assessment_rows(ryuiki):
        list_id = _list_id_for_redlist_row(r, assessment_lists)
        cur_code = _category_code_for(r["category_ja"], alias, context="category_ja")
        prev_code = _category_code_for(r["category_prev_ja"], alias, context="category_prev_ja")
        rows.append({
            "assessment_id": r["assessment_id"],
            "list_id": list_id,
            "list_year": r["list_year"],
            "taxon_id": _resolve_taxon_id(r["scientific_name"], by_name, by_binom),
            "scientific_name_raw": r["scientific_name"],
            "vernacular_name_ja_raw": r["vernacular_name_ja"],
            "taxon_group_ja": r["taxon_group_ja"],
            "taxon_subgroup_ja": r["taxon_subgroup_ja"],
            "family_ja": r["family_ja"],
            "category_raw": r["category_ja"],
            "category_code": cur_code,
            "prev_category_raw": r["category_prev_ja"],
            "prev_category_code": prev_code,
            "national_category_raw": r["national_category_ja"],
            "origin": None,
            "source_id": r["source_id"],
        })
    return rows


def _load_moe_ias_rows() -> list[dict]:
    if not MOE_IAS_LIST_CSV.exists():
        raise FileNotFoundError(
            f"moe_ias_list.csv が無い: {MOE_IAS_LIST_CSV}\n"
            "scripts/c21_moe_ias_list.py の成果物。再生成するにはそのスクリプトを実行する"
            "（環境省サイトへのダウンロードを伴うため、通常はリポジトリの成果物をそのまま使う）。"
        )
    with MOE_IAS_LIST_CSV.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _build_ias_rows(
    assessment_lists: dict[str, dict],
    by_name: dict[str, list[str]],
    by_binom: dict[str, list[str]],
) -> list[dict]:
    entry = assessment_lists[_IAS_LIST_ID]
    rows = []
    for i, r in enumerate(_load_moe_ias_rows(), start=1):
        sci = (r.get("scientific_name") or "").strip() or None
        rows.append({
            "assessment_id": f"{_IAS_LIST_ID}_{i:05d}",
            "list_id": _IAS_LIST_ID,
            "list_year": entry["year"],
            "taxon_id": _resolve_taxon_id(sci, by_name, by_binom),
            "scientific_name_raw": sci,
            "vernacular_name_ja_raw": (r.get("vernacular_name_ja") or None),
            "taxon_group_ja": (r.get("taxon_group_ja") or None),
            "taxon_subgroup_ja": None,
            "family_ja": (r.get("family_ja") or None),
            "category_raw": (r.get("category_ja") or None),
            "category_code": None,
            "prev_category_raw": None,
            "prev_category_code": None,
            "national_category_raw": None,
            "origin": (r.get("origin_ja") or None),
            "source_id": (r.get("source_id") or None),
        })
    return rows


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション（taxon (A-4) が既に
    commit 済みであること——r01 の STEPS 順で taxon の後に置く）。
    src: {'ryuiki': ..., 'cells': ...} の読み取り専用コネクション。
    戻り値: {'taxon_assessment': 挿入した行数}。
    """
    ryuiki = src["ryuiki"]

    assessment_lists = load_assessment_lists()
    for list_id in (*_REDLIST_LIST_IDS, _IAS_LIST_ID):
        assert list_id in assessment_lists, (
            f"{ASSESSMENT_LIST_YAML} に list_id={list_id!r} が無い（P-2の前提）"
        )
    alias = load_redlist_category_alias()
    load_assessment_scope_exclusions()  # 構造検証だけ（戻り値は b08 が使う）。

    by_name, by_binom = _load_taxon_lookup(conn)

    redlist_rows = _build_redlist_rows(ryuiki, assessment_lists, alias, by_name, by_binom)
    ias_rows = _build_ias_rows(assessment_lists, by_name, by_binom)
    all_rows = redlist_rows + ias_rows

    n_taxon_id = sum(1 for r in all_rows if r["taxon_id"])
    print(
        f"  [taxon_assessment] {len(all_rows):,}行"
        f"（redlist {len(redlist_rows):,} / {_IAS_LIST_ID} {len(ias_rows):,}）"
        f" taxon_id解決 {n_taxon_id:,} ({n_taxon_id / len(all_rows) * 100:.1f}%)"
    )

    n = common.insert_many(
        conn,
        "taxon_assessment",
        TAXON_ASSESSMENT_COLUMNS,
        ([r[c] for c in TAXON_ASSESSMENT_COLUMNS] for r in all_rows),
    )
    return {"taxon_assessment": n}
