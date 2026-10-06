"""observation / occurrence の公開 ID の発行規則（ADR-0004、Issue #39 Phase C 担当 C）。

**ID は行の位置ではなく出典の業務キーで決める**（原本の rowid・CSV 行番号に依存しない）。
同じ原本 -> 同じ ID（決定的）、同じ出典の再取得でキーが同じなら同じ ID、
キーが消えた行の ID は再利用しない（墓標表は作らず、検査で固定する）。
スコープは常に `common`（ADR-0004 規約0 の追記。地域は `region_id` 列で絞る）。

    observation_id = common:obs:<tbl>.<key>
      measurements       tbl=meas    key = reversible_key(measurement_id)                      例 common:obs:meas.atsugi_river_water_quality__000000
      sensor_timeseries  tbl=sensor  `sensor.<source_id>.<sha256 先頭16桁>`（業務キー (site_id, datastream, phenomenon_time, source_id)
                                     が全行で一意であることは実測済み。長いのでハッシュにする。衝突は UNIQUE 索引で止まる）
      landuse            tbl=landuse key = <watershed_id>.<data_year>.<code>.<area_km2|n_cells>（各部を reversible_key。CSV 行番号は使わない）
    occurrence_id  = common:occ:<ns>.<key>   ns は gbif / inat（`taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE`）、
                                     key = 出典の key（`record_id` = `<source_id>__<key>` の `<key>`）
                                     例 common:occ:gbif.1830141077（source が gbif_kanagawa から
                                     gbif_kanagawa_occurrences に移っても同じ）
"""
import hashlib
import re
import urllib.parse

from registry import common as registry_common
from taxon_namespaces import TAXON_KEY_SOURCE_NAMESPACE

from . import common

_KEY_SAFE = re.compile(r"[A-Za-z0-9_.\-]")


def reversible_key(raw: str) -> str:
    """公開 ID の key 用の**可逆な**エンコード（`urllib.parse.unquote` で元に戻る）。
    `[A-Za-z0-9_.-]` 以外（空白・`:`・`/`・非 ASCII・`%`）は UTF-8 の percent-encode にし、`_` `.` の連続を畳まない
    （`registry.common.slugify_local_key` は連続する `_` を畳むので、`a__b` と `a_b` が同じ key に潰れる。
    place ID はそちらを使い続ける〔既存 ID を変えない〕が、観測・出現の ID は可逆にして衝突を原理的に避ける）。"""
    if not raw:
        raise common.MigrationError("公開 ID の key が空")
    return "".join(ch if _KEY_SAFE.match(ch) else "".join(f"%{b:02X}" for b in ch.encode("utf-8")) for ch in raw)


OBS_ENTITY = "obs"
OCC_ENTITY = "occ"


def measurement_observation_id(measurement_id: str) -> str:
    return registry_common.scoped_id(OBS_ENTITY, f"meas.{reversible_key(measurement_id)}")


def sensor_observation_id(site_id: str, datastream: str, phenomenon_time: str, source_id: str | None) -> str:
    if not source_id:
        raise common.MigrationError(
            f"sensor_timeseries の source_id が空の行は observation_id を発行できない（site_id={site_id!r}）"
        )
    if not registry_common.SOURCE_ID_RE.match(source_id):
        raise common.MigrationError(f"source_id が [a-z0-9_]+ ではない: {source_id!r}")
    raw = "\x1f".join((site_id, datastream, phenomenon_time, source_id))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return registry_common.scoped_id(OBS_ENTITY, f"sensor.{source_id}.{digest}")


def landuse_observation_id(watershed_id: str, data_year: str, code: str, suffix: str) -> str:
    key = ".".join(reversible_key(p) for p in (watershed_id, data_year, code, suffix))
    return registry_common.scoped_id(OBS_ENTITY, f"landuse.{key}")


def occurrence_id(record_id: str, source_id: str) -> str:
    """`record_id`（`<source_id>__<key>`）から公開 ID を作る。接頭辞が合わない・未知の出典は止まる。"""
    ns = TAXON_KEY_SOURCE_NAMESPACE.get(source_id)
    if ns is None:
        raise common.MigrationError(f"occurrence_id の名前空間が未定義の source_id: {source_id!r}")
    prefix = f"{source_id}__"
    if not record_id.startswith(prefix) or len(record_id) == len(prefix):
        raise common.MigrationError(f"record_id が <source_id>__<key> の形ではない: {record_id!r}（source_id={source_id!r}）")
    key = reversible_key(record_id[len(prefix):])
    return registry_common.scoped_id(OCC_ENTITY, f"{ns}.{key}")


def adapter_occurrence_id(source_id: str, record_key: str) -> str:
    """adapter（`scripts/adapters/`）経由の出現の公開 ID: `common:occ:<source_id>.<key>`（key は可逆エンコード）。

    gbif/inat は `TAXON_KEY_SOURCE_NAMESPACE` の名前空間（`gbif.`/`inat.`）を使う従来の `occurrence_id()` のまま
    （既存 ID は変えない）。名前空間を持たない新しい出典は、source_id 自身を名前空間にする
    （`TAXON_KEY_SOURCE_NAMESPACE` への追記を要求しない＝ソース追加でライブラリ側を触らない）。
    """
    if TAXON_KEY_SOURCE_NAMESPACE.get(source_id) is not None:
        raise common.MigrationError(f"{source_id!r} は組み込みの出典。occurrence_id() を使うこと")
    return registry_common.scoped_id(OCC_ENTITY, f"{source_id}.{reversible_key(record_key)}")
