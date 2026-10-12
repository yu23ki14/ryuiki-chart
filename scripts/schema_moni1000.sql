-- モニタリングサイト1000（モニ1000）神奈川県 5 出典の生の記録（scripts/m10_moni1000.py が作る）。
-- 設計: docs/plans/MONI1000.md §2.1。5 出典とも「調査 × 地点 × 種 × 個体数」の同じ形なので 1 表に統合する。
-- 出典固有の列は extra_json。生の行は 1 行も落とさない（occurrence に流さない行は in_occurrence=0 と exclude_reason）。
CREATE TABLE IF NOT EXISTS moni1000_counts (
  record_id TEXT PRIMARY KEY,        -- satochi 3 出典: '{source_id}:{data_id}'。他: '{source_id}:r{6桁連番}'（CSV の行順）
  source_id TEXT NOT NULL, source_ref TEXT,
  survey_id TEXT,                    -- 調査 ID（satochi 3 出典。他は NULL）
  site_key TEXT NOT NULL,            -- 出典の地点キー（S060 / 100246 / 130700）
  site_name_ja TEXT,
  place_id TEXT,                     -- registry の place（registry/source/moni1000_site_map.csv で結ぶ。無ければ NULL）
  lat REAL, lon REAL,                -- 出典の値のまま（丸め・補完・ぼかしをしない）
  lat_lon_basis TEXT,                -- 'row'（行に在る）/ 'site_table'（sites CSV）/ NULL
  coord_decimals INTEGER,            -- 小数桁数（精度の根拠）
  observed_on TEXT,                  -- 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY'（欠けた分は補わない）か NULL
  survey_year INTEGER, survey_month INTEGER, survey_day INTEGER,
  start_time TEXT, end_time TEXT,    -- 'HH:MM'（forest/shorebird）。mammal の photo_time は start_time に
  season_ja TEXT,                    -- season_ja / survey_period_ja を出典ごとに
  survey_round TEXT,                 -- rep_no（調査回）
  section_ja TEXT,                   -- section_name_ja / point_ja（ライン区間・ポイント）
  species_ja TEXT, scientific_name TEXT,
  individual_count REAL,             -- 数値化できたときだけ。0 も 0 のまま
  individual_count_raw TEXT,         -- 原文（'－'・'-' を含む。空は NULL）
  count_qualifier TEXT,              -- plusminus（'+'/'±'）
  id_note_ja TEXT,                   -- id_confidence_ja（'sp.'/'?'）/ id_type_ja
  out_of_range INTEGER, out_of_time INTEGER,   -- 0/1（範囲外・時間外。元の列が空なら 0）
  taxon_id TEXT,                     -- 名寄せ表（registry/taxon/moni1000_name_map.csv）の結果。無ければ NULL
  taxon_resolution TEXT,             -- 'map_sci'/'map_ja'/'unresolved'/'non_taxon'
  in_occurrence INTEGER NOT NULL,    -- 1=occurrence に流す、0=流さない
  exclude_reason TEXT,               -- in_occurrence=0 の理由: zero_count / unresolved_taxon / non_wild / non_species
  extra_json TEXT                    -- 出典固有の残りの列
);
CREATE INDEX IF NOT EXISTS ix_moni_src ON moni1000_counts(source_id, survey_year);
CREATE INDEX IF NOT EXISTS ix_moni_sp ON moni1000_counts(species_ja);
