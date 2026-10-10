"""マニフェスト（`manifests/<source_id>.yml`）の読み込みと構造検証（Issue #40 Phase D、ADR-0012 改定）。

マニフェスト = 宣言（YAML）。ソース固有の変換は `scripts/adapters/<source_id>.py`（短い Python）に書く。
変換 DSL は作らない（ADR-0012 の `map:` は撤回した）。

## キー

必須: `source`（ファイル名の stem と一致。`source_registry.source_id` との一致は registry ビルドが検査する）,
`region`（`registry/region.yaml` に在る region_id）, `target`（`observation`|`occurrence`）,
`update_mode`（`snapshot|append|revision|static`。**未宣言は止める**。推測で埋めない）,
`input`（`{table: …}` か `{file: …}` のどちらか 1 つ）, `adapter`（`builtin` か、`scripts/adapters/` のモジュール名
＝`source` と同じ名前）, `evidence`（宣言の根拠）。
任意: `expected_row_count`（取り込む行数の宣言。b03/b06 が実測と突合する）, `checks`（下記）, `edition`
（`registry/source/editions.yaml` の `edition_key` への参照。インライン版は書かない）, `expected`（下記）。

## `adapter: builtin`

既存の 5 系統（measurements・sensor_timeseries・土地利用・organism_records）の変換は b03/b06 のまま
（数百万行の出力を 1 ビットも動かさない）。マニフェストはメタデータ（region・update_mode・expected_row_count・
edition 参照）だけを持つ。`checks` は書けない。`expected` は **target=occurrence のときだけ任意**（下記。奄美の出現の
件数の宣言。既存出典の宣言は `scripts/migrate/*.yaml` のまま）。b03/b06 は、マニフェストに無い出典・
マニフェストにあるのに誰も処理しない出典のどちらも止める。

## `checks`（実装済みの語彙だけ。非 builtin のみ）

`not_null: [列…]` / `unique: [列…]` / `row_count_between: [最小, 最大]` / `in_registry: taxon` /
`date_between: [最小日, 最大日]`（`observed_on_raw` の先頭 10 桁の文字列比較）。列は adapter が返す行の列契約。

## `expected`（target=occurrence のみ。非 builtin は必須、builtin は任意）

既存出典の宣言（`scripts/migrate/occurrence_*.yaml`）は変更しない。新出典の宣言値は**ここに書く**
（ソース追加で `scripts/migrate/` を触らないため。b06/b07/b09 は yaml の宣言値とここの値の和と突合する）。

    expected:
      period_shapes: {day: 400}          # 期間の形ごとの件数（b06）
      place:                             # 座標のある行（b09）
        coord_resolved: 0                #   流域に解決した件数
        coord_unresolved: 0              #   どの流域にも入らない件数
      cube:                              # b07
        dated_rows: 400                  #   日付あり行数
        dated_no_coordinate_rows: 400    #   うち座標なし（grid01 には入れず watershed の place_id NULL セルにだけ入る）
        leaf_cell_source_rows: 0         #   年をまたぐ区間の件数
        leaf_cell_source_rows_no_coordinate: 0   # うち座標なし
        month_cell_source_rows: 0        #   月セルに入る件数（座標あり）
        watershed_dated_resolved_rows: 0
        watershed_dated_unresolved_rows: 400
"""
from __future__ import annotations

import copy
import pathlib
import re
from dataclasses import dataclass, field, replace

import regions
from migrate.common import MigrationError, load_yaml, parse_manifest_inputs

from .api import ROW_COLUMNS  # adapter が返す行の列契約（正は api.py の 1 か所。`checks` の列名の検証に使う）

ROOT = pathlib.Path(__file__).resolve().parents[2]
DEFAULT_MANIFESTS_DIR = ROOT / "manifests"
DEFAULT_ADAPTERS_DIR = ROOT / "scripts" / "adapters"

# `registry/source/editions.yaml` の `update_mode_codes` と同じ集合（テストが一致を固定する）。
UPDATE_MODE_CODES = ("snapshot", "append", "revision", "static")
TARGET_CODES = ("observation", "occurrence")
BUILTIN = "builtin"
CHECK_NAMES = ("not_null", "unique", "row_count_between", "in_registry", "date_between")

_SOURCE_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")

REQUIRED_KEYS = ("source", "region", "target", "update_mode", "input", "adapter", "evidence")
OPTIONAL_KEYS = ("expected_row_count", "checks", "edition", "expected", "expected_place_region_null_rows",
                 "expected_absent_excluded_rows",
                 "sample_input_max_rows")

EXPECTED_PLACE_KEYS = ("coord_resolved", "coord_unresolved")
EXPECTED_CUBE_KEYS = (
    "dated_rows", "dated_no_coordinate_rows", "leaf_cell_source_rows", "leaf_cell_source_rows_no_coordinate",
    "month_cell_source_rows", "watershed_dated_resolved_rows", "watershed_dated_unresolved_rows",
)


@dataclass(frozen=True)
class Manifest:
    source: str
    region: str
    target: str
    update_mode: str
    input: dict
    adapter: str
    evidence: str
    expected_row_count: int | None = None
    checks: tuple = ()
    edition: str | None = None
    expected: dict | None = None
    # b03（観測）: place が region を持たない（place.region_id NULL）のに、マニフェストの region で決めた行の件数の宣言（既定 0）。
    # ADR-0022 決定3: region は出典から決め place 経由は照合だが、place 側が NULL の行は照合できない。黙って増えないよう宣言で固定する。
    expected_place_region_null_rows: int = 0
    # b06（出現）: organism_records.occurrence_status='ABSENT'（GBIF の不在記録）を occurrence から除いた行数の宣言（既定 0）。
    # 不在記録は原本に残し、出現として数えない（ADR-0025 の 2026-10-07 追記）。実測と食い違えば b06 が止まる。
    expected_absent_excluded_rows: int = 0
    # 縮小サンプルに入力表を全件入れてよい行数の、この出典だけの上限（scripts/s01_build_sample.py が見る）。
    # 既定（None）は s01 の ADAPTER_INPUT_WHOLESALE_MAX_ROWS。入力表を絞る経路は無いので、大きい表の出典だけが宣言する。
    sample_input_max_rows: int | None = None
    path: str = ""

    @property
    def is_builtin(self) -> bool:
        return self.adapter == BUILTIN

    @property
    def count_breakdown(self) -> dict[str, int]:
        """縮小サンプルの件数 overlay が差し替えられる内訳（`manifests:<source>.<キー>`）。宣言が 0 より大きいものだけ。
        source_regions・s01・test_sample_coverage はこの 1 か所から導く。"""
        return {"absent_excluded_rows": self.expected_absent_excluded_rows} if self.expected_absent_excluded_rows else {}


def _non_negative_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v >= 0


def _expected_problems(label: str, expected) -> list[str]:
    if not isinstance(expected, dict):
        return [f"{label}.expected がマッピングになっていない"]
    problems: list[str] = []
    extra = sorted(set(expected) - {"period_shapes", "place", "cube"})
    missing = sorted({"period_shapes", "place", "cube"} - set(expected))
    if extra:
        problems.append(f"{label}.expected に未知のキー: {extra}")
    if missing:
        problems.append(f"{label}.expected に必須キーが無い: {missing}")
    shapes = expected.get("period_shapes")
    if "period_shapes" in expected:
        if not isinstance(shapes, dict):
            problems.append(f"{label}.expected.period_shapes がマッピングになっていない")
        else:
            problems += [
                f"{label}.expected.period_shapes.{k} が非負整数でない（実際: {v!r}）"
                for k, v in shapes.items() if not _non_negative_int(v)
            ]
    for key, names in (("place", EXPECTED_PLACE_KEYS), ("cube", EXPECTED_CUBE_KEYS)):
        if key not in expected:
            continue
        sub = expected[key]
        if not isinstance(sub, dict):
            problems.append(f"{label}.expected.{key} がマッピングになっていない")
            continue
        if set(sub) != set(names):
            problems.append(f"{label}.expected.{key} のキーが想定と違う（期待: {sorted(names)}、実際: {sorted(sub)}）")
        problems += [
            f"{label}.expected.{key}.{k} が非負整数でない（実際: {v!r}）"
            for k, v in sub.items() if k in names and not _non_negative_int(v)
        ]
    return problems


def _checks_problems(label: str, checks) -> list[str]:
    if not isinstance(checks, list):
        return [f"{label}.checks がリストになっていない"]
    problems: list[str] = []
    for i, c in enumerate(checks):
        if not isinstance(c, dict) or len(c) != 1:
            problems.append(f"{label}.checks[{i}] は 1 キーのマッピングでなければならない（実際: {c!r}）")
            continue
        (name, arg), = c.items()
        if name not in CHECK_NAMES:
            problems.append(f"{label}.checks[{i}] の語彙が未知: {name!r}（使えるもの: {list(CHECK_NAMES)}）")
        elif name in ("not_null", "unique"):
            if not (isinstance(arg, list) and arg and all(a in ROW_COLUMNS for a in arg)):
                problems.append(f"{label}.checks[{i}].{name} は列のリスト（{list(ROW_COLUMNS)} のいずれか）でなければならない")
        elif name == "row_count_between":
            if not (isinstance(arg, list) and len(arg) == 2 and all(_non_negative_int(a) for a in arg) and arg[0] <= arg[1]):
                problems.append(f"{label}.checks[{i}].row_count_between は [最小, 最大]（非負整数、最小<=最大）")
        elif name == "in_registry":
            if arg != "taxon":
                problems.append(f"{label}.checks[{i}].in_registry は現状 `taxon` のみ（実際: {arg!r}）")
        elif name == "date_between":
            if not (isinstance(arg, list) and len(arg) == 2 and all(isinstance(a, str) and len(a) == 10 for a in arg)):
                problems.append(f"{label}.checks[{i}].date_between は ['YYYY-MM-DD', 'YYYY-MM-DD']")
    return problems


def manifest_problems(raw, stem: str, *, adapters_dir=None) -> list[str]:
    """生の dict の構造の問題を文字列のリストで返す（空なら問題なし。原本 DB 不要。CI とロード時の両方が使う）。"""
    label = stem
    adapters_dir = adapters_dir or DEFAULT_ADAPTERS_DIR  # 呼び出し時に解決する（テストが差し替えられる）
    if not isinstance(raw, dict):
        return [f"{label}: マッピングになっていない"]
    problems: list[str] = []
    unknown = sorted(set(raw) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS))
    if unknown:
        problems.append(f"{label}: 未知のキー {unknown}（使えるキー: {list(REQUIRED_KEYS + OPTIONAL_KEYS)}）")
    missing = [k for k in REQUIRED_KEYS if raw.get(k) in (None, "", {})]
    if missing:
        problems.append(f"{label}: 必須キーが欠けている（または空）: {missing}")
    if raw.get("source") not in (None, "") and raw.get("source") != stem:
        problems.append(f"{label}: source={raw.get('source')!r} がファイル名（{stem}.yml）と一致しない")
    if not _SOURCE_ID_RE.match(stem):
        problems.append(f"{label}: ファイル名が source_id の形（小文字英数字と _）でない")
    if raw.get("target") not in (None, "") and raw["target"] not in TARGET_CODES:
        problems.append(f"{label}.target={raw['target']!r} が未知（使えるもの: {list(TARGET_CODES)}。feature/place/document は需要が出るまで書けない）")
    if raw.get("update_mode") not in (None, "") and raw["update_mode"] not in UPDATE_MODE_CODES:
        problems.append(f"{label}.update_mode={raw['update_mode']!r} が未知（使えるもの: {list(UPDATE_MODE_CODES)}）")
    inp = raw.get("input")
    if inp not in (None, "", {}):
        if not (isinstance(inp, dict) and len(inp) == 1 and next(iter(inp)) in ("table", "file")
                and isinstance(next(iter(inp.values())), str) and next(iter(inp.values()))):
            problems.append(f"{label}.input は {{table: 名前}} か {{file: パス}} のどちらか 1 つ（実際: {inp!r}）")
    if "expected_place_region_null_rows" in raw and not _non_negative_int(raw["expected_place_region_null_rows"]):
        problems.append(f"{label}.expected_place_region_null_rows が非負整数でない（実際: {raw['expected_place_region_null_rows']!r}）")
    if "expected_absent_excluded_rows" in raw and not _non_negative_int(raw["expected_absent_excluded_rows"]):
        problems.append(f"{label}.expected_absent_excluded_rows が非負整数でない（実際: {raw['expected_absent_excluded_rows']!r}）")
    elif raw.get("expected_absent_excluded_rows") and (raw.get("adapter") != BUILTIN or raw.get("target") != "occurrence"):
        # 不在記録の除外は b06 の organism_records 経路（adapter=builtin・target=occurrence）にしか無い
        problems.append(
            f"{label}.expected_absent_excluded_rows は adapter=builtin かつ target=occurrence のマニフェストにだけ書ける"
            f"（実際: adapter={raw.get('adapter')!r}, target={raw.get('target')!r}）"
        )
    if "sample_input_max_rows" in raw:
        v = raw["sample_input_max_rows"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v > 0):
            problems.append(f"{label}.sample_input_max_rows が正の整数でない（実際: {v!r}）")
        elif raw.get("adapter") == BUILTIN:
            problems.append(f"{label}: adapter=builtin に sample_input_max_rows は書けない（adapter 出典の入力表の上限）")
    if "expected_row_count" in raw and not _non_negative_int(raw["expected_row_count"]):
        problems.append(f"{label}.expected_row_count が非負整数でない（実際: {raw['expected_row_count']!r}）")
    builtin = raw.get("adapter") == BUILTIN
    if raw.get("adapter") not in (None, "") and not builtin:
        a = raw["adapter"]
        if a != stem:
            problems.append(f"{label}.adapter={a!r}: `builtin` か、source と同じ名前のモジュール（scripts/adapters/{stem}.py）でなければならない")
        elif not (pathlib.Path(adapters_dir) / f"{a}.py").is_file():
            problems.append(f"{label}.adapter={a!r}: {pathlib.Path(adapters_dir) / (a + '.py')} が無い")
    if builtin:
        if raw.get("checks"):
            problems.append(f"{label}: adapter=builtin に checks は書けない（b03/b06 が自分で検査する）")
        # 緩和（奄美 Step 1 PR-B 決定8）: builtin でも target=occurrence なら expected を書ける。既存出典（神奈川）の宣言は
        # scripts/migrate/*.yaml のまま、新しい地域の出現の件数はマニフェストに書く。他の組み合わせは従来どおり書けない。
        if "expected" in raw:
            if raw.get("target") == "occurrence":
                problems += _expected_problems(label, raw["expected"])
                # 既存の地域（baseline）の builtin 出現は、件数の宣言を scripts/migrate/*.yaml が既に持つ。
                # 両方に書くと二重計上になる（b06/b07/b09 は yaml の値にマニフェストの合計を足す）ので止める。
                if raw.get("region") in regions.REGIONS and regions.is_baseline(raw["region"]):
                    problems.append(
                        f"{label}: 既存の地域（region={raw['region']}）の builtin 出現は expected を書けない"
                        "（scripts/migrate/*.yaml が既に宣言を持つ。二重に数える）"
                    )
            else:
                problems.append(
                    f"{label}: adapter=builtin に expected は target=occurrence のときしか書けない"
                    "（既存出典の宣言は scripts/migrate/*.yaml が持つ）"
                )
    elif raw.get("adapter") not in (None, ""):
        if "expected_row_count" not in raw:
            problems.append(f"{label}: 非 builtin は expected_row_count が必須（取り込み件数の宣言）")
        if raw.get("target") == "occurrence":
            if "expected" not in raw:
                problems.append(f"{label}: 非 builtin の occurrence は expected が必須")
            else:
                problems += _expected_problems(label, raw["expected"])
        elif "expected" in raw:
            problems.append(f"{label}: expected は target=occurrence のみ")
        if "checks" in raw:
            problems += _checks_problems(label, raw["checks"])
    if "edition" in raw and not (isinstance(raw["edition"], str) and raw["edition"]):
        problems.append(f"{label}.edition は editions.yaml の edition_key（文字列）でなければならない")
    return problems


def validate_manifests_shape(manifests_dir=DEFAULT_MANIFESTS_DIR, *, adapters_dir=None) -> None:
    """構造検証（原本 DB 不要。CI 用）。1 件でも問題があれば全部まとめて止まる。"""
    manifests_dir = pathlib.Path(manifests_dir)
    if not manifests_dir.is_dir():
        raise MigrationError(f"{manifests_dir} がディレクトリでない（マニフェストの置き場）")
    problems: list[str] = []
    stray = sorted(p.name for p in manifests_dir.iterdir() if p.is_file() and p.suffix not in (".yml", ".md"))
    if stray:
        problems.append(f"{manifests_dir} に .yml 以外のファイルがある: {stray}")
    for p in sorted(manifests_dir.glob("*.yml")):
        raw = load_yaml(p)
        problems += manifest_problems(raw, p.stem, adapters_dir=adapters_dir)
        if isinstance(raw, dict) and not problems:
            # PyYAML を使えない鮮度判定（check_v2_fresh）が読む最小パーサの結果が、PyYAML の結果と一致していること。
            adapter, inp = parse_manifest_inputs(p.read_text(encoding="utf-8"))
            want_input = next(iter(raw["input"].items())) if isinstance(raw.get("input"), dict) and raw["input"] else None
            if adapter != raw.get("adapter") or (inp is not None and inp != want_input) or (inp is None and want_input):
                problems.append(
                    f"{p.stem}: adapter/input を最小パーサ（migrate.common.parse_manifest_inputs）が正しく読めない"
                    f"（パーサ: {adapter!r}/{inp!r}、YAML: {raw.get('adapter')!r}/{want_input!r}）。単純な書き方にすること"
                )
    if problems:
        raise MigrationError(f"{manifests_dir} のマニフェストの形が不正:\n- " + "\n- ".join(problems))


def load_manifests(manifests_dir=DEFAULT_MANIFESTS_DIR, *, adapters_dir=None) -> dict[str, Manifest]:
    """`{source_id: Manifest}`。構造が不正なら止まる（`validate_manifests_shape`）。"""
    validate_manifests_shape(manifests_dir, adapters_dir=adapters_dir)
    out: dict[str, Manifest] = {}
    for p in sorted(pathlib.Path(manifests_dir).glob("*.yml")):
        raw = load_yaml(p)
        out[p.stem] = Manifest(
            source=raw["source"], region=raw["region"], target=raw["target"], update_mode=raw["update_mode"],
            input=dict(raw["input"]), adapter=raw["adapter"], evidence=str(raw["evidence"]).strip(),
            expected_row_count=raw.get("expected_row_count"),
            checks=tuple(raw.get("checks") or ()), edition=raw.get("edition"),
            expected=raw.get("expected"), expected_place_region_null_rows=raw.get("expected_place_region_null_rows", 0),
            expected_absent_excluded_rows=raw.get("expected_absent_excluded_rows", 0),
            sample_input_max_rows=raw.get("sample_input_max_rows"),
            path=str(p),
        )
    return out


def update_modes(manifests: dict[str, Manifest]) -> dict[str, str]:
    """registry ビルド（`scripts/registry/build_source.py`）へ流す `{source_id: update_mode}`。"""
    return {sid: m.update_mode for sid, m in manifests.items()}


@dataclass(frozen=True)
class ExpectedSums:
    """`expected` を持つ occurrence マニフェスト（非 builtin は必須、builtin は任意）の合計（b06/b07/b09 が yaml の宣言値に足して突合する）。"""
    period_shapes: dict = field(default_factory=dict)
    place: dict = field(default_factory=lambda: {k: 0 for k in EXPECTED_PLACE_KEYS})
    cube: dict = field(default_factory=lambda: {k: 0 for k in EXPECTED_CUBE_KEYS})
    sources: tuple = ()  # 宣言を持つ（非 builtin の occurrence）出典の source_id


def expected_sums(manifests: dict[str, Manifest]) -> ExpectedSums:
    shapes: dict[str, int] = {}
    place = {k: 0 for k in EXPECTED_PLACE_KEYS}
    cube = {k: 0 for k in EXPECTED_CUBE_KEYS}
    sources: list[str] = []
    for m in manifests.values():
        if m.target != "occurrence" or not m.expected:
            continue
        sources.append(m.source)
        for k, v in m.expected["period_shapes"].items():
            shapes[k] = shapes.get(k, 0) + v
        for k in EXPECTED_PLACE_KEYS:
            place[k] += m.expected["place"][k]
        for k in EXPECTED_CUBE_KEYS:
            cube[k] += m.expected["cube"][k]
    return ExpectedSums(shapes, place, cube, tuple(sorted(sources)))


# ---- 縮小サンプルの件数 overlay が manifest の `expected` に効く層 ----------------------------------------
# overlay のキーは `manifests:<source>.expected.<section>.<key>`（section は period_shapes / place / cube）。
# 対象は builtin × occurrence で `expected` を持つ出典（奄美の GBIF・iNat 等）だけ。
# scripts/migrate/*.yaml の宣言は `period.apply_count_overlay` が差し替えるが、manifest の expected は別の場所にあり、
# 差し替えないと原本の全件の値がサンプルの実測に足されてしまう。

EXPECTED_OVERLAY_PREFIX = "expected."


def split_expected_overlay(overlay: dict | None) -> tuple[dict, dict]:
    """`manifests` グループの overlay を (従来の件数キー, `<source>.expected.…` のキー) に分ける。"""
    plain: dict = {}
    exp: dict = {}
    for k, v in (overlay or {}).items():
        _, _, sub = k.partition(".")
        (exp if sub.startswith(EXPECTED_OVERLAY_PREFIX) else plain)[k] = v
    return plain, exp


def expected_overlay_keys(manifests: dict[str, "Manifest"]) -> set[str]:
    """overlay が指せる `<source>.expected.<section>.<key>` の集合（builtin × occurrence で expected を持つ出典）。"""
    keys: set[str] = set()
    for sid, m in manifests.items():
        if m.is_builtin and m.target == "occurrence" and m.expected:
            for section, sub in m.expected.items():
                keys.update(f"{sid}.expected.{section}.{k}" for k in sub)
    return keys


def apply_expected_overlay(manifests: dict[str, "Manifest"], overlay: dict | None) -> dict[str, "Manifest"]:
    """`manifests` の `expected` を overlay で差し替えたコピーを返す（overlay が None・空なら同じものを返す）。
    実在しない出典・section・key を指すと KeyError（黙って無視しない）。"""
    _, exp = split_expected_overlay(overlay)
    if not exp:
        return manifests
    out = dict(manifests)
    copied: set[str] = set()
    for flat_key, value in exp.items():
        if isinstance(value, bool) or not isinstance(value, int):
            raise TypeError(f"count overlay: {flat_key!r} の値は整数でなければならない（実際: {value!r}）")
        sid, _, rest = flat_key.partition(".")
        _, section, key = rest.split(".", 2)
        m = out.get(sid)
        if m is None or not (m.is_builtin and m.target == "occurrence" and m.expected) \
                or section not in m.expected or key not in m.expected[section]:
            raise KeyError(f"count overlay: manifests:{flat_key} が manifest の expected に無い")
        if sid not in copied:   # 元の manifests を書き換えない
            m = replace(m, expected=copy.deepcopy(m.expected))
            copied.add(sid)
        m.expected[section][key] = value
        out[sid] = m
    return out
