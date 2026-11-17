-- OpenStreetMap の河川線とダム・堰（scripts/c105_osm_waterways.py が Overpass から取り、scripts/m12_osm_waterways.py が入れる）。
-- 河川線は way（名前つきの waterway=river/stream）。座標は Overpass の生の geometry のまま（丸め・間引きをしない）。
CREATE TABLE IF NOT EXISTS osm_waterways (
  way_id INTEGER PRIMARY KEY,        -- OSM の way id
  name_ja TEXT,                      -- OSM の name（日本語。英語名しか無いものはそのまま）
  waterway TEXT NOT NULL,            -- 'river' / 'stream'
  relation_id INTEGER,               -- それを含む waterway リレーション（同じ川としてのまとまり）。無ければ NULL。複数なら最小の id
  region_id TEXT,                    -- 'jp-14' / 'jp-46'。始点が region の bbox 内ならその region、外なら取得した範囲の region
  length_m REAL,                     -- 球面近似（haversine の総和）
  geometry_geojson TEXT,             -- LineString
  start_lat REAL, start_lon REAL, end_lat REAL, end_lon REAL,
  source_id TEXT NOT NULL, source_ref TEXT   -- 'osm:way/<id>'
);
CREATE INDEX IF NOT EXISTS ix_osmw_region ON osm_waterways(region_id, waterway);
CREATE INDEX IF NOT EXISTS ix_osmw_rel ON osm_waterways(relation_id);

CREATE TABLE IF NOT EXISTS osm_water_structures (
  osm_type TEXT NOT NULL,            -- 'node' / 'way' / 'relation'
  osm_id INTEGER NOT NULL,
  kind TEXT NOT NULL,                -- 'dam' / 'weir'
  name_ja TEXT,
  region_id TEXT,
  lat REAL, lon REAL,                -- node はその座標、way/relation は Overpass の center
  source_id TEXT NOT NULL, source_ref TEXT,  -- 'osm:node/<id>' 等
  PRIMARY KEY (osm_type, osm_id)
);
CREATE INDEX IF NOT EXISTS ix_osmws_region ON osm_water_structures(region_id, kind);
CREATE UNIQUE INDEX IF NOT EXISTS ux_osmws_ref ON osm_water_structures(source_ref);  -- get_records のページング・id 指定の鍵
