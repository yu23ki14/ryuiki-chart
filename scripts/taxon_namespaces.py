"""`organism_records.taxon_key` の名前空間の正（phase-b/occurrence-registry, F1）。

`taxon_key` は出典によって別の数値空間が入っている: GBIF 由来行（taxon_key=GBIFの
taxonKey）は `'gbif'`、iNaturalist 由来行（taxon_key=iNaturalist自身のtaxon.id。
GBIFのtaxonKeyとは無関係な別の数値空間）は `'inat'`。`m03_organisms.py` が
`organism_records.source_id` にこの2値を書き込む。

**依存が要らない、レジストリのパッケージ（`scripts/registry/`）の外の1箇所**に
このデータを置く。`scripts/registry/build_taxon.py`（`taxon_id` を
`common:taxon:<namespace>.<key>` の形に組み立てる）はここを正として import する
（以前は build_taxon.py 内の private な辞書だったため、レジストリを経由しない
読み手に届かなかった）。`scripts/x01_dwca.py`（DwC-A 書き出し）はまだこれを
経由せず、生の taxon_key を出典の区別なしに taxonID にそのまま書いている
（docs/plans/PHASE_B_INTAKE.md 参照。直すのは公開物の意図的な変更になるため別PR）。

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
