"""`organism_records.taxon_key` の名前空間の正（phase-b/occurrence-registry, F1）。

`taxon_key` は出典によって別の数値空間が入っている: GBIF 由来行（taxon_key=GBIFの
taxonKey）は `'gbif'`、iNaturalist 由来行（taxon_key=iNaturalist自身のtaxon.id。
GBIFのtaxonKeyとは無関係な別の数値空間）は `'inat'`。`m03_organisms.py` が
`organism_records.source_id` にこの2値を書き込む。

**依存が要らない、レジストリのパッケージ（`scripts/registry/`）の外の1箇所**に
このデータを置く。`scripts/registry/build_taxon.py`（`taxon_id` を
`common:taxon:<namespace>.<key>` の形に組み立てる）はここを正として import する
（以前は build_taxon.py 内の private な辞書だったため、レジストリを経由しない
読み手に届かなかった）。`scripts/x01_dwca.py`（DwC-A 書き出し）は
`dwca_taxon_id()` で taxonID に名前空間を前置する（`gbif:8026`/`inat:8026`。Issue #34 D4。
公開物の意図的な変更）。`scripts/x03_verify_dwca.py` は `check_dwca_taxon_id()` で検証する。

**以前は `scripts/common.py`（収集系の共有モジュール）に置いていたが、
`scripts/common.py` は冒頭で `requests` を import しており、CI（`requirements.txt`
は PyYAML・pytest だけ）に `requests` が無いため
`scripts/registry/build_taxon.py`（→ `r01_build_registry.py --files-only`・
`scripts/tests/test_registry_taxon.py`）経由で `ModuleNotFoundError` を起こした
（実際にPR #15のCIで発生）。このモジュールは標準ライブラリにも `requests` にも
依存しない（import 時の副作用も無い）ことを条件に、ここへ切り出した。**
"""

TAXON_KEY_SOURCE_NAMESPACE = {
    "gbif_kanagawa_occurrences": "gbif",
    "inaturalist_kanagawa": "inat",
}


def assert_known_source_ids(source_ids, error_cls=ValueError) -> None:
    """`source_ids`（重複・`None` を含みうる `organism_records.source_id` の
    集まり）がすべて `TAXON_KEY_SOURCE_NAMESPACE` に含まれることを検証する。

    `scripts/registry/build_taxon.py` と `scripts/b06_build_occurrence.py` が
    同じ検査を別々に持っていた（呼び出し側が投げたい例外の型だけが違う）ため、
    ここに1本化した（/simplify 指摘1）。呼び出し側は `error_cls` で好きな
    例外クラスを指定できる（既定 `ValueError`。`b06` は
    `common.MigrationError` を渡す——このモジュールは依存の無いことが条件
    〔モジュール docstring 参照〕なので、`migrate.common` を直接 import しない）。

    未知の値があれば `error_cls(...)` を投げる。`None` は文字列と比較できず、
    素の `sorted()` は `str`/`None` が混ざると `TypeError` になる——
    `key=lambda v: (v is None, v)` で `None` を最後に回す（`b06` 側で先に
    見つかった潜在バグ。この統合で `build_taxon.py` 側の同じ潜在バグも直る）。
    """
    unknown = sorted(
        (s for s in set(source_ids) if s not in TAXON_KEY_SOURCE_NAMESPACE),
        key=lambda v: (v is None, v),
    )
    if unknown:
        raise error_cls(
            "taxon_id の名前空間が未定義の source_id がある"
            "（scripts/taxon_namespaces.py の TAXON_KEY_SOURCE_NAMESPACE に"
            f"追記すること）: {unknown}"
        )


# 外来種リスト（環境省 moe_ias_2015）の list_id。`registry/taxon/assessment_list.yaml` の値。
# b06（occurrence の is_alien_in_scope）と build_taxon_assessment.py が共有する
# （yaml に依存しないこのモジュールに置く。Issue #34）。
IAS_LIST_ID = "moe_ias_2015"


def binom_of(name: str | None) -> str | None:
    """学名の先頭2語（属+種）。web/scripts/build-biota.mjs の BINOM と同じ規則。
    `scripts/registry/build_taxon_assessment.py`（taxon_assessment.binom・in_scope）と
    `scripts/b06_build_occurrence.py`（is_alien_in_scope）が同じ規則で binom を取るための正。
    """
    if not name:
        return None
    toks = name.split(" ")
    if len(toks) < 2:
        return name
    return f"{toks[0]} {toks[1]}"


def dwca_taxon_id(source_id, taxon_key) -> str:
    """DwC-A の `taxonID`（Issue #34 D4）。出典の名前空間を前置する: `gbif:8026` / `inat:8026`。
    GBIF の taxonKey と iNaturalist の taxon.id は別の数値空間なので、前置しないと同じ数字が
    別の実体を指す。`taxon_key` が空なら空文字（taxonID を持たない行）。
    未知の `source_id` で taxon_key があるときは `ValueError`（黙って名前空間なしで出さない）。
    """
    if taxon_key is None or str(taxon_key) == "":
        return ""
    ns = TAXON_KEY_SOURCE_NAMESPACE.get(source_id)
    if ns is None:
        raise ValueError(
            f"DwC-A taxonID: source_id={source_id!r} の名前空間が未定義"
            "（TAXON_KEY_SOURCE_NAMESPACE に追記すること）"
        )
    return f"{ns}:{taxon_key}"


def check_dwca_taxon_id(taxon_id: str, occurrence_id: str) -> str | None:
    """`occurrence.txt` の 1 行の taxonID を検査する。問題があれば理由の文字列、無ければ None。
    空は許す（taxon_key の無い行）。非空は `^(gbif|inat):\\d+$`、かつ名前空間が
    `occurrenceID`（`<source_id>__<key>`）の出典と一致すること。
    """
    if taxon_id == "":
        return None
    ns, sep, key = taxon_id.partition(":")
    if not sep or not key.isdigit() or ns not in set(TAXON_KEY_SOURCE_NAMESPACE.values()):
        return "形式が <gbif|inat>:<数字> ではない"
    source_id = occurrence_id.split("__", 1)[0]
    if TAXON_KEY_SOURCE_NAMESPACE.get(source_id) != ns:
        return f"名前空間 {ns} が occurrenceID の出典 {source_id!r} と合わない"
    return None
