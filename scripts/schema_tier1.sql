-- Tier 1 ソース(docs/UNDATAFIED_TIERS.md)の受け皿。
-- 既存のアプリモデル(schema_app.sql)に収まらない「台帳・区域・メッシュ」型のデータだけを足す。
-- 水質・大気・沈下量のような測定値は既存の measurements / sensor_timeseries に入れるので
-- ここには新設しない。
-- scripts/m05_tier1.py が起動時に流す。CREATE TABLE IF NOT EXISTS なので再実行しても安全。

-- 保護区・緑地・保存樹木の指定台帳。
-- 自然公園 / 特別緑地保全地区 / 近郊緑地保全区域 / 歴史的風土保存地区 / 風致地区 /
-- 都市公園 / 保存樹木 を category_code で束ねている。面積を持たない点データ(保存樹木)も同居する。
CREATE TABLE IF NOT EXISTS protected_areas (
  area_id TEXT PRIMARY KEY,
  name_ja TEXT,
  category_ja TEXT,               -- 原文の区分名
  category_code TEXT,             -- 我々が付けた英字スラグ
  municipality_ja TEXT,
  area_ha REAL, area_ha_raw TEXT,
  designated_on TEXT, designated_on_raw TEXT,
  lat REAL, lon REAL,
  watershed TEXT,                 -- m05 が点内判定で埋める(座標があるもののみ)
  zone INTEGER,                   -- 未使用。Ridge to Reef ゾーンは標高と海岸線距離が要る
                                  -- (m01_sites.py 参照)。区域データには標高が無いので埋めていない
  note_ja TEXT,
  source_id TEXT, source_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_pa_cat ON protected_areas(category_code, municipality_ja);

-- 現存植生図2024(環境省 いきもの地図 ArcGIS REST)の神奈川県相当範囲。
-- geometry_geojson は表示用に simplify 済み。面積は緯度経度からの近似(厳密な測地面積ではない)。
CREATE TABLE IF NOT EXISTS vegetation_polygons (
  feature_id TEXT PRIMARY KEY,
  legend_code TEXT, legend_name_ja TEXT,
  veg_division_ja TEXT,
  naturalness REAL, naturalness_class_ja TEXT,
  survey_year INTEGER, block_ja TEXT,
  area_m2 REAL,                   -- 近似値
  centroid_lat REAL, centroid_lon REAL,
  watershed TEXT,
  geometry_geojson TEXT,          -- simplify 済み
  source_id TEXT, source_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_veg_legend ON vegetation_polygons(legend_code);

-- 中大型哺乳類の3次メッシュ分布(タヌキ/キツネ/アナグマ)。
-- 元データは年別の確認フラグが横に並ぶワイド形式。1メッシュ×1調査年次=1行に展開してある。
-- survey_label に元の列名を必ず残す(第6回=dai6kai のように年を持たない列があるため)。
CREATE TABLE IF NOT EXISTS mammal_mesh (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  mesh_code TEXT, species TEXT, species_ja TEXT,
  survey_label TEXT,              -- 元の列名
  survey_year INTEGER,            -- 西暦。年を持たない調査は NULL
  confirmed INTEGER,              -- 0/1
  lat REAL, lon REAL,             -- メッシュ中心
  source_id TEXT, source_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_mammal ON mammal_mesh(species, survey_year, mesh_code);

-- 大型獣の出没・目撃記録(ツキノワグマ)。
-- 個体群管理の記録であって分類学的な観察記録ではないため organism_records とは分けている
-- (頭数・状況(目撃/痕跡/捕殺)・区分(人里/山中)は Darwin Core に対応する列が無い)。
-- 場所は地名テキストのみで座標は原本に無い。推測で埋めていないので lat/lon は NULL。
CREATE TABLE IF NOT EXISTS wildlife_sightings (
  sighting_id TEXT PRIMARY KEY,
  species_ja TEXT,
  fiscal_year INTEGER,
  observed_on TEXT,               -- 年度から西暦を決めて正規化。1-3月は翌年
  observed_on_raw TEXT, observed_time_raw TEXT,
  individual_count REAL, individual_count_raw TEXT,
  situation_ja TEXT,              -- 目撃/痕跡/捕殺 等(原文のまま)
  locality_ja TEXT,
  area_kind_ja TEXT,              -- 人里/山中 等(原文のまま)
  municipality_ja TEXT, lat REAL, lon REAL,
  is_preliminary INTEGER DEFAULT 0,  -- 速報値なら 1
  note_ja TEXT,
  source_id TEXT, source_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_ws ON wildlife_sightings(species_ja, fiscal_year);

-- 河川流路。既存の nlni_w05_rivers は県コード単位なので神奈川県内で切れているが、
-- こちらは水系コード830307単位なので相模川の水源である山梨県側の桂川上流部を含む。
CREATE TABLE IF NOT EXISTS river_segments (
  feature_id TEXT PRIMARY KEY,
  name_ja TEXT, section_type TEXT, prefecture_ja TEXT,
  length_m REAL,                  -- 近似値
  start_lat REAL, start_lon REAL, end_lat REAL, end_lon REAL,
  geometry_geojson TEXT,
  source_id TEXT, source_ref TEXT
);
CREATE INDEX IF NOT EXISTS ix_river_pref ON river_segments(prefecture_ja);
