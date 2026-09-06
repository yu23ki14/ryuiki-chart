-- 水道水の水源マップ（docs/WATER_SOURCE_MAP.md）の受け皿。
-- web/src/db/schema.ts の water_* テーブルと同じ形。あちらが D1 の正、こちらが ryuiki.sqlite 側。
-- 片方を直したらもう片方も直す（列がずれるとシードで落ちる）。
-- scripts/m06_water.py が起動時に流す。CREATE TABLE IF NOT EXISTS なので再実行しても安全。
--
-- 設計図のエンティティ名は D1 では一般的すぎるので water_ を前に付けてある。
--   utility→water_utility  facility→water_facility  zone→water_zone  source_doc→water_source_doc

-- 水道事業体。kind: bulk（用水供給＝卸）/ retail（末端給水）
CREATE TABLE IF NOT EXISTS water_utility (
  utility_id TEXT PRIMARY KEY,
  name TEXT,
  kind TEXT,
  note_ja TEXT
);

-- 水源。type: river / dam / groundwater / spring
-- parent_id は自己参照（ダム→河川、支流→本流、市の地下水→涵養域）。
-- river_name_ja は river_segments / nlni_w05_rivers の河川名への名寄せ。推測で埋めない。
CREATE TABLE IF NOT EXISTS water_source (
  source_id TEXT PRIMARY KEY,
  name TEXT,
  type TEXT,
  river_system TEXT,
  parent_id TEXT,
  river_name_ja TEXT,
  lat REAL, lon REAL,
  note_ja TEXT,
  source_doc_id TEXT
);

-- 取水堰・浄水場・配水池・分岐。type: intake / purification / reservoir / junction
CREATE TABLE IF NOT EXISTS water_facility (
  facility_id TEXT PRIMARY KEY,
  utility_id TEXT,
  name TEXT,
  type TEXT,
  lat REAL, lon REAL,
  note_ja TEXT,
  source_doc_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_wfac_utility ON water_facility(utility_id);

-- 根拠資料。これが無い行はビルドで落とす（設計図 §6-1）。
-- PDF の実体は data/raw/water/（Git 管理外）。url + sha256 で再取得できるようにする。
CREATE TABLE IF NOT EXISTS water_source_doc (
  doc_id TEXT PRIMARY KEY,
  title TEXT,
  publisher TEXT,
  url TEXT,
  published_at TEXT,
  retrieved_at TEXT,
  local_path TEXT,
  sha256 TEXT,
  license_ja TEXT
);

-- 流れの辺。「to_id に入る水のうち何割が from_id 由来か」。
-- basis: measured（年報の実測）/ estimated（推計）/ nominal（施設能力比。UI で「概算」）
CREATE TABLE IF NOT EXISTS water_flow_edge (
  edge_id TEXT PRIMARY KEY,
  from_id TEXT,
  to_id TEXT,
  share REAL,
  basis TEXT,
  valid_from TEXT,
  valid_to TEXT,
  source_doc_id TEXT,
  note_ja TEXT
);
CREATE INDEX IF NOT EXISTS ix_wedge_to ON water_flow_edge(to_id, valid_from);

-- 町丁目（e-Stat 2020年国勢調査 小地域）。c90_estat_shozaiki.py の出力から入れる。
-- ポリゴンはここに持たない（静的アセット /geo/water_zones.geojson 側）。
CREATE TABLE IF NOT EXISTS water_zone (
  key_code TEXT PRIMARY KEY,
  muni_code TEXT,
  city_name TEXT,
  s_name TEXT,
  name TEXT,
  parts INTEGER,
  population INTEGER,
  households INTEGER,
  area_km2 REAL,
  centroid_lat REAL,
  centroid_lon REAL
);
CREATE INDEX IF NOT EXISTS ix_wzone_city ON water_zone(city_name);

-- 町丁目 → 給水元の施設。混在する町丁目のみ share < 1.0。ポリゴンは分割しない。
-- confidence: high / medium / low。推測で high を付けない。
CREATE TABLE IF NOT EXISTS water_zone_assignment (
  assignment_id TEXT PRIMARY KEY,
  key_code TEXT,
  facility_id TEXT,
  share REAL,
  confidence TEXT,
  valid_from TEXT,
  valid_to TEXT,
  source_doc_id TEXT,
  note_ja TEXT
);
CREATE INDEX IF NOT EXISTS ix_wza_key ON water_zone_assignment(key_code);
CREATE INDEX IF NOT EXISTS ix_wza_fac ON water_zone_assignment(facility_id);

-- 派生。m06_water.py が再帰合成で生成する。手で書かない。
CREATE TABLE IF NOT EXISTS water_zone_source_share (
  key_code TEXT,
  source_id TEXT,
  share REAL,
  confidence TEXT,
  basis TEXT,
  as_of TEXT
);
CREATE INDEX IF NOT EXISTS ix_wzss_key ON water_zone_source_share(key_code);
CREATE INDEX IF NOT EXISTS ix_wzss_src ON water_zone_source_share(source_id);
