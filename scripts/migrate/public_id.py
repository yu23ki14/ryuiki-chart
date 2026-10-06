"""observation / occurrence の公開 ID の発行規則（ADR-0004、Issue #39 Phase C 担当 C）。

**ID は行の位置ではなく出典の業務キーで決める**（原本の rowid・CSV 行番号に依存しない）。
同じ原本 -> 同じ ID（決定的）、同じ出典の再取得でキーが同じなら同じ ID、
キーが消えた行の ID は再利用しない（墓標表は作らず、検査で固定する）。
スコープは常に `common`（ADR-0004 規約0 の追記。地域は `region_id` 列で絞る）。

    observation_id = common:obs:<tbl>.<key>
      measurements       tbl=meas    key = slug(measurement_id)                         例 common:obs:meas.atsugi_river_water_quality__000000
      sensor_timeseries  tbl=sensor  `sensor.<source_id>.<sha256 先頭16桁>`（業務キー (site_id, datastream, phenomenon_time, source_id)
                                     が全行で一意であることは実測済み。長いのでハッシュにする。衝突は UNIQUE 索引で止まる）
      landuse            tbl=landuse key = slug(<watershed_id>.<data_year>.<code>.<area_km2|n_cells>)（CSV 行番号は使わない）
    occurrence_id  = common:occ:<ns>.<key>   ns は gbif / inat（`taxon_namespaces.TAXON_KEY_SOURCE_NAMESPACE`）、
                                     key = 出典の key（`record_id` = `<source_id>__<key>` の `<key>`）
                                     例 common:occ:gbif.1830141077（source が gbif_kanagawa から
                                     gbif_kanagawa_occurrences に移っても同じ）
"""
import hashlib

from registry import common as registry_common
from taxon_namespaces import TAXON_KEY_SOURCE_NAMESPACE

from . import common

OBS_ENTITY = "obs"
OCC_ENTITY = "occ"


def measurement_observation_id(measurement_id: str) -> str:
    return registry_common.scoped_id(OBS_ENTITY, f"meas.{registry_common.slugify_local_key(measurement_id)}")


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
    key = registry_common.slugify_local_key(f"{watershed_id}.{data_year}.{code}.{suffix}")
    return registry_common.scoped_id(OBS_ENTITY, f"landuse.{key}")


def occurrence_id(record_id: str, source_id: str) -> str:
    """`record_id`（`<source_id>__<key>`）から公開 ID を作る。接頭辞が合わない・未知の出典は止まる。"""
    ns = TAXON_KEY_SOURCE_NAMESPACE.get(source_id)
    if ns is None:
        raise common.MigrationError(f"occurrence_id の名前空間が未定義の source_id: {source_id!r}")
    prefix = f"{source_id}__"
    if not record_id.startswith(prefix) or len(record_id) == len(prefix):
        raise common.MigrationError(f"record_id が <source_id>__<key> の形ではない: {record_id!r}（source_id={source_id!r}）")
    key = registry_common.slugify_local_key(record_id[len(prefix):])
    return registry_common.scoped_id(OCC_ENTITY, f"{ns}.{key}")
