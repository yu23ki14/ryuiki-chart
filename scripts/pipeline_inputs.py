#!/usr/bin/env python3
"""原本・入力ファイル（`data/db/ryuiki.sqlite`・`cells.sqlite`・
`data/processed` の5ファイル）の一覧とハッシュの計算を1箇所にまとめる。

**このモジュールを作った理由（レビュー指摘）**: `scripts/s01_build_sample.py`
（`data/sample/manifest.json` の `source_files`）と
`scripts/b00_run_full_gate.py`（`reports/full_gate_proof.json` の
`source_hashes`）が、それぞれ別々にキーの付け方を決めていた
（前者は `"ryuiki.sqlite"`/`"processed/<name>"`、後者は
`"data/db/ryuiki.sqlite"`/`"data/processed/<name>"`）。CI の
`full-gate-proof-check` ジョブがこの2つを突き合わせる際、キーの形が違うため
`KeyError` で落ちる不具合になっていた。**両方がこのモジュールの
`SOURCE_FILE_KEYS`/`compute_source_hashes()` だけからキーを作ることで、
キーの形が2箇所で食い違う余地を無くす。**

キーはリポジトリルートからの相対パス（`"data/db/ryuiki.sqlite"` の形、
`/` 区切り）に統一する——`"ryuiki.sqlite"` だけだと `data/db/` 以外の
同名ファイルと区別できず曖昧だが、リポジトリルート相対パスなら一意に決まる。

`SOURCE_FILE_KEYS`（`data/processed` の5ファイル）は
`data/sample/coverage.yaml` の `wholesale_processed_files` と同じ集合で
あることを `scripts/tests/test_pipeline_inputs.py` が確認する（コード側の
定数と YAML の宣言が黙って食い違うのを防ぐ——値を二重管理する代わりに、
値が同じであることをテストで機械的に保証する）。
"""
from __future__ import annotations

import hashlib
import pathlib

# リポジトリルートからの相対パス。原本2つ（ryuiki.sqlite・cells.sqlite）＋
# data/processed の入力5つ（v1・v2 のどちらかが読むもの。
# data/sample/coverage.yaml の wholesale_processed_files と同じ集合）。
SOURCE_FILE_KEYS: tuple[str, ...] = (
    "data/db/ryuiki.sqlite",
    "data/db/cells.sqlite",
    "data/processed/nlni_w12_watersheds.geojson",
    "data/processed/nlni_w12_watersheds.jsonl",
    "data/processed/nlni_l03b_landuse_by_watershed.csv",
    "data/processed/moe_ias_list.csv",
    "data/processed/taxon_crosswalk.csv",
)


def sha256_file(path) -> str:
    # scripts/common.py にも同じロジックの sha256() があるが、あちらは
    # モジュール先頭で `import requests` する（CI が入れるのは PyYAML・pytest
    # だけなので ModuleNotFoundError になる——taxon_namespaces.py を切り出した
    # のと同じ理由。code-review 指摘対応）。このモジュールは CI から
    # 依存無しで呼べる必要があるため、あえて再実装する。
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_source_paths(ryuiki_db, cells_db, processed_dir) -> dict[str, pathlib.Path]:
    """`SOURCE_FILE_KEYS` の各キーに対応する、実際のファイルパスを返す。

    原本・入力ファイルの実体の在り処は呼び出し側ごとに違う
    （`scripts/s01_build_sample.py` は `--ryuiki-db`/`--cells-db`/
    `--processed-dir` の CLI 引数、`scripts/b00_run_full_gate.py` は
    リポジトリの既定パス）ため引数で受ける。`SOURCE_FILE_KEYS` の
    `"data/processed/<name>"` は `processed_dir/<name>` に対応する
    （`<name>` はキーの末尾のファイル名部分）。
    """
    processed_dir = pathlib.Path(processed_dir)
    paths: dict[str, pathlib.Path] = {}
    for key in SOURCE_FILE_KEYS:
        if key == "data/db/ryuiki.sqlite":
            paths[key] = pathlib.Path(ryuiki_db)
        elif key == "data/db/cells.sqlite":
            paths[key] = pathlib.Path(cells_db)
        else:
            filename = key.rsplit("/", 1)[-1]
            paths[key] = processed_dir / filename
    return paths


def compute_source_hashes(ryuiki_db, cells_db, processed_dir) -> dict[str, str]:
    """`SOURCE_FILE_KEYS` をキーにした sha256 の辞書
    （`scripts/s01_build_sample.py` の `manifest.json["source_files"]`・
    `scripts/b00_run_full_gate.py` の `full_gate_proof.json["source_hashes"]`
    のどちらもこれを呼ぶ）。ファイルが1つでも無ければ、どのキーに対応する
    ファイルが無いかを名指しした `FileNotFoundError` を投げる
    （黙って一部だけのハッシュを返さない）。
    """
    paths = resolve_source_paths(ryuiki_db, cells_db, processed_dir)
    out: dict[str, str] = {}
    for key, path in paths.items():
        if not path.exists():
            raise FileNotFoundError(f"原本・入力ファイルが無い: {path}（キー: {key!r}）")
        out[key] = sha256_file(path)
    return out
