-- 流域カルテ アプリデータモデル (要求定義書 §6)
-- is_synthetic: 1=実データを土台に生成した合成レコード / 0=公開データ由来の実測
CREATE TABLE IF NOT EXISTS source_registry (
  source_id TEXT PRIMARY KEY, name TEXT, publisher TEXT, url TEXT,
  category TEXT, access_method TEXT, format TEXT, license TEXT,
  redistributable INTEGER, fetched_at TEXT, record_count INTEGER, notes TEXT
);
CREATE TABLE IF NOT EXISTS sites (
  site_id TEXT PRIMARY KEY, name TEXT, name_en TEXT,
  watershed TEXT, zone INTEGER,            -- Ridge to Reef 1-5
  lat REAL, lon REAL, elevation_m REAL, geohash TEXT,
  municipality TEXT, muni_code TEXT,
  treatment TEXT,                          -- 対策区 / 対照区 / 参照
  established_on TEXT, operator TEXT,
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS protocols (
  protocol_id TEXT PRIMARY KEY, name TEXT, version TEXT, domain TEXT,
  steps_json TEXT, source_id TEXT, url TEXT
);
CREATE TABLE IF NOT EXISTS instruments (
  instrument_id TEXT PRIMARY KEY, kind TEXT, model TEXT,
  calibrated_on TEXT, calibration_note TEXT, uncalibrated_flag INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS observers (
  observer_id TEXT PRIMARY KEY, display_name TEXT, role TEXT,  -- 初級/訓練済/専門
  org TEXT, is_synthetic INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS events (
  event_id TEXT PRIMARY KEY, site_id TEXT, event_date TEXT, event_time TEXT,
  protocol_id TEXT, protocol_version TEXT,
  weather TEXT, precip_24h_mm REAL, water_temp_c REAL,
  photo_count INTEGER, gps_offset_m REAL,
  is_backfilled INTEGER DEFAULT 0, is_rain_triggered INTEGER DEFAULT 0,
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS event_observers (
  event_id TEXT, observer_id TEXT, part TEXT   -- 測定者 / 立会者
);
CREATE TABLE IF NOT EXISTS measurements (
  measurement_id TEXT PRIMARY KEY, event_id TEXT, site_id TEXT,
  measured_on TEXT, variable TEXT, variable_en TEXT,
  value REAL, value_raw TEXT, unit TEXT, method TEXT,
  instrument_id TEXT, detection_flag TEXT,
  quality_stage TEXT DEFAULT '暫定',        -- 暫定/検証済/公開済
  verified_by TEXT, verified_on TEXT,
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_meas_site ON measurements(site_id, variable, measured_on);
CREATE TABLE IF NOT EXISTS organism_records (
  record_id TEXT PRIMARY KEY, event_id TEXT, site_id TEXT,
  observed_on TEXT, scientific_name TEXT, vernacular_name TEXT,
  taxon_rank TEXT, kingdom TEXT, phylum TEXT, class TEXT, "order" TEXT,
  family TEXT, genus TEXT, taxon_key TEXT,
  individual_count REAL, density REAL, density_unit TEXT,
  basis_of_record TEXT, identified_by TEXT, identification_basis TEXT,
  identification_confidence REAL,
  lat REAL, lon REAL, coordinate_uncertainty_m REAL,
  red_list_category TEXT, is_alien INTEGER DEFAULT 0,
  quality_stage TEXT DEFAULT '暫定', publication_scope TEXT DEFAULT '限定共有',
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0,
  -- レコード単位ライセンス（iNaturalist/GBIFはソースレベルのredistributableだけでは
  -- 再配布可否を判定できず、観察/データセット単位でライセンスが混在するため個別に保持する）
  record_license TEXT,      -- 元データの表記そのまま (例: 'cc-by-nc', 'http://creativecommons.org/licenses/by/4.0/legalcode', NULL, '')
  license_class TEXT,       -- 正規化: open / noncommercial / unknown / restricted
  commercial_ok INTEGER     -- 0/1 (原ライセンスが商用利用を許諾しているか)
);
CREATE INDEX IF NOT EXISTS ix_org_name ON organism_records(scientific_name);
CREATE INDEX IF NOT EXISTS ix_org_license_class ON organism_records(license_class);
CREATE TABLE IF NOT EXISTS interventions (
  intervention_id TEXT PRIMARY KEY, site_id TEXT, kind TEXT,
  parcel TEXT, quantity REAL, quantity_unit TEXT,
  started_on TEXT, finished_on TEXT, operator TEXT,
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS decisions (
  decision_id TEXT PRIMARY KEY, meeting_name TEXT, meeting_date TEXT,
  presented_data TEXT, decided TEXT, stalled_item_resolved INTEGER,
  participants TEXT, url TEXT,
  source_id TEXT, source_ref TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS quality_transitions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, target_table TEXT, target_id TEXT,
  from_stage TEXT, to_stage TEXT, actor TEXT, occurred_at TEXT, note TEXT
);
CREATE TABLE IF NOT EXISTS sensor_timeseries (
  id INTEGER PRIMARY KEY AUTOINCREMENT, site_id TEXT, datastream TEXT,
  phenomenon_time TEXT, result REAL, unit TEXT, instrument_id TEXT,
  source_id TEXT, is_synthetic INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_ts ON sensor_timeseries(site_id, datastream, phenomenon_time);
