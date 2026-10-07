-- 神奈川県 環境DNA（eDNA）調査結果の原本表。docs/plans/KANAGAWA_EDNA.md §2.2。
-- scripts/m07_kanagawa_edna.py が起動時に流して wipe+reload する（CREATE ... IF NOT EXISTS）。
-- ryuiki.sqlite の原本表であって、D1 の drizzle スキーマ（web/src/db/schema.ts）には載せない
-- （D1 に eDNA 専用表は作らない。occurrence は b06 が edna_detections から作る）。

-- 地点（= ファイル × 調査地点列）。座標は台帳（data/edna/kanagawa_edna_site_coords.csv）の写し。
-- 公開データに座標は無い。lat/lon は「推定位置」で、根拠区分 coord_source と精度つき。判別不能は NULL。
CREATE TABLE IF NOT EXISTS edna_sites (
  site_key TEXT PRIMARY KEY,            -- '<ファイル名の stem>:<地点IDを trim したもの>'（正規化しない）
  dataset_file TEXT NOT NULL,
  program TEXT NOT NULL CHECK (program IN ('kenmin','project')),
  assay TEXT NOT NULL CHECK (assay IN ('fish_12S','insects_16S','insects_amphibians','all_taxa')),
  fiscal_year INTEGER NOT NULL,
  site_id_raw TEXT NOT NULL,
  water_system_raw TEXT, water_system_ja TEXT,
  tributary_raw TEXT,    tributary_ja TEXT,
  municipality_raw TEXT, municipality_ja TEXT,   -- 複数は「・」区切りのまま
  collected_on TEXT,                    -- YYYY-MM-DD。空欄・解釈不能は NULL（落とさない・補わない）
  collected_on_raw TEXT,                -- Excel シリアル値 or 'YYYYMMDD' の原表記
  lat REAL, lon REAL,                   -- 推定位置（台帳から）。公開データの座標ではない
  coord_source TEXT NOT NULL CHECK (coord_source IN ('map_image','estimated_from_name','none')),
  coordinate_uncertainty_m REAL,        -- coord_source<>'none' のとき必須
  coord_method TEXT, coord_note TEXT,
  source_id TEXT NOT NULL, source_ref TEXT NOT NULL,   -- source_ref = '<URL>#<file>!<列>'
  CHECK ((lat IS NULL) = (lon IS NULL)),
  CHECK (coord_source = 'none' OR (lat IS NOT NULL AND coordinate_uncertainty_m IS NOT NULL)),
  CHECK (coord_source <> 'none' OR (lat IS NULL AND coordinate_uncertainty_m IS NULL))
);

-- 検出も不検出も（約 13.4 万行）。値はリード数であって個体数ではない。
CREATE TABLE IF NOT EXISTS edna_reads (
  read_id TEXT PRIMARY KEY,             -- '<site_key>:<xlsx の行番号>'（スナップショット内で安定）
  site_key TEXT NOT NULL REFERENCES edna_sites(site_key),
  class_ja TEXT, order_ja TEXT, family_ja TEXT, genus_ja TEXT,     -- 綱・目・科・属（原文。'-' は NULL）
  name_raw TEXT,                        -- 「参考種名（機械的な併記処理）」または「種名」
  name_adopted TEXT,                    -- 「種名（手動精査結果）」/「種和名」（採用名。fish は種名）
  name_sci_raw TEXT,                    -- r7 の「学名」。他は NULL
  name_note TEXT,                       -- 「（注）」「（和名なし）」「（cf.）」等の括弧書きを原文のまま
  reads INTEGER NOT NULL CHECK (reads >= 0),
  is_detected INTEGER NOT NULL CHECK (is_detected IN (0,1)),   -- reads > 0
  pident_qcov REAL,                     -- 'MAX(pident*qcovs)'（0〜1）。fish は NULL
  reliability TEXT,                     -- '高'/'中'/'低'。列の無いファイルは NULL
  national_rl_raw TEXT, pref_rl_raw TEXT, alien_raw TEXT, -- 各ファイルの RL・特定外来種の列（原表記）
  name_key TEXT NOT NULL,               -- 名前の正規化キー。taxon の解決はこれで引く
  taxon_id TEXT,                        -- m07 が name_map から焼く。NULL なら止める
  source_id TEXT NOT NULL,
  CHECK (is_detected = (reads > 0))
);
CREATE INDEX IF NOT EXISTS ix_edna_reads_site ON edna_reads(site_key, is_detected);

-- adapter（manifests/kanagawa_edna.yml）の入力。edna_reads の is_detected=1 に地点の列を結合した投影。
-- m07 が同じトランザクションで作る。adapter は 1 入力表しか読めないので、結合はここで済ませる。
CREATE TABLE IF NOT EXISTS edna_detections (
  record_key TEXT PRIMARY KEY,          -- = read_id
  taxon_id TEXT NOT NULL, scientific_name TEXT, vernacular_name TEXT, taxon_rank TEXT, red_list_category TEXT,
  observed_on TEXT,                     -- = collected_on
  lat REAL, lon REAL, coordinate_uncertainty_m REAL,
  attributes_json TEXT NOT NULL         -- 設計 §3.3 の attributes。m07 が組む
);
