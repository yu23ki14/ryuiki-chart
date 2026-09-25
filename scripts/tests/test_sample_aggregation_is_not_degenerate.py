"""縮小サンプルの集計が「1件をそのまま写す」空振りになっていないことを、
サンプル自身の v1 出力の指紋（`data/sample/derived_baseline.json`）から機械で
確かめる（レビュー指摘対応。原本DB・材料化も不要——コミット済みの JSON を
読むだけ）。

対象は「集計対象の生レコード数」を持つ列（`n`/`n_raw`/`n_hours`。表ごとの
意味は `docs/plans/PHASE_B_FACT_SLICE.md`/`PHASE_B_OCCURRENCE.md` 参照）で、
`species_n`/`mesh_n`/`n_sites`/`alien_n`/`redlist_n`/`n_cells`/`n_warnings`
のような「distinct な別次元の件数」はここでは見ない
（0件・1件でも実データとして正当にありうるため——例えば
`doc_series_meta.n_warnings` は警告0件が普通に起こる）。

`n`/`n_raw`/`n_hours` の最大値が1以下なら、その表の集計セルはどれも
「元レコード1件をそのまま写しただけ」で、v1 と v2 の集計方法の違い
（`AVG`/`SUM` の丸め、複数レコードの合成規則の違い等）を一度も試していない
ことになる。1つでもあれば非0で落とす。
"""
from __future__ import annotations

import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLE_DIR = ROOT / "data" / "sample"

# 「集計対象の生レコード数」を意味する列名だけ（distinct 系の別次元件数は対象外。
# モジュール docstring 参照）。
_RAW_COUNT_COLUMNS = ("n", "n_raw", "n_hours")

pytestmark = pytest.mark.skipif(
    not (SAMPLE_DIR / "derived_baseline.json").exists(),
    reason="data/sample/derived_baseline.json が無い",
)


@pytest.fixture(scope="module")
def baseline() -> dict:
    return json.loads((SAMPLE_DIR / "derived_baseline.json").read_text(encoding="utf-8"))


def _tables_with_raw_count_column(baseline: dict) -> dict[str, str]:
    """表名 -> 実際に持っている `_RAW_COUNT_COLUMNS` のうちの1列名。"""
    out: dict[str, str] = {}
    for table, spec in baseline["tables"].items():
        numeric = spec["numeric_columns"]
        for col in _RAW_COUNT_COLUMNS:
            if col in numeric:
                out[table] = col
                break
    return out


def test_at_least_the_reviewer_named_tables_have_a_raw_count_column(baseline):
    """レビューで名指しされた表（meas_daily 等）が、この検証の対象として
    実際に拾えていることの自己チェック（列名を変える将来のリファクタで
    静かに対象から漏れるのを防ぐ）。
    """
    named = {
        "meas_daily", "meas_month", "meas_year", "sensor_daily", "rain_daily",
        "sensor_hour_month", "zone_year", "org_group_year", "species_year2",
        "mesh_year", "org_watershed_year",
    }
    covered = set(_tables_with_raw_count_column(baseline))
    missing = named - covered
    assert not missing, f"想定していた表が対象から漏れている: {sorted(missing)}"


def test_raw_count_columns_are_not_degenerate(baseline):
    """`n`/`n_raw`/`n_hours` を持つ表**すべて**（レビューが名指しした表に限らない）
    で、最大値が2以上であることを確認する。
    """
    problems = []
    for table, col in sorted(_tables_with_raw_count_column(baseline).items()):
        max_value = float(baseline["tables"][table]["numeric_columns"][col]["max"])
        if max_value < 2:
            problems.append(f"{table}.{col}: max={max_value:g}")
    assert not problems, "集計が空振り（最大値が2未満）の表・列:\n" + "\n".join(problems)
