"""taxon_assessment を作る（ADR-0019 の最小形。P-2、2026-09-23。
/code-review 対応、2026-09-23）。

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
  **redlist の list_id 集合は `assessment_list.yaml` の `kind='red_list'` から
  導出する**（`redlist_list_ids()`）——以前はこのモジュールと
  `scripts/b12_project_taxon_v1.py` の両方に3件を直書きしており、新しい版を
  足したとき b12 側だけ更新し忘れると `redlist_change` が静かに版1つぶん
  足りなくなる欠陥があった（/code-review 指摘8）。
- `data/processed/moe_ias_list.csv`（429行、環境省 生態系被害防止外来種リスト）:
  **`ryuiki.taxa` ではなくこの L1 を直接読む**。`scripts/c25_taxa_table.py` が
  `taxa` 行を組み立てる際に `origin_ja`（国内由来/国外由来の区別。P-2決定3の
  除外7種の根拠）を落としているため、`taxa.ias_category` からは origin を
  復元できない。`data/processed/taxon_crosswalk.csv` を build_taxon.py が
  直読みしているのと同じ扱い（指紋にも同様に足す。`scripts/registry/common.py`
  の `MOE_IAS_LIST_CSV_RELPATH`）。
  **`assessment_id` は内容から決まる**（`_ias_assessment_id()`）——以前は
  CSV の行順（`moe_ias_2015_00001`...）で機械的に発行していたが、これは
  ADR-0004 規約2「ID は不変」に反する: CSV に行の追加・削除があると既存行の
  連番がずれ、同じ ID が別の種を指すようになる（/code-review 指摘7）。学名の
  正規化＋区分＋和名（原表記）の組から作る——実測でこの3項の組は429行すべてで
  一意（唯一の重複学名 `'Bufo spp.'` は区分が同じだが和名が異なるため区別できる）。

## 和名の解決（v1 の `taxa` の畳み込みをレジストリ側で再現する）

v1 の `ias_species.name_ja`（`MAX(vernacular_name_ja) FROM r.taxa ...`）は、
`taxa` テーブルが既に済ませた**3出典（`kanagawa_redlist.csv` →
`moe_redlist.csv`〔国レッドリスト、このモジュールの対象外〕→
`moe_ias_list.csv` の順、`scripts/c25_taxa_table.py`）をまたいだ「同じ学名の
最初の非空和名が勝つ」畳み込みの結果**を読んでいる。`moe_ias_list.csv` 単体の
`vernacular_name_ja` だけでは再現できない（実測の具体例・件数は
`docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照）。

**この畳み込みの再現は、射影（`scripts/b08_project_occurrence_v1.py`）ではなく
ここ（レジストリのビルド）で行う**——射影は「`registry.sqlite` だけを読み、
原本（`ryuiki.sqlite`）には触れない」という既存の層分けを保つため（以前は
b08 が `ryuiki.sqlite` を直接 ATTACH していたが、これは射影の層に原本が入り
込む設計逸脱だった。/code-review 指摘1）。`ryuiki.taxa.vernacular_name_ja`
を学名の正規化キー（`_norm_id()` = `scripts/c25_taxa_table.py.norm_id()` と
同じ規則）で引き、`taxon_assessment.vernacular_name_ja_resolved` に持たせる
（moe_ias_2015 の行だけ。redlist 側は常に NULL——v1 の `redlist_change` は
taxa を経由しないため）。**`vernacular_name_ja_resolved` は今のところ
消費者が `ias_species`（moe_ias_2015 の行だけ）1つだけの、list 固有の狭い列
である——2つ目の消費者（例: redlist側にも和名の畳み込みが要る場面）が
出てきたら、list ごとの列を増やすのではなく `taxon_id`（または学名の
正規化キー）をキーにした汎用の和名解決テーブルに昇格させること**
（申し送り。/simplify 指摘8）。

**`taxa` に対応する行が無い場合は止める**（黙って空文字や NULL に落とさない。
/code-review 指摘4）: `scripts/c25_taxa_table.py` は moe_ias_list.csv の
全行を必ず `taxa` に取り込む設計なので、対応が無いのは taxa の再生成漏れ等の
異常であり、データが無いことを隠さず明示的に止めるのが安全側（v1 が「その行を
出さない」のは taxa 自体に行が無いときの帰結だが、原因不明のまま v1 と違う
行数になるより、はっきり気づける形にする）。`taxa.vernacular_name_ja` 自体が
NULL/空文字の場合はそのまま NULL を持たせる（`"" ` に丸めない。v1 の
`MAX(vernacular_name_ja)` も NULL のままの行がありうる。実測では429行全件で
非NULLだったため、この分岐は将来データが増えたときの防御）。

**二名法（binom）は `taxa.scientific_name`（3出典のうち最初に登録された
綴り）から作るのが v1 の規則だが、これは `moe_ias_list.csv` 自身の
`scientific_name`（`scientific_name_raw` 列）と一致することを機械検証する**
（実測: 429行すべてで一致。食い違えば止める。/code-review 指摘10）——この
検証が通っている限り、`org_norm` との結合（`scripts/b08_project_occurrence_v1.py`）
は `scientific_name_raw` から作った binom をそのまま使ってよい（`taxa` を
経由しなくても v1 と同じ結果になることが保証される）。

## カテゴリーの正規化

`category_raw`（今回の区分）・`prev_category_raw`（前回の区分。その版の文書
自身が書いている値で、版どうしを JOIN して導いたものではない——ADR-0019 決定5
への例外。理由は `docs/adr/0019-taxon-registry.md` の追記参照）は、
`assessment_list.yaml` の `codelist` 宣言に従ってコード化する
（`_category_code_for_list()`。/code-review 指摘9: 以前は「redlist系は
コード化する・moe_ias系はしない」という分岐がコードにハードコードされ、
`codelist` 宣言自体は読まれていなかった）: `codelist='redlist_category'`
の3リスト（rl2020/rdb2022p/rl2026）は `registry/taxon/redlist_category_alias.csv`
で正規化し、`codelist: null` の `moe_ias_2015` は常に `category_code=NULL`
のまま（専用のコードリストを持たない。P-2決定3）。

**正規化（改行・半角/全角空白の除去）は alias を引くキーにだけ使い、`*_raw` 列は
原表記を無加工で残す**（実測: `docs/plans/PHASE_B_TAXON_ASSESSMENT.md` 参照）。
`'―'` は v1 では「redlist_map に無い raw -> LEFT JOIN で一致なし ->
prev_rank IS NULL -> 前回記載なし」に落ちる。ここでは
`redlist_category_alias.csv` に `'―' -> not_listed` を明示的に宣言し、黙って
未知の値として落とさない（`registry/taxon/redlist_category.yaml` の
`not_listed`（rank=null）を参照）。v1 互換の射影
（`scripts/b12_project_taxon_v1.py`）は `not_listed` を出力直前に NULL へ
戻す——**v1 が実際に一致なしだった事実は、projection 側の「v1 互換に戻す」
変換として残す**（このモジュール〔registry〕の責務は「'―' を黙って落とさない」
ところまで、b12 の責務は「v1 のバイト列を再現する」ところ）。
`national_category_raw` は v1（redlist_change の SELECT）も一切正規化・
コード化していないため、ここでも無加工のまま carry する（`（ハマカキラン：
\n絶滅危惧Ⅱ類）` のような自由記述も混ざるため、これをコード化しようとすること
自体が誤り）。

**未知の原表記でビルド全体を止めるのは、ADR-0019 決定2からの意図的な逸脱
である。** 理由・経緯は `docs/adr/0019-taxon-registry.md` の2026-09-23追記に
一本化した（/code-review 指摘11）。

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
`load_assessment_scope_exclusions()` はこのファイルの構造検証を行う——ここで
検証しておけば `scripts/b08_project_occurrence_v1.py` の `_build_ias_species()`
は import してそのまま使ってよい（同じ検証を2箇所に書かない）:

- reasons が既知のコードリストの部分集合であること・実測件数（domestic_origin
  6件・subspecies_binomial_contraction 2件・distinct 7種）と一致すること。
- **`list_id` が `assessment_list.yaml` に実在すること**（/code-review 指摘6:
  以前は検査しておらず、`list_id` を打ち間違えても件数の検査は素通りしたまま
  除外が1件静かに効かなくなる欠陥があった）。
- **`scientific_name` が二名法（空白区切りで2語）であること**（/code-review
  指摘5: `WHERE o.binom NOT IN (...)` の比較先である `org_norm.binom`/
  `taxon_assessment` の binom は常に2語なので、3語（亜種名付き等）で書かれると
  binom と一致せず除外が黙って効かなくなる）。
"""
import csv
import hashlib
import re
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
    "scientific_name_raw", "vernacular_name_ja_raw", "vernacular_name_ja_resolved",
    "taxon_group_ja", "taxon_subgroup_ja", "family_ja",
    "category_raw", "category_code",
    "prev_category_raw", "prev_category_code",
    "national_category_raw", "origin", "source_id",
]

_KNOWN_LIST_KINDS = frozenset({"red_list", "invasive"})
# assessment_list.yaml/redlist_category.yaml の region/scope が取りうる値
# （ADR-0002 の地域ID + 'common'）。/code-review 指摘9: 宣言されているのに
# どこからも参照されていなかったため、ここで実際に検証する（新しい地域IDが
# 増えたらこのリストに足すこと）。
_KNOWN_REGIONS = frozenset({"common", "jp", "jp-14"})
_IAS_LIST_ID = "moe_ias_2015"

_KNOWN_EXCLUSION_REASONS = frozenset({"domestic_origin", "subspecies_binomial_contraction"})
# 実測件数（docs/plans/PHASE_B_TAXON_ASSESSMENT.md 参照）。将来この宣言ファイルの
# 中身を編集した人が、既知の7種以外を意図せず増減させていないかを機械で確認する。
_EXPECTED_EXCLUSION_TOTAL = 7
_EXPECTED_EXCLUSION_REASON_COUNTS = {"domestic_origin": 6, "subspecies_binomial_contraction": 2}


# ---------------------------------------------------------------------------
# 語彙の読み込み・構造検証
# ---------------------------------------------------------------------------
#
# 重複検査（`common.assert_unique`）は `scripts/registry/common.py` にある
# 共通実装を使う（/simplify 指摘2: `build_unit_variable.py`/`build_taxon.py`/
# `build_caveat.py` にもそれぞれ私有の同名関数があったが、このモジュールで
# 5個目の複製になった時点で共通化した。既存4箇所は本PRのスコープ外）。

def load_redlist_categories() -> dict[str, dict]:
    """`registry/taxon/redlist_category.yaml` を code をキーにした辞書で返す
    （code の重複・scope の既知性を検証済み）。`scripts/b12_project_taxon_v1.py`
    もこの関数から label_ja/rank を取る——以前はこのモジュールと b12 がこの
    YAML を別々にパースしており、2つの結果が食い違っていないかを実行時
    assert で検出する形になっていた（正が2つある状態。/simplify 指摘5）。
    """
    with REDLIST_CATEGORY_YAML.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["categories"]
    common.assert_unique([e["code"] for e in entries], f"{REDLIST_CATEGORY_YAML} の code")
    for e in entries:
        scope = e.get("scope") or "common"
        assert scope in _KNOWN_REGIONS, (
            f"{REDLIST_CATEGORY_YAML}: 未知の scope={scope!r} code={e['code']!r}"
            f"（コードリスト: {sorted(_KNOWN_REGIONS)}）"
        )
    return {e["code"]: e for e in entries}


def load_redlist_category_codes() -> set[str]:
    """`load_redlist_categories()` の code 集合だけを返す薄いラッパー
    （r01 の不変条件チェック等、code の集合だけで足りる呼び出し元向け）。"""
    return set(load_redlist_categories())


def load_redlist_category_alias() -> dict[str, str]:
    with REDLIST_CATEGORY_ALIAS_CSV.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    common.assert_unique([r["raw"] for r in rows], f"{REDLIST_CATEGORY_ALIAS_CSV} の raw")
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
    common.assert_unique([e["list_id"] for e in entries], f"{ASSESSMENT_LIST_YAML} の list_id")
    for e in entries:
        assert e["kind"] in _KNOWN_LIST_KINDS, (
            f"{ASSESSMENT_LIST_YAML}: 未知の kind={e['kind']!r} list_id={e['list_id']!r}"
            f"（コードリスト: {sorted(_KNOWN_LIST_KINDS)}）"
        )
        assert e["region"] in _KNOWN_REGIONS, (
            f"{ASSESSMENT_LIST_YAML}: 未知の region={e['region']!r} list_id={e['list_id']!r}"
            f"（コードリスト: {sorted(_KNOWN_REGIONS)}）"
        )
    return {e["list_id"]: e for e in entries}


def redlist_list_ids(assessment_lists: dict[str, dict]) -> list[str]:
    """`kind='red_list'` の list_id 一覧（`assessment_list.yaml` から導出）。
    `scripts/b12_project_taxon_v1.py` もこの関数を使う（/code-review 指摘8。
    モジュール docstring「入力」参照）。
    """
    return sorted(lid for lid, e in assessment_lists.items() if e["kind"] == "red_list")


def load_assessment_scope_exclusions(path=ASSESSMENT_SCOPE_EXCLUSIONS_YAML) -> list[dict]:
    """P-2 オーナー決定A（v1 の `ias_species` が静的にハードコードしていた7種の
    除外を宣言化したもの）。構造・実測件数（domestic_origin 6件・
    subspecies_binomial_contraction 2件・distinct 7種）・`list_id` の実在・
    `scientific_name` が二名法であることを検証する（モジュール docstring
    「除外7種」参照）。`scripts/b08_project_occurrence_v1.py` の
    `_build_ias_species()` がこの関数をそのまま import して使う。
    """
    assessment_lists = load_assessment_lists()
    with path.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    entries = doc["exclusions"]
    common.assert_unique(
        [(e["list_id"], e["scientific_name"]) for e in entries],
        f"{path} の (list_id, scientific_name)",
    )
    reason_counts = {k: 0 for k in _KNOWN_EXCLUSION_REASONS}
    for e in entries:
        assert e["list_id"] in assessment_lists, (
            f"{path}: {e['scientific_name']!r} の list_id={e['list_id']!r} が "
            f"{ASSESSMENT_LIST_YAML} に無い（打ち間違いだと除外が静かに効かなくなる。"
            "/code-review 指摘6）"
        )
        sci = e["scientific_name"]
        toks = sci.split(" ")
        assert len(toks) == 2, (
            f"{path}: scientific_name={sci!r} が二名法（空白区切りで2語）ではない"
            f"（{len(toks)}語）。org_norm.binom/taxon_assessment の binom は常に"
            "2語なので、3語目があると黙って除外が効かなくなる（/code-review 指摘5）"
        )
        reasons = e.get("reasons") or []
        assert reasons, f"{path}: {sci!r} の reasons が空"
        unknown = sorted(set(reasons) - _KNOWN_EXCLUSION_REASONS)
        assert not unknown, (
            f"{path}: {sci!r} の reasons に未知の値 {unknown} "
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
            f"{REDLIST_CATEGORY_ALIAS_CSV} に追加すること（黙って落とさない。"
            "ADR-0019 決定2からの意図的な逸脱——モジュール docstring「カテゴリーの"
            "正規化」参照）。"
        )
    return code


# 実在するコード体系は現状 'redlist_category' の1つだけ。`codelist` 宣言は
# 「この list がコード化されるかどうか」の名前の妥当性検証はするが、
# コード体系そのものを切り替える仕組みはまだ無い（`_category_code_for()` が
# `redlist_category_alias.csv`〔正準の alias〕を決め打ちで使う）。**2つ目の
# コード体系（例: 別の地域の独自リスト）が実際に増えたら、`_category_code_for_list()`
# に「codelist名 -> aliasの読み込み関数」の対応表を持たせ、alias の選び方を
# 引数化すること**（申し送り。/simplify 指摘7）。
_KNOWN_CODELISTS = frozenset({"redlist_category"})


def _category_code_for_list(
    list_id: str, raw: str | None, assessment_lists: dict[str, dict],
    alias: dict[str, str], *, context: str,
) -> str | None:
    """`assessment_lists[list_id]["codelist"]` に従って `raw` をコード化する
    （/code-review 指摘9: `codelist` 宣言を実際の分岐に使う。以前は
    「redlist系はコード化・moe_ias系はNone決め打ち」という分岐がコードに
    ハードコードされ、`codelist` 宣言自体は読まれていなかった）。`codelist`
    が null の list は常に `category_code=None`（moe_ias_2015 は専用の
    コードリストを持たない。P-2決定3）。**現状はコード体系が1つしか無いため
    `alias`〔呼び出し元が渡す `redlist_category_alias.csv`〕を素通しするだけの
    実質1択の分岐——`_KNOWN_CODELISTS` 直前のコメント参照。**
    """
    codelist = assessment_lists[list_id]["codelist"]
    if codelist is None:
        return None
    if codelist not in _KNOWN_CODELISTS:
        raise ValueError(
            f"{ASSESSMENT_LIST_YAML}: list_id={list_id!r} の codelist={codelist!r} が未知"
            f"（コードリスト: {sorted(_KNOWN_CODELISTS)}）"
        )
    return _category_code_for(raw, alias, context=context)


# ---------------------------------------------------------------------------
# taxon_id 解決（学名完全一致 -> 二名法一致。曖昧なら解決しない）
# ---------------------------------------------------------------------------

def binom_of(name: str | None) -> str | None:
    """学名の先頭2語（属+種）。web/scripts/build-biota.mjs の BINOM と同じ規則。
    `scripts/registry/build_taxon.py._binom()` とも同じ規則（意図的な重複。
    そちらはレジストリのビルド時パッケージ内で完結する）。
    `scripts/b08_project_occurrence_v1.py` はこの公開関数を import して使う
    （/code-review 指摘12: 3つ目の複製を作らない）。
    """
    if not name:
        return None
    toks = name.split(" ")
    if len(toks) < 2:
        return name
    return f"{toks[0]} {toks[1]}"


def _norm_id(name: str | None) -> str:
    """`scripts/c25_taxa_table.py.norm_id()` と同じ規則（空白列を1つに畳み、
    前後をトリムして小文字化）。`ryuiki.taxa.taxon_id` はこのキーそのもの。
    """
    return re.sub(r"\s+", " ", (name or "")).strip().lower()


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
    b = binom_of(sci)
    if b:
        candidates = by_binom.get(b)
        if candidates and len(candidates) == 1:
            return candidates[0]
    return None


# ---------------------------------------------------------------------------
# 和名の解決（v1 の taxa の畳み込みを再現する。モジュール docstring参照）
# ---------------------------------------------------------------------------

def _load_taxa_lookup(ryuiki: sqlite3.Connection) -> dict[str, tuple[str, str | None]]:
    """`ryuiki.taxa` を正規化学名（`_norm_id()`）で引く辞書:
    `{norm_id: (scientific_name, vernacular_name_ja)}`。
    """
    return {
        row[0]: (row[1], row[2])
        for row in ryuiki.execute("SELECT taxon_id, scientific_name, vernacular_name_ja FROM taxa")
    }


def _ias_assessment_id(scientific_name_raw: str, category_raw: str | None, vernacular_name_ja_raw: str | None) -> str:
    """内容から決まる安定な ID（ADR-0004 規約2: ID は不変。/code-review 指摘7）。
    学名の正規化＋区分＋和名（原表記）の組から作る——実測でこの3項の組は
    moe_ias_list.csv の429行すべてで一意（唯一の重複学名 `'Bufo spp.'` は
    区分が同じだが和名が異なるため区別できる）。学名部分は
    `common.slugify_local_key()` で読める接頭辞にし、内容ハッシュ（sha256の
    先頭12桁）を添えて衝突を機械的に防ぐ（`taxon_assessment.assessment_id` は
    PRIMARY KEY なので、万一衝突しても SQLite の INSERT が例外で止める）。
    """
    basis = f"{_norm_id(scientific_name_raw)}|{category_raw or ''}|{vernacular_name_ja_raw or ''}"
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()[:12]
    slug = common.slugify_local_key(scientific_name_raw)
    return f"{_IAS_LIST_ID}_{slug}_{digest}"


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
        cur_code = _category_code_for_list(
            list_id, r["category_ja"], assessment_lists, alias, context="category_ja",
        )
        prev_code = _category_code_for_list(
            list_id, r["category_prev_ja"], assessment_lists, alias, context="category_prev_ja",
        )
        rows.append({
            "assessment_id": r["assessment_id"],
            "list_id": list_id,
            "list_year": r["list_year"],
            "taxon_id": _resolve_taxon_id(r["scientific_name"], by_name, by_binom),
            "scientific_name_raw": r["scientific_name"],
            "vernacular_name_ja_raw": r["vernacular_name_ja"],
            "vernacular_name_ja_resolved": None,  # moe_ias_2015 の行だけが持つ
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
    alias: dict[str, str],
    by_name: dict[str, list[str]],
    by_binom: dict[str, list[str]],
    taxa_lookup: dict[str, tuple[str, str | None]],
) -> list[dict]:
    entry = assessment_lists[_IAS_LIST_ID]
    rows = []
    n_matched = 0
    for r in _load_moe_ias_rows():
        sci = (r.get("scientific_name") or "").strip() or None
        if not sci:
            raise ValueError(f"{MOE_IAS_LIST_CSV} に scientific_name の無い行がある: {r!r}")

        key = _norm_id(sci)
        taxa_entry = taxa_lookup.get(key)
        if taxa_entry is None:
            raise ValueError(
                f"{MOE_IAS_LIST_CSV} の学名 {sci!r}（正規化キー {key!r}）に対応する "
                "ryuiki.taxa 行が無い。scripts/c25_taxa_table.py はこの学名も taxa に"
                "取り込む設計なので、taxa の再生成漏れの可能性がある"
                "（/code-review 指摘4・10。黙って空文字/NULLに丸めず止める）。"
            )
        taxa_scientific_name, taxa_vernacular = taxa_entry
        if taxa_scientific_name != sci:
            raise ValueError(
                f"{MOE_IAS_LIST_CSV} の学名 {sci!r} と ryuiki.taxa.scientific_name "
                f"{taxa_scientific_name!r}（同じ正規化キー {key!r}）の綴りが食い違う。"
                "v1（taxa.scientific_name から二名法を作る）との前提が崩れている"
                "（/code-review 指摘10）。"
            )
        n_matched += 1

        category_raw = r.get("category_ja") or None
        vernacular_raw = r.get("vernacular_name_ja") or None
        rows.append({
            "assessment_id": _ias_assessment_id(sci, category_raw, vernacular_raw),
            "list_id": _IAS_LIST_ID,
            "list_year": entry["year"],
            "taxon_id": _resolve_taxon_id(sci, by_name, by_binom),
            "scientific_name_raw": sci,
            "vernacular_name_ja_raw": vernacular_raw,
            "vernacular_name_ja_resolved": taxa_vernacular,  # NULL のままもありうる
            "taxon_group_ja": (r.get("taxon_group_ja") or None),
            "taxon_subgroup_ja": None,
            "family_ja": (r.get("family_ja") or None),
            "category_raw": category_raw,
            "category_code": _category_code_for_list(
                _IAS_LIST_ID, category_raw, assessment_lists, alias, context="category_ja",
            ),
            "prev_category_raw": None,
            "prev_category_code": None,
            "national_category_raw": None,
            "origin": (r.get("origin_ja") or None),
            "source_id": (r.get("source_id") or None),
        })
    print(
        f"  [taxon_assessment] {_IAS_LIST_ID}: {n_matched:,}/{len(rows):,}行が taxa と"
        "学名一致（vernacular_name_ja_resolved を解決）"
    )
    return rows


def build(conn: sqlite3.Connection, src: dict[str, sqlite3.Connection]) -> dict[str, int]:
    """conn: registry.sqlite への書き込み用コネクション（taxon (A-4) が既に
    commit 済みであること——r01 の STEPS 順で taxon の後に置く）。
    src: {'ryuiki': ..., 'cells': ...} の読み取り専用コネクション。
    戻り値: {'taxon_assessment': 挿入した行数}。
    """
    ryuiki = src["ryuiki"]

    assessment_lists = load_assessment_lists()
    assert redlist_list_ids(assessment_lists), (
        f"{ASSESSMENT_LIST_YAML} に kind='red_list' の list が1件も無い"
    )
    assert _IAS_LIST_ID in assessment_lists, (
        f"{ASSESSMENT_LIST_YAML} に list_id={_IAS_LIST_ID!r} が無い（P-2の前提）"
    )
    alias = load_redlist_category_alias()
    load_assessment_scope_exclusions()  # 構造検証だけ（戻り値は b08 が使う）。

    by_name, by_binom = _load_taxon_lookup(conn)
    taxa_lookup = _load_taxa_lookup(ryuiki)

    redlist_rows = _build_redlist_rows(ryuiki, assessment_lists, alias, by_name, by_binom)
    ias_rows = _build_ias_rows(assessment_lists, alias, by_name, by_binom, taxa_lookup)
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
