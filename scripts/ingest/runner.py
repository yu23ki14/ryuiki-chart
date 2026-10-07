"""adapter を回し、共通検査を通して occurrence の行へ渡す（Issue #40 Phase D、ADR-0012 改定）。

`scripts/b06_build_occurrence.py` が、`adapter` が `builtin` でない target=occurrence のマニフェストごとに
`AdapterRun` を作り、`rows()` を既存の organism_records と同じ後段（region・taxon 解決・place・期間・挿入）に流す。
ここで行うのは adapter の出力の**契約検査**と、マニフェストの `checks`:

- 行が dict で、列契約（`ingest.api`）どおりの型・組（lat/lon は両方あるか両方無い）であること
- `record_key` が非空・出典内で一意（重複は止まる。黙って片方を捨てない）
- `checks`（`not_null`/`unique`/`row_count_between`/`in_registry`/`date_between`）
- `taxon_id` が registry に実在すること（`in_registry: taxon` を書かなくても b06 の解決で止まる。
  `checks` の `in_registry` は adapter の出力段で早く・名指しで落とすための宣言）

adapter は `importlib` で `adapters.<source_id>` を読み、`rows(ctx)` を呼ぶ（モジュール名は
マニフェストの `adapter` で、`source` と同じ名前に限る。`ingest.manifest` が検証済み）。
"""
from __future__ import annotations

import csv
import importlib
import pathlib
import math
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Iterator

from migrate.common import MigrationError

from . import api
from .manifest import Manifest, ROOT

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass
class AdapterRow:
    record_key: str
    taxon_id: str | None
    observed_on_raw: str | None
    lat: float | None
    lon: float | None
    scientific_name: str | None = None
    vernacular_name: str | None = None
    taxon_rank: str | None = None
    red_list_category: str | None = None
    license_class: str | None = None
    attributes: dict = field(default_factory=dict)
    coordinate_uncertainty_m: float | None = None


def _number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


class AdapterRun:
    """1 つのマニフェスト（非 builtin の occurrence）の実行。`rows()` を最後まで消費してから `problems()` を読む。"""

    def __init__(self, manifest: Manifest, work: sqlite3.Connection, taxon_ids: set[str], *, root=ROOT):
        if manifest.is_builtin:
            raise MigrationError(f"{manifest.source}: adapter=builtin は AdapterRun で回さない（b03/b06 が処理する）")
        self.manifest = manifest
        self._work = work
        self._taxon_ids = taxon_ids
        self._root = pathlib.Path(root)
        self.n_rows = 0
        self.n_attributes = 0
        self._seen_keys: set[str] = set()
        self._unique_seen: dict[tuple, set] = {}
        self._problems: list[str] = []
        # checks（1 キーの dict のリスト）は最初に 1 回だけ (名前, 引数) に分解する
        self._checks = [next(iter(c.items())) for c in manifest.checks]
        self._finished = False

    # --- 入力（読み取り専用の窓。adapter には接続を渡さない）-------------------------------------
    def _input_rows(self) -> Iterator[dict]:
        kind, value = next(iter(self.manifest.input.items()))
        if kind == "table":
            if not _IDENT_RE.match(value):
                raise MigrationError(f"{self.manifest.source}: input.table={value!r} が識別子の形でない")
            cur = self._work.execute(f'SELECT * FROM src."{value}" ORDER BY rowid')
            cols = [d[0] for d in cur.description]
            for row in cur:
                yield dict(zip(cols, row))
        else:
            path = pathlib.Path(value)
            if path.is_absolute() or ".." in path.parts:
                raise MigrationError(f"{self.manifest.source}: input.file={value!r} はリポジトリ内の相対パスでなければならない")
            with open(self._root / path, encoding="utf-8", newline="") as f:
                yield from csv.DictReader(f)

    # --- 実行 ---------------------------------------------------------------------------------
    def rows(self) -> Iterator[AdapterRow]:
        m = self.manifest
        try:
            module = importlib.import_module(f"adapters.{m.adapter}")
        except ImportError as e:
            raise MigrationError(f"{m.source}: adapter モジュール adapters.{m.adapter} を読み込めない: {e}") from e
        fn = getattr(module, "rows", None)
        if not callable(fn):
            raise MigrationError(f"{m.source}: adapters.{m.adapter} に rows(ctx) が無い")
        ctx = api.Ctx(source_id=m.source, region_id=m.region, input_rows=self._input_rows)
        for i, raw in enumerate(fn(ctx), start=1):
            row = self._validate(raw, i)
            self.n_rows += 1
            if row.attributes:
                self.n_attributes += 1
            self._apply_row_checks(row, i)
            yield row
        self._finished = True

    def _validate(self, raw, i: int) -> AdapterRow:
        src = self.manifest.source
        if not isinstance(raw, dict):
            raise MigrationError(f"{src}: adapter の {i} 行目が dict でない（実際: {type(raw).__name__}）")
        extra = sorted(set(raw) - set(api.ROW_COLUMNS) - set(api.OPTIONAL_COLUMNS))
        missing = [c for c in api.ROW_COLUMNS if c not in raw]
        if extra or missing:
            raise MigrationError(f"{src}: adapter の {i} 行目の列が契約と違う（未知: {extra} / 欠け: {missing}）。"
                                 "ingest.api.occurrence_row() で作ること")
        key = raw["record_key"]
        if not isinstance(key, str) or not key:
            raise MigrationError(f"{src}: adapter の {i} 行目の record_key が空/非文字列: {key!r}")
        if key in self._seen_keys:
            raise MigrationError(f"{src}: record_key が重複している: {key!r}（{i} 行目）。黙って片方を捨てない")
        self._seen_keys.add(key)
        lat, lon = raw["lat"], raw["lon"]
        if (lat is None) != (lon is None):
            raise MigrationError(f"{src}: lat/lon の片方だけが無い: record_key={key!r}")
        if lat is not None and not (_number(lat) and _number(lon)):
            raise MigrationError(f"{src}: lat/lon が数値でない: record_key={key!r} lat={lat!r} lon={lon!r}")
        unc = raw.get("coordinate_uncertainty_m")
        if unc is not None:
            if not _number(unc) or unc < 0 or not math.isfinite(unc):
                raise MigrationError(
                    f"{src}: coordinate_uncertainty_m が非負の有限な数値でない: record_key={key!r} 値={unc!r}")
            if lat is None:
                raise MigrationError(
                    f"{src}: 座標が無いのに coordinate_uncertainty_m がある: record_key={key!r} 値={unc!r}")
        for c in ("taxon_id", "observed_on_raw", "scientific_name", "vernacular_name", "taxon_rank",
                  "red_list_category", "license_class"):
            v = raw.get(c)
            if v is not None and not isinstance(v, str):
                raise MigrationError(f"{src}: {c} が文字列でない: record_key={key!r} 値={v!r}")
        attrs = raw.get("attributes") or {}
        if not isinstance(attrs, dict):
            raise MigrationError(f"{src}: attributes が dict でない: record_key={key!r}")
        return AdapterRow(
            record_key=key, taxon_id=raw["taxon_id"], observed_on_raw=raw["observed_on_raw"],
            lat=None if lat is None else float(lat), lon=None if lon is None else float(lon),
            scientific_name=raw.get("scientific_name"), vernacular_name=raw.get("vernacular_name"),
            taxon_rank=raw.get("taxon_rank"), red_list_category=raw.get("red_list_category"),
            license_class=raw.get("license_class"), attributes=attrs,
            coordinate_uncertainty_m=None if unc is None else float(unc),
        )

    def _apply_row_checks(self, row: AdapterRow, i: int) -> None:
        src = self.manifest.source
        for name, arg in self._checks:
            if name == "not_null":
                for col in arg:
                    if getattr(row, col) is None:
                        self._problems.append(f"{src}: checks.not_null[{col}] に違反（record_key={row.record_key!r}）")
            elif name == "unique":
                tup = tuple(getattr(row, c) for c in arg)
                seen = self._unique_seen.setdefault(tuple(arg), set())
                if tup in seen:
                    self._problems.append(f"{src}: checks.unique[{','.join(arg)}] に違反（{tup!r}）")
                seen.add(tup)
            elif name == "in_registry":
                if row.taxon_id is not None and row.taxon_id not in self._taxon_ids:
                    self._problems.append(
                        f"{src}: checks.in_registry[taxon]: {row.taxon_id!r} が registry に無い（record_key={row.record_key!r}）"
                    )
            elif name == "date_between":
                lo, hi = arg
                d = (row.observed_on_raw or "")[:10]
                if row.observed_on_raw is not None and not (lo <= d <= hi):
                    self._problems.append(
                        f"{src}: checks.date_between[{lo}..{hi}] に違反: {row.observed_on_raw!r}（record_key={row.record_key!r}）"
                    )

    def problems(self, limit: int = 20) -> list[str]:
        """全行を消費したあとの問題一覧（行ごとの検査と `row_count_between`）。空なら問題なし。"""
        if not self._finished:
            raise MigrationError(f"{self.manifest.source}: rows() を最後まで消費する前に problems() を呼んだ")
        out = list(self._problems)
        for name, arg in self._checks:
            if name == "row_count_between" and not (arg[0] <= self.n_rows <= arg[1]):
                out.append(f"{self.manifest.source}: checks.row_count_between[{arg[0]}..{arg[1]}] に違反（実測 {self.n_rows}）")
        if len(out) > limit:
            out = out[:limit] + [f"…ほか {len(out) - limit} 件"]
        return out
