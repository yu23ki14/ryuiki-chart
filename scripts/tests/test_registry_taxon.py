"""scripts/registry/build_taxon.py の F1（taxon_id の名前空間分割）・F2（分類補完と
taxon_group）のテスト（phase-b/occurrence-registry）。

本物の `data/db/*.sqlite`（828MB/42MB/449MB）を要さず、
scripts/tests/registry_fixtures.py の小さな自作 sqlite だけで完結する。
`registry/taxon/vernacular_ja.csv` と `registry/taxon/taxon_group.yaml` だけは実物を読む
（build_taxon.py が常にリポジトリのこのファイルを読む設計のため。どちらも手書きの正本であり
Git 管理下にあるので、`CLAUDE.md` の原本使用禁止の対象外）。`data/processed/taxon_crosswalk.csv`
は Git 管理外（.gitignore の `data/*`）なので、`build_taxon.CROSSWALK_CSV` を tmp_path の
空クロスウォークに差し替える（`monkeypatch`）。
"""
import sqlite3

import pytest

from registry import common
from registry.build_taxon import build as build_taxon
import registry.build_taxon as build_taxon_module

from .registry_fixtures import make_ryuiki_taxon_db, open_taxon_src


@pytest.fixture(autouse=True)
def _empty_crosswalk(monkeypatch, tmp_path):
    """CROSSWALK_CSV（Git管理外）を空のクロスウォークに差し替える。
    どのテストも `gbif_match_type='EXACT'` な taxa 行の `rank` は使わない
    （crosswalk_rank に無いキーは `_load_crosswalk_rank().get()` が None を返すだけで
    落ちない設計）ので、ヘッダ行だけのファイルで十分。
    """
    csv_path = tmp_path / "taxon_crosswalk.csv"
    csv_path.write_text("taxon_id,rank\n", encoding="utf-8")
    monkeypatch.setattr(build_taxon_module, "CROSSWALK_CSV", csv_path)


def _build(tmp_path, organism_records_rows=(), taxa_rows=()):
    ryuiki_path = tmp_path / "ryuiki.sqlite"
    make_ryuiki_taxon_db(ryuiki_path, organism_records_rows, taxa_rows)

    registry_conn = common.create_registry_db(tmp_path / "registry.sqlite")
    registry_conn.row_factory = sqlite3.Row
    src = open_taxon_src(ryuiki_path)
    try:
        counts = build_taxon(registry_conn, src)
    finally:
        src["ryuiki"].close()
    return registry_conn, counts


def _taxon(conn, taxon_id):
    row = conn.execute("SELECT * FROM taxon WHERE taxon_id = ?", (taxon_id,)).fetchone()
    assert row is not None, f"{taxon_id} が taxon に無い"
    return dict(row)


# ---------------------------------------------------------------------------
# F1: taxon_id の名前空間分割
# ---------------------------------------------------------------------------


def test_gbif_and_inat_with_same_numeric_key_do_not_collide(tmp_path):
    """GBIF の taxonKey と iNaturalist の taxon.id がたまたま同じ数値でも、
    別の taxon_id（別の実体）として登録される（実データの9件衝突の回帰テスト）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "8026", "Axiidae", "FAMILY",
         "Animalia", "Arthropoda", "Malacostraca", None, "Axiidae", "2020-01-01"),
        ("inaturalist_kanagawa", "8026", "Corvus macrorhynchos", "species",
         None, None, None, None, None, "2020-01-02"),
    ]
    conn, counts = _build(tmp_path, organism_records_rows=rows)

    assert counts["taxon"] == 2
    gbif_row = _taxon(conn, "common:taxon:gbif.8026")
    inat_row = _taxon(conn, "common:taxon:inat.8026")
    assert gbif_row["scientific_name"] == "Axiidae"
    assert gbif_row["gbif_taxon_key"] == "8026"
    assert inat_row["scientific_name"] == "Corvus macrorhynchos"
    # iNat 由来行の gbif_taxon_key は常に NULL（本物の GBIF taxonKey ではないため）。
    assert inat_row["gbif_taxon_key"] is None


def test_unknown_source_id_raises(tmp_path):
    """SOURCE_NAMESPACE に無い source_id は黙って混ぜず例外で止める（F1）。"""
    rows = [
        ("some_new_source", "1", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
    ]
    with pytest.raises(ValueError, match="名前空間が未定義"):
        _build(tmp_path, organism_records_rows=rows)


def test_new_namespace_without_traits_raises_immediately(tmp_path, monkeypatch):
    """TAXON_KEY_SOURCE_NAMESPACE に3つ目の名前空間を足しても、taxon_id の
    組み立て方（_NAMESPACE_TRAITS）が無ければビルド開始直後に明示的に止まる
    （黙って既存の名前空間——inat——に化けたりしない。/code-review 指摘1）。
    """
    monkeypatch.setitem(build_taxon_module.TAXON_KEY_SOURCE_NAMESPACE, "third_source", "third")
    rows = [
        ("third_source", "1", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
    ]
    with pytest.raises(ValueError, match="_NAMESPACE_TRAITS"):
        _build(tmp_path, organism_records_rows=rows)


def test_new_namespace_with_traits_gets_correct_id_and_no_collision(tmp_path, monkeypatch):
    """_NAMESPACE_TRAITS に3つ目の名前空間の組み立て方を足せば、正しい形の
    taxon_id になり、既存の gbif/inat 名前空間と衝突しない（同じ数値キー8026が
    3つの名前空間それぞれで別の taxon になる。/code-review 指摘1）。
    """
    monkeypatch.setitem(build_taxon_module.TAXON_KEY_SOURCE_NAMESPACE, "third_source", "third")
    monkeypatch.setitem(
        build_taxon_module._NAMESPACE_TRAITS,
        "third",
        {
            "id_builder": lambda key: f"common:taxon:third.{key}",
            "fill_gbif_taxon_key": False,
        },
    )
    rows = [
        ("gbif_kanagawa_occurrences", "8026", "Axiidae", "FAMILY",
         None, None, None, None, None, "2020-01-01"),
        ("inaturalist_kanagawa", "8026", "Corvus macrorhynchos", "species",
         None, None, None, None, None, "2020-01-02"),
        ("third_source", "8026", "Something thirdish", "species",
         None, None, None, None, None, "2020-01-03"),
    ]
    conn, counts = _build(tmp_path, organism_records_rows=rows)
    assert counts["taxon"] == 3
    third_row = _taxon(conn, "common:taxon:third.8026")
    assert third_row["scientific_name"] == "Something thirdish"
    assert third_row["gbif_taxon_key"] is None
    assert _taxon(conn, "common:taxon:gbif.8026")["scientific_name"] == "Axiidae"
    assert _taxon(conn, "common:taxon:inat.8026")["scientific_name"] == "Corvus macrorhynchos"


def test_taxon_key_to_binomial_must_be_a_function(tmp_path):
    """出典内で同じ taxon_key に異なる二名法キー(binom)が付くと機械検証で止まる
    （F1機械検証。同じ数値キーが実は複数の実体を指している異常を示す）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "999", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "999", "Baz qux", "species", None, None, None, None, None, "2020-01-02"),
    ]
    with pytest.raises(AssertionError, match="二名法キーが関数でない"):
        _build(tmp_path, organism_records_rows=rows)


def test_representative_selection_tie_with_only_naming_difference_does_not_stop_build(tmp_path):
    """同じ (ns, taxon_key) の中で代表候補(scientific_name違い)の件数が同数でも、
    分類（kingdom/phylum/class/order/family）が一致していれば黙って選び、
    ビルドを止めず needs_review にもしない（/code-review 指摘3。以前は
    AssertionError で必ず止めていたため、著者引用の表記ゆれ2件だけで
    ensure-registry.sh→docker compose up が起動しなくなる事故だった）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "50", "Testx aaa forma1", "species",
         "Kingdom1", "Phylum1", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "50", "Testx aaa forma2", "species",
         "Kingdom1", "Phylum1", "ClassA", None, None, "2020-01-02"),
    ]
    conn, counts = _build(tmp_path, organism_records_rows=rows)
    assert counts["taxon"] == 1
    t = _taxon(conn, "common:taxon:gbif.50")
    assert t["class"] == "ClassA"
    assert t["status"] == "accepted"


def test_representative_selection_tie_with_classification_conflict_marks_needs_review(tmp_path):
    """同じ (ns, taxon_key) の中で代表候補の件数が同数で、かつ分類が食い違う場合は
    needs_review にする（ビルドは止めない。/code-review 指摘3）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "51", "Testy aaa forma1", "species",
         "Kingdom1", "Phylum1", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "51", "Testy aaa forma2", "species",
         "Kingdom1", "Phylum1", "ClassB", None, None, "2020-01-02"),
    ]
    conn, counts = _build(tmp_path, organism_records_rows=rows)
    assert counts["taxon"] == 1
    t = _taxon(conn, "common:taxon:gbif.51")
    assert t["status"] == "needs_review"
    assert t["class"] in ("ClassA", "ClassB")  # NULL-lastのタイブレークで決定論的に決まる


# ---------------------------------------------------------------------------
# F2: 分類補完(kingdom/phylum/class/taxon_group)
# ---------------------------------------------------------------------------


def test_own_classification_wins_over_majority(tmp_path):
    """出典自身が分類を持っていれば、それをそのまま使う（basis='source'）。"""
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Corvus corone", "species",
         "Animalia", "Chordata", "Aves", "Passeriformes", "Corvidae", "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["kingdom"] == "Animalia"
    assert t["phylum"] == "Chordata"
    assert t["class"] == "Aves"
    assert t["order"] == "Passeriformes"
    assert t["family"] == "Corvidae"
    assert t["classification_basis"] == "source"
    assert t["canonical_binomial"] == "Corvus corone"
    assert t["taxon_group"] == "鳥類"
    assert t["status"] == "accepted"


def test_binomial_majority_fills_missing_own_classification(tmp_path):
    """own class が無い記録(iNat 想定)は、同じ二名法キーの他記録の多数決で埋まる
    （basis='binomial_match'）。"""
    rows = [
        # GBIF側: 同じ binom で class を持つ記録（多数決の材料）。
        ("gbif_kanagawa_occurrences", "2", "Milvus migrans", "species",
         "Animalia", "Chordata", "Aves", "Accipitriformes", "Accipitridae", "2020-01-01"),
        # iNat側: 同じ binom・own class 無し（対象）。
        ("inaturalist_kanagawa", "500", "Milvus migrans", "species",
         None, None, None, None, None, "2020-02-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:inat.500")
    assert t["class"] == "Aves"
    assert t["kingdom"] == "Animalia"
    assert t["classification_basis"] == "binomial_match"
    assert t["status"] == "accepted"
    # order/family は多数決で補完しない(v1 も補完していない)。
    assert t["order"] is None
    assert t["family"] is None


def test_genus_majority_tie_marks_needs_review(tmp_path):
    """属単位の多数決が同数のとき、明示規則(件数降順、同数ならclass昇順)で
    決定論的に決め、その taxon を status='needs_review' にする。"""
    rows = [
        # 同じ属 Testgenus 内で class が1対1に割れる(tie)。
        ("gbif_kanagawa_occurrences", "10", "Testgenus aaa", "species",
         "Kingdom1", "PhylumX", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "11", "Testgenus bbb", "species",
         "Kingdom2", "PhylumY", "ClassB", None, None, "2020-01-02"),
        # 対象: own class 無し・binom 単位の多数決も無い(このbinomでclassを持つ記録が無い)。
        ("gbif_kanagawa_occurrences", "12", "Testgenus ccc", "species",
         None, None, None, None, None, "2020-01-03"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.12")
    assert t["classification_basis"] == "genus_match"
    assert t["class"] == "ClassA"  # 件数同数(1件ずつ)なので class 昇順で ClassA が勝つ
    assert t["status"] == "needs_review"

    # 明示的に own class を持つ taxon 自身は tie の影響を受けない。
    a = _taxon(conn, "common:taxon:gbif.10")
    assert a["classification_basis"] == "source"
    assert a["status"] == "accepted"


def test_unresolved_status_becomes_needs_review_when_classification_tied(tmp_path):
    """taxa 由来 unresolved (GBIF 未照合) 行でも、分類の多数決が不確か（同数・複数class
    にまたがる属）なら status='needs_review' に変わる（/code-review 指摘1。実データの
    *Martensia flabelliformis*——属の多数決が紅藻2件/端脚類2件の同数——で taxon_group が
    丸ごと変わりうるのに、以前は unresolved のまま隠れていた回帰）。
    """
    taxa_rows = [
        ("wamei:てすと", "Testgenus ddd", None, None, None,
         None, None, None, None, None),
    ]
    organism_rows = [
        ("gbif_kanagawa_occurrences", "10", "Testgenus aaa", "species",
         "Kingdom1", "PhylumX", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "11", "Testgenus bbb", "species",
         "Kingdom2", "PhylumY", "ClassB", None, None, "2020-01-02"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=organism_rows, taxa_rows=taxa_rows)
    t = _taxon(conn, "common:taxon:ryuiki-taxa.wamei.%E3%81%A6%E3%81%99%E3%81%A8")
    assert t["status"] == "needs_review"
    assert t["classification_basis"] == "genus_match"


def test_kingdom_only_tie_marks_needs_review_even_with_own_class(tmp_path):
    """own class はあるが own kingdom が無く、kingdom を二名法キーの多数決(bc)から
    補完するケースで、その bc の多数決が同数なら needs_review になる
    （/code-review 指摘2。以前は class が自前にあると bc の tie を一切見ておらず、
    kingdom 側の同数を見逃していた）。

    同じ binom "Testbinom aaa" で KingdomX/KingdomY が2件ずつの同数（bcのkingdomがtie）。
    対象行自身（own class はあるが own kingdom は無い）も class0 が非NULLなので bc の
    母集団に (ClassShared, kingdom0=NULL) として1件加わるが、最多得票数(2)には届かない
    ため tie の対象外（NULL が誤って勝つことはない）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "20", "Testbinom aaa", "species",
         "KingdomX", "Phylum1", "ClassShared", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "21", "Testbinom aaa", "species",
         "KingdomX", "Phylum1", "ClassShared", None, None, "2020-01-02"),
        ("inaturalist_kanagawa", "20", "Testbinom aaa", "species",
         "KingdomY", "Phylum1", "ClassShared", None, None, "2020-01-03"),
        ("inaturalist_kanagawa", "21", "Testbinom aaa", "species",
         "KingdomY", "Phylum1", "ClassShared", None, None, "2020-01-04"),
        # 対象: own class はある(ClassShared)が own kingdom が無い。
        ("gbif_kanagawa_occurrences", "22", "Testbinom aaa", "species",
         None, None, "ClassShared", None, None, "2020-01-05"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.22")
    assert t["class"] == "ClassShared"
    assert t["classification_basis"] == "source"  # class は own なので source
    assert t["kingdom"] == "KingdomX"  # 2対2の同数、kingdom昇順のタイブレークで KingdomX
    assert t["status"] == "needs_review"  # だが kingdom の補完元(bc)が同数なので要確認


def test_class_tie_with_matching_kingdom_does_not_mark_kingdom_needs_review(tmp_path):
    """bc の多数決が (class0, kingdom0) の組で同数でも、同数の候補どうしで kingdom
    が一致していれば（class だけが食い違っていても）needs_review にしない
    （/code-review 指摘2。`is_tied`——組全体の同数——をそのまま使うと、companion
    列(kingdom)が実は一致しているケースを誤検出する）。own class がある行は
    class 自体が bc を経由しないので、class 側の食い違いにも引きずられない。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "60", "Testk aaa", "species",
         "Animalia", "Phylum1", "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "61", "Testk aaa", "species",
         "Animalia", "Phylum1", "ClassA", None, None, "2020-01-02"),
        ("inaturalist_kanagawa", "60", "Testk aaa", "species",
         "Animalia", "Phylum1", "ClassB", None, None, "2020-01-03"),
        ("inaturalist_kanagawa", "61", "Testk aaa", "species",
         "Animalia", "Phylum1", "ClassB", None, None, "2020-01-04"),
        # 対象: own class はある(多数決には現れない値)が own kingdom が無い。
        ("gbif_kanagawa_occurrences", "62", "Testk aaa", "species",
         None, None, "ClassSelf", None, None, "2020-01-05"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.62")
    assert t["class"] == "ClassSelf"
    assert t["classification_basis"] == "source"
    assert t["kingdom"] == "Animalia"
    assert t["status"] == "accepted"  # class側のtie(A/B)に引きずられて誤検出しない


def test_bc_tie_null_last_prefers_non_null_kingdom(tmp_path):
    """bc の同数タイブレークは NULL を最後に回すので、(class=A, kingdom=NULL)×2 と
    (class=A, kingdom=K)×2 が同数のとき K が選ばれる（NULL が勝って kingdom が
    落ち taxon_group が「未判定」になる事故を防ぐ。/code-review 指摘2）。NULL は
    COUNT(DISTINCT ...) の対象外なので「食い違い」とは扱わず needs_review にもならない。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "70", "Testn aaa", "species",
         None, None, "ClassA", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "71", "Testn aaa", "species",
         None, None, "ClassA", None, None, "2020-01-02"),
        ("inaturalist_kanagawa", "70", "Testn aaa", "species",
         "K", None, "ClassA", None, None, "2020-01-03"),
        ("inaturalist_kanagawa", "71", "Testn aaa", "species",
         "K", None, "ClassA", None, None, "2020-01-04"),
        # 対象: own class・own kingdom とも無く、bc の多数決に頼る。
        ("gbif_kanagawa_occurrences", "72", "Testn aaa", "species",
         None, None, None, None, None, "2020-01-05"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.72")
    assert t["class"] == "ClassA"
    assert t["kingdom"] == "K"
    assert t["classification_basis"] == "binomial_match"
    assert t["status"] == "accepted"


def test_multi_class_genus_marks_needs_review_without_tie(tmp_path):
    """属の多数決で class を補完した taxon は、同数でなくてもその属が複数の class に
    またがっていれば needs_review にする（/code-review 指摘6。アドバイザーの概算で
    実データ約24 taxon。例: Pieris はチョウ目 Insecta が優勢だが被子植物
    Magnoliopsida も混じる）。
    """
    rows = [
        # 属 Multigen: Insecta が3件、Magnoliopsida が1件（同数ではないが複数classにまたがる）。
        ("gbif_kanagawa_occurrences", "30", "Multigen aaa", "species",
         None, None, "Insecta", None, None, "2020-01-01"),
        ("gbif_kanagawa_occurrences", "31", "Multigen bbb", "species",
         None, None, "Insecta", None, None, "2020-01-02"),
        ("gbif_kanagawa_occurrences", "32", "Multigen ccc", "species",
         None, None, "Insecta", None, None, "2020-01-03"),
        ("gbif_kanagawa_occurrences", "33", "Multigen ddd", "species",
         None, None, "Magnoliopsida", None, None, "2020-01-04"),
        # 対象: own class 無し・binom 単位の多数決も無い。属の多数決(Insecta、優勢)で埋まる。
        ("gbif_kanagawa_occurrences", "34", "Multigen eee", "species",
         None, None, None, None, None, "2020-01-05"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.34")
    assert t["classification_basis"] == "genus_match"
    assert t["class"] == "Insecta"  # 3対1で同数ではない(tieではない)
    assert t["status"] == "needs_review"  # が、属自体が複数classを含むので要確認


def test_classification_basis_no_match_when_nothing_resolves(tmp_path):
    """own も二名法キーの多数決も属の多数決も無ければ classification_basis='no_match'
    （旧名 'unresolved' から改名。status='unresolved'——GBIF backbone未照合——と
    文字列が同じで紛らわしかったため。/simplify 指摘11）。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Solounicum aaa", "species",
         None, None, None, None, None, "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["classification_basis"] == "no_match"
    assert t["class"] is None
    assert t["status"] == "accepted"  # 分類が不明でも backbone は accepted のまま


def test_representative_selection_uses_shared_source_namespace(tmp_path):
    """未知の source_id のエラーメッセージが、正の置き場(scripts/taxon_namespaces.py)
    を指す（/code-review 指摘5。SOURCE_NAMESPACE は build_taxon.py の private 定数
    ではなく scripts/taxon_namespaces.py の TAXON_KEY_SOURCE_NAMESPACE に移した。
    当初は scripts/common.py に置いたが、そのモジュールは requests に依存し
    CI（PyYAML・pytestしか入れない）で ModuleNotFoundError を起こしたため、
    依存の無いモジュールに切り出し直した）。
    """
    rows = [
        ("some_new_source", "1", "Foo bar", "species", None, None, None, None, None, "2020-01-01"),
    ]
    with pytest.raises(ValueError, match="scripts/taxon_namespaces.py"):
        _build(tmp_path, organism_records_rows=rows)


def test_taxon_group_default_is_unclassified(tmp_path):
    """taxon_group.yaml のどのルールにも一致しない場合は default_label_ja('未判定')。"""
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Mysterium unknownii", "species",
         "Chromista", "Foraminifera", "Foraminiferea", None, None, "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["taxon_group"] == "未判定"


def test_taxon_group_first_match_wins_over_later_rule(tmp_path):
    """class='Aves' は kingdom='Animalia' のルール(その他無脊椎動物)より先に
    一致するので、先勝ちで「鳥類」になる(taxon_group.yaml の順序を保つことの回帰)。
    """
    rows = [
        ("gbif_kanagawa_occurrences", "1", "Corvus corone", "species",
         "Animalia", "Chordata", "Aves", None, None, "2020-01-01"),
    ]
    conn, _counts = _build(tmp_path, organism_records_rows=rows)
    t = _taxon(conn, "common:taxon:gbif.1")
    assert t["taxon_group"] == "鳥類"


def test_taxon_group_yaml_rejects_duplicate_match_conditions(tmp_path, monkeypatch):
    """taxon_group.yaml は先勝ちの表なので、同じ match 条件が2回登場すると片方が
    黙って無効になる。build_place._load_zone_yaml()/build_caveat._load_caveat_yaml()
    と同じ流儀で重複を検知する（/simplify 指摘13）。
    """
    dup_yaml = tmp_path / "taxon_group.yaml"
    dup_yaml.write_text(
        "default_label_ja: \"未判定\"\n"
        "rules:\n"
        "  - match: { class: \"Aves\" }\n"
        "    label_ja: \"鳥類\"\n"
        # 配列の並び順が違うだけの同一条件（重複として検知されるべき）。
        "  - match: { class: [\"Squamata\", \"Testudines\"] }\n"
        "    label_ja: \"爬虫類\"\n"
        "  - match: { class: [\"Testudines\", \"Squamata\"] }\n"
        "    label_ja: \"別ラベル\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(build_taxon_module, "TAXON_GROUP_YAML", dup_yaml)
    with pytest.raises(AssertionError, match="match が重複している"):
        build_taxon_module._load_taxon_group_rules()
