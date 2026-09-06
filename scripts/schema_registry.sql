-- 語彙レジストリ(docs/plans/PHASE_A.md §A-1, docs/adr/0004/0006/0010/0013/0019)の DDL。
-- web/src/db/schema.ts の drizzle 定義から生成した
-- web/drizzle/migrations/0003_worthless_longshot.sql と列・索引を一致させてある。
-- スキーマを変えるときは両方を更新すること(正は drizzle 側。ここは追随する)。
--
-- scripts/r01_build_registry.py が起動時にこれを流して data/db/registry.sqlite を作る。
-- CREATE TABLE IF NOT EXISTS なので再実行しても安全。中身(行)は scripts/registry/build_*.py
-- が入れる(このファイルは器だけ)。

-- 単位。symbol は人間向けの原表記、ucum は UCUM 準拠のコード。
CREATE TABLE IF NOT EXISTS unit (
  unit_id TEXT PRIMARY KEY,
  symbol TEXT,
  ucum TEXT,
  name_ja TEXT,
  quantity_kind TEXT
);

-- 正準の指標。measurements.variable / sensor_timeseries.datastream の出典別名は
-- variable_alias 側に持ち、ここには名前から単位・粒度・統計量を剥がした後の
-- 正準形だけを置く(ADR-0010)。
CREATE TABLE IF NOT EXISTS variable (
  variable_id TEXT PRIMARY KEY,
  code TEXT,
  name_ja TEXT,
  name_en TEXT,
  theme TEXT,
  unit_id TEXT,
  value_type TEXT,
  default_stat TEXT,
  higher_is_worse INTEGER,
  description_ja TEXT,
  status TEXT
);

-- 出典表記 -> 正準 variable の対応。alias が v1 の measurements.variable /
-- sensor_timeseries.datastream の生の文字列。alias は出典をまたいで再利用され
-- うるため一意にならず、PK は別に自動採番の id を持つ。
CREATE TABLE IF NOT EXISTS variable_alias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alias TEXT NOT NULL,
  source_scope TEXT,
  variable_id TEXT,
  unit_id TEXT,
  stat TEXT,
  grain TEXT,
  note TEXT
);
CREATE INDEX IF NOT EXISTS ix_variable_alias_alias ON variable_alias(alias);
CREATE INDEX IF NOT EXISTS ix_variable_alias_variable ON variable_alias(variable_id);

-- 空間単位(ADR-0006)。Phase A で登録するのは集計軸として実在するものだけ
-- (site / watershed / mesh3 / zone)。place_relation と geometry_ref は
-- Phase A では持たない(点→place の解決も含め Phase B)。
CREATE TABLE IF NOT EXISTS place (
  place_id TEXT PRIMARY KEY,
  region_id TEXT,
  place_kind TEXT,
  name_ja TEXT,
  lat REAL,
  lon REAL,
  elevation_m REAL,
  area_km2 REAL,
  definition_ref TEXT,
  status TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_kind ON place(place_kind);

-- v1 の出典側識別子(sites.site_id / watershed_meta.watershed_id / mlat,mlon 等)から
-- place への対応。「v1 を動かさずに並走させる」ための接続点(PHASE_A.md §A-3)。
-- external_key からの逆引きが主な引き方。
CREATE TABLE IF NOT EXISTS place_source_ref (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  place_id TEXT,
  external_key TEXT,
  source_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_external ON place_source_ref(external_key);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_place ON place_source_ref(place_id);

-- 分類群レジストリ(ADR-0019)。GBIF 由来は taxon_id = common:taxon:gbif.<key>、
-- taxa(v1)由来で GBIF 未照合のものは common:taxon:ryuiki-taxa.<taxa の主キー>。
-- accepted_taxon_id は status='synonym' のときに正の taxon を指す
-- (ADR-0004 規約2: ID は不変、実体が変わったら新 ID を作り旧 ID は残す)。
CREATE TABLE IF NOT EXISTS taxon (
  taxon_id TEXT PRIMARY KEY,
  scientific_name TEXT,
  rank TEXT,
  gbif_taxon_key TEXT,
  vernacular_name_ja TEXT,
  status TEXT,
  accepted_taxon_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_taxon_gbif_key ON taxon(gbif_taxon_key);

-- 注意事項(ADR-0013)。caveat_id は web/src/lib/ai/caveats.ts が今返しているキー文字列を
-- そのまま使う(common:caveat:<key>)。cells.notes 由来は common:caveat:cells.<note の主キー>。
-- 引き方は scope_kind + scope_ref の組。
CREATE TABLE IF NOT EXISTS caveat (
  caveat_id TEXT PRIMARY KEY,
  scope_kind TEXT,
  scope_ref TEXT,
  severity TEXT,
  kind TEXT,
  title_ja TEXT,
  body_ja TEXT,
  quote TEXT
);
CREATE INDEX IF NOT EXISTS ix_caveat_scope ON caveat(scope_kind, scope_ref);
