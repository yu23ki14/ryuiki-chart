-- 語彙レジストリ(docs/plans/PHASE_A.md §A-1, docs/adr/0004/0006/0010/0013/0019)の DDL。
-- web/src/db/schema-registry.ts の drizzle 定義から生成した web/drizzle/migrations/ 配下の
-- マイグレーションと列・索引を一致させてある。
-- スキーマを変えるときは両方を更新すること(正は drizzle 側。ここは追随する)。
-- 例外: place_relation・place_watershed(いずれも下記)はまだ web/src/db/schema-registry.ts
-- に無い。D1 に載せる消費者がまだ無いため意図的に見送っている(ADR-0022, ADR-0006)。
--
-- scripts/r01_build_registry.py が起動時にこれを流して data/db/registry.sqlite を作る。
-- CREATE TABLE IF NOT EXISTS なので再実行しても安全。中身(行)は scripts/registry/build_*.py
-- が入れる(このファイルは器だけ)。

-- region（ADR-0002）ごとの時刻帯の語彙（Issue #32-3、ADR-0024）。手書きの正は registry/region.yaml。
-- region_id は place.region_id・observation.region_id と同じ値（jp-14 等）。
CREATE TABLE IF NOT EXISTS region (
  region_id TEXT PRIMARY KEY,
  name_ja TEXT NOT NULL,
  tz_name TEXT NOT NULL,
  utc_offset TEXT NOT NULL,
  evidence TEXT
);

-- 単位。symbol は人間向けの原表記、ucum は UCUM 準拠のコード。
CREATE TABLE IF NOT EXISTS unit (
  unit_id TEXT PRIMARY KEY,
  symbol TEXT,
  ucum TEXT,
  name_ja TEXT,
  quantity_kind TEXT,
  -- 正準単位への換算（ADR-0023、Issue #31）。値_正準 = 値_出典 × scale_to_canonical。線形のみ
  -- （オフセット換算は扱わない）。換算しない単位は自分自身を指し scale=1。
  canonical_unit_id TEXT NOT NULL,
  scale_to_canonical REAL NOT NULL
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
-- sensor_timeseries.datastream の生の文字列。エイリアスは「出典 × 表記」で解決する
-- (docs/adr/0010-variable-registry.md 決定1)。dataset は alias がどの v1 テーブルの
-- 表記かを表し (measurements / sensor_timeseries)、source_id は v1
-- source_registry.source_id (空 = 出典未記録。is_synthetic=1 の行)。
-- 同じ (dataset, alias) でも source_id が違えば grain/stat が異なりうるため、
-- PK は別に自動採番の id を持つ。source_id は bare のまま変えない（cube・D1 も bare）。
-- 出典が版を持つときだけ edition_key / source_edition_id（Issue #39 Phase C。土地利用の
-- `@<年>` を置き換えた。dataset は論理名のまま）。
-- grain/stat は一次資料調査 (docs/plans/PHASE_B_ALIAS_STAT_SOURCES.md) 済みで、
-- (dataset, alias, source_id) の組ごとに固定 1 値に決まる (atsugi_river_water_quality
-- の「日付書式の混在」も統計量としては全期間 mean/day で確定するため、行ごとに決まる
-- 宣言的な列は不要と判断した)。
CREATE TABLE IF NOT EXISTS variable_alias (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  alias TEXT NOT NULL,
  dataset TEXT,
  source_id TEXT,
  variable_id TEXT,
  unit_id TEXT,
  stat TEXT,
  grain TEXT,
  -- unit_id の根拠: 'source'=原本が同じ単位を報告している / 'registry'=原本に単位の記載が無く
  -- レジストリが補った（Issue #31）。unit_id が空の行は空。
  unit_basis TEXT,
  note TEXT,
  -- 版（Issue #39 Phase C、ADR-0005）。NULL = 全 edition 共通。値があるとき (source_id, edition_key)
  -- が source_edition に実在することをビルドが検査し、source_edition_id に展開して持つ
  -- （common:edition:<source_id>.<edition_key>）。土地利用 46 行（2006:22・2016:24）だけが値を持つ。
  edition_key TEXT,
  source_edition_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_variable_alias_alias ON variable_alias(alias);
CREATE INDEX IF NOT EXISTS ix_variable_alias_variable ON variable_alias(variable_id);
CREATE INDEX IF NOT EXISTS ix_variable_alias_dataset_alias_source ON variable_alias(dataset, alias, source_id);

-- 出典のライセンス（ADR-0005、Issue #39 Phase C）。手書きの正は registry/source/license.yaml。
-- license_class のコードリストもそこ。
CREATE TABLE IF NOT EXISTS license (
  license_id TEXT PRIMARY KEY,
  name_ja TEXT,
  spdx_or_url TEXT,
  license_class TEXT NOT NULL,
  attribution_text TEXT,
  notes TEXT
);

-- 出典（不変）。source_id は ryuiki.sqlite の source_registry.source_id そのまま（bare。
-- cube・D1・alias は bare のまま）。公開 ID は source_ref_id = 'common:source:' || source_id。
-- superseded_by は置き換え先の source_id（旧 ID は消さない。ADR-0004 規約2）。
-- source_registry（D1 の v1 表）は並走して残す。
CREATE TABLE IF NOT EXISTS source (
  source_id TEXT PRIMARY KEY,
  source_ref_id TEXT NOT NULL,
  name_ja TEXT,
  publisher TEXT,
  homepage_url TEXT,
  region_id TEXT,
  theme TEXT,
  access_method TEXT,
  superseded_by TEXT,
  notes TEXT
);

-- 出典の版（取得回、または出典自身の版 = vintage）。edition_id = common:edition:<source_id>.<edition_key>。
-- redistributable/license_class/commercial_ok は出典の旗であり、出力を絞る根拠にしない
-- （ADR-0005 改定・ADR-0028。embargo_reason 列は作らない）。license_raw は source_registry.license の原文。
-- 過去の取得履歴は復元不能なので作らない（宣言した版と現在の 1 版だけ。registry/source/editions.yaml）。
CREATE TABLE IF NOT EXISTS source_edition (
  edition_id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL,
  edition_key TEXT NOT NULL,
  vintage TEXT,
  fetched_at TEXT,
  url TEXT,
  format TEXT,
  content_sha256 TEXT,
  license_id TEXT NOT NULL,
  license_raw TEXT,
  license_class TEXT NOT NULL,
  redistributable INTEGER,
  commercial_ok INTEGER,
  record_count INTEGER,
  superseded_by TEXT,
  update_mode TEXT,
  notes TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_source_edition_source_key ON source_edition(source_id, edition_key);

-- 出典ごとの「ツールで値が取れるか」(docs/plans/MCP_SOURCE_ACCESS.md §1)。source 1 行 = 1 行(合成データを含む)。
-- 正は registry/source/access.yaml と manifests/(build_source_access.py が原本と突き合わせて作る)。
-- state: queryable / not_queryable。queryable_via・tables は JSON(配列)。record_set_rows は JSON(オブジェクト。record_set → その出典の行数。get_records の n_total)。
-- n_source_rows は原本の行数(キューブの集計行数ではない)。basis: source_rows / registry_record_count / catalog_datasets(外部ポータルの目録の件数＝データセット数) / none。
-- counted_at は件数を数えた原本の最新取得日時(source_registry.fetched_at の最大。決定論のため実行時刻は使わない)。
-- not_queryable のときだけ reason(コード)・reason_ja・reason_note を持つ。
CREATE TABLE IF NOT EXISTS source_access (
  source_id TEXT PRIMARY KEY,
  state TEXT NOT NULL,
  queryable_via TEXT NOT NULL,
  tables TEXT NOT NULL,
  record_set_rows TEXT NOT NULL DEFAULT '{}',
  n_source_rows INTEGER,
  n_source_rows_basis TEXT NOT NULL,
  counted_at TEXT,
  reason TEXT,
  reason_ja TEXT,
  reason_note TEXT
);

-- 空間単位(ADR-0006)。Phase A で登録するのは集計軸として実在するものだけ
-- (site / watershed / mesh3 / zone)。geometry_ref は持たない(点→place の解決も含め
-- Phase B 以降)。region_id は place_id 自身のスコープ(<scope>:place:...)と一致させる
-- (ADR-0022 決定1。common なら NULL、地域固有なら region_id、例: jp-14)。
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

-- 空間単位どうしの関係(ADR-0006)。Phase B(phase-b/region-scope, ADR-0022)で新設。
-- 最初に作った辺は「地点 -> ゾーン」(parent_id=ゾーンの place_id, child_id=地点の
-- place_id, relation='within')。Phase B `phase-b/place-attributes`(P-1a)で
-- 「地点 -> 流域」(sites.watershed 由来)を追加し、現在は2種類。fraction は
-- NOT NULL とし、全体を含む関係には 1.0 を入れる("NULL=全体"のような暗黙の意味を
-- 持たせない。ADR-0011 の「fraction があるものは加重する」を常に同じ式で書ける
-- ようにするため)。ADR-0006 が挙げる source_edition_id 列はまだ持たない: 出典の
-- 版管理(source_registry/source_edition, ADR-0005)自体が Phase C の仕事で、いま
-- 作っている辺(地点->ゾーンは registry/place/zone.yaml、地点->流域は
-- data/processed/nlni_w12_watersheds.jsonl)の出典はそれぞれ単一の手書き/配布
-- ファイルに固定されており、版を切り替える必要が今は無い(ADR-0022 決定3)。
-- (parent_id, child_id, relation) の一意性は DDL の UNIQUE 制約ではなく
-- scripts/r01_build_registry.py 側の Python 表明で検証する(variable_alias の
-- (dataset, alias, source_id) 一意性と同じ流儀。registry/README.md 参照)。
-- web の D1(schema.ts/schema-registry.ts)にはまだ載せない: 消費者がまだ無く、
-- D1 は捨てて作り直せる配信キャッシュ(ADR-0001)なので、使う側が現れてから足す。
CREATE TABLE IF NOT EXISTS place_relation (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  parent_id TEXT NOT NULL,
  child_id TEXT NOT NULL,
  relation TEXT NOT NULL,
  fraction REAL NOT NULL,
  basis TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_relation_parent ON place_relation(parent_id);
CREATE INDEX IF NOT EXISTS ix_place_relation_child ON place_relation(child_id);

-- v1 の出典側識別子(sites.site_id / watershed_meta.watershed_id / mlat,mlon 等)から
-- place への対応。「v1 を動かさずに並走させる」ための接続点(PHASE_A.md §A-3)。
-- external_key からの逆引きが主な引き方。
-- key_space = 外部キーの空間(site_id | zone | watershed_id | grid01_latlon。
-- registry/place/key_space.yaml が宣言。旧 source_id 列の値 'sites.site_id' 等を
-- Issue #39 Phase C で改称した。出典ではないので source_id とは呼ばない)。
-- source_edition_id = その行の出典の版(NULL 可。出典を持たない key_space は NULL)。
CREATE TABLE IF NOT EXISTS place_source_ref (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  place_id TEXT,
  external_key TEXT,
  key_space TEXT,
  source_edition_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_external ON place_source_ref(external_key);
CREATE INDEX IF NOT EXISTS ix_place_source_ref_place ON place_source_ref(place_id);

-- kind 固有の属性サテライト(ADR-0006 §「place の属性」、ADR-0011「place_attribute」
-- カテゴリの具体形、Phase B `phase-b/place-attributes`)。place 本体の列は増やさず、
-- watershed だけが持つ属性(旧 derived.watershed_meta の残り4列)をここに置く。
-- water_system_code は v1 の水系コード(旧コード、10桁未満)をそのまま文字列で持つ
-- (親 place(water_system)+place_relation にする案は今回の再現には過剰なので採用しない。
-- ADR-0006 追記参照)。main_rivers は主要河川が無い流域(143/377)向けの空文字列を
-- そのまま持つ(JSONL の生値・v1 とも NULL ではなく空文字列。丸めない)。
-- 1 place_id につき高々1行(1:1)。place と同様に web の D1(schema.ts/schema-registry.ts)
-- にはまだ載せない: place_relation と同じ理由で、消費者がまだ無い。
CREATE TABLE IF NOT EXISTS place_watershed (
  place_id TEXT PRIMARY KEY,
  water_system_code TEXT,
  water_system_category TEXT,
  main_rivers TEXT,
  data_year INTEGER
);

-- 分類群レジストリ(ADR-0019。taxon_id の名前空間分割・分類補完は Phase B
-- phase-b/occurrence-registry。決定と理由の正は ADR-0019 の日付付き追記、
-- 実測の正は docs/plans/PHASE_B_OCCURRENCE.md。ここには列の意味だけ書く)。
--
-- taxon_id は出典ごとに名前空間を分ける: GBIF 由来は common:taxon:gbif.<GBIFのtaxonKey>、
-- iNaturalist 由来は common:taxon:inat.<iNatのtaxon.id>(GBIFのtaxonKeyとは無関係な
-- 別の数値空間)、taxa(v1)由来で GBIF 未照合のものは common:taxon:ryuiki-taxa.<taxaの主キー>。
-- 名前空間の対応の正は scripts/common.py の TAXON_KEY_SOURCE_NAMESPACE。
-- gbif_taxon_key 列は本物の GBIF taxonKey のときだけ埋める(iNat 由来行は常に NULL)。
-- accepted_taxon_id は status='synonym' のときに正の taxon を指す
-- (ADR-0004 規約2: ID は不変、実体が変わったら新 ID を作り旧 ID は残す)。
--
-- kingdom/phylum/class/order/family/classification_basis/canonical_binomial/
-- taxon_group は v1 (org_norm) の分類補完規則を taxon 単位でレジストリのビルダー側に
-- 移したもの。classification_basis は class の解決経路 ('source'=出典が直接持つ /
-- 'binomial_match'=同じ二名法キーの他記録からの多数決 /
-- 'genus_match'=同じ属の他記録からの多数決 / 'no_match'=解決不能。
-- taxon.status='unresolved' と紛らわしいため 'unresolved' から改名)。
-- order/family は多数決による補完をしない。taxon_group は
-- registry/taxon/taxon_group.yaml から機械的に生成した日本語ラベル。
-- status は 'accepted'/'unresolved' に加え、分類の多数決が不確か(同数、または
-- 属が複数classにまたがる)な taxon だけ 'needs_review' を持つ(accepted/unresolved
-- どちらの行にも起こりうる)。
--
-- vernacular_name_en（Issue #48 PR-3a）: organism_records.vernacular_name の
-- うちラテン文字だけの値を (名前空間, taxon_key) ごとに最頻値(同数は値の昇順)で
-- 選んだもの。gbif/inat 名前空間の行にだけ付く(taxa 由来の unresolved 行は常に
-- NULL——organism_records に対応する taxon_key が無いため)。「英名」ではなく
-- 「ラテン文字の俗名」であることに注意(ローマ字表記・属の仮名も入りうる。
-- registry/README.md 参照)。
--
-- vernacular_ja_basis（同PR、D4）: vernacular_name_ja の出処。'override'
-- (registry/taxon/vernacular_ja.csv の人手確認済み54件)/'taxa'(taxa 由来、
-- gbif_match_type='EXACT' の代表行 or unresolved 行自身)/'records'
-- (vernacular_name_ja が override/taxa のどちらからも埋まらなかった行だけ、
-- organism_records.vernacular_name の非ラテン文字の最頻値で補完したもの)。
-- 優先順は override > taxa > records——override は taxa 由来の値があっても
-- 無条件に上書きする(build_taxon.py モジュール docstring 参照)一方、records
-- 補完は vernacular_name_ja が NULL の行にだけ適用し、既存の値は1件も変えない。
-- 双方とも NULL のまま(候補が無い)行は vernacular_ja_basis も NULL。
-- 'supplement'(2026-10-07): registry/taxon/supplement_taxa.csv の手書き行の和名(人が確かめた値。override と同格)。
-- classification_basis にも 'supplement'(分類列を CSV の値で持つ補完 taxon)がある。
CREATE TABLE IF NOT EXISTS taxon (
  taxon_id TEXT PRIMARY KEY,
  scientific_name TEXT,
  canonical_binomial TEXT,
  rank TEXT,
  kingdom TEXT,
  phylum TEXT,
  class TEXT,
  "order" TEXT,
  family TEXT,
  classification_basis TEXT,
  taxon_group TEXT,
  gbif_taxon_key TEXT,
  vernacular_name_ja TEXT,
  vernacular_name_en TEXT,
  vernacular_ja_basis TEXT,
  status TEXT,
  accepted_taxon_id TEXT
);
CREATE INDEX IF NOT EXISTS ix_taxon_gbif_key ON taxon(gbif_taxon_key);
CREATE INDEX IF NOT EXISTS ix_taxon_binomial ON taxon(canonical_binomial);

-- 版ごとの分類群の評価(ADR-0019 の最小形。P-2、2026-09-23追記。
-- docs/adr/0019-taxon-registry.md の日付付き追記 / docs/plans/PHASE_B_TAXON_ASSESSMENT.md)。
-- v1 の redlist_assessments(2,884行、rl2020/rdb2022p/rl2026 の3版)と
-- taxa.ias_category 由来の外来種評価(moe_ias_2015、v1 は data/processed/moe_ias_list.csv
-- 由来)を、同じ「あるリストがある分類群に付けた評価」という構造に統合したもの。
-- Phase A/B 当初は D1(web/src/db/schema-registry.ts)の消費者が無いとして
-- 見送っていたが、Issue #48(PR-0)で D1 に追加した(web 側の taxonAssessment
-- 定義参照)。
--
-- list_id は registry/taxon/assessment_list.yaml のコードリスト。
-- category_code/prev_category_code は registry/taxon/redlist_category.yaml +
-- redlist_category_alias.csv で正規化したコード(list_id='moe_ias_2015' の行は
-- 専用のコードリストを持たないため常に NULL。category_raw だけを持つ)。
-- category_raw/prev_category_raw/national_category_raw は原表記を無加工で残す
-- (正規化は alias を引くキーにだけ使う。category_raw 自体は改行・空白を含め
-- そのまま)。prev はその版の文書が自分で書いている「前回区分」の原表記であり、
-- 版どうしを JOIN して導いたものではない(ADR-0019 決定5への例外。理由は
-- docs/adr/0019-taxon-registry.md 追記参照)。
-- taxon_id は解決できた分だけ埋める(学名の完全一致 → 二名法一致の順。
-- 解決できない行は NULL のまま——Phase B の再現(v1は名前を文字列で運ぶ)には
-- 不要な診断用の列)。origin は外来種リストの由来区分(moe_ias_list.csv の
-- origin_ja。レッドリスト側の行は常に NULL)。
--
-- vernacular_name_ja_resolved (P-2、/code-review 対応、2026-09-23):
-- moe_ias_2015 の行だけが持つ、v1 の `taxa.vernacular_name_ja`(3出典をまたいだ
-- 畳み込み済みの和名)相当。NULL もありうる(空文字に丸めない)。redlist側の行は
-- 常に NULL。背景・実測・畳み込みの詳細は
-- scripts/registry/build_taxon_assessment.py のモジュール docstring「和名の解決」・
-- docs/plans/PHASE_B_TAXON_ASSESSMENT.md 参照。
--
-- in_scope (Issue #48 PR-3a、D7): registry/taxon/assessment_scope_exclusions.yaml
-- に宣言した7種（moe_ias_2015 の binom による誤ヒット除外。P-2 オーナー決定A）
-- を 0、それ以外の全行(redlist 3版含む)を 1 にした列。**このテーブル自体は
-- moe_ias_list.csv の429行をそのまま持つ「正の記録」であり、除外は一切しない
-- (build_taxon_assessment.py モジュール docstring「除外7種」参照)。in_scope は
-- 除外の判断をデータから消さず、消費者(scripts/b08_project_occurrence_v1.py の
-- ias_species 射影・将来の D1 側の画面)が「宣言済み除外を機械的に反映した集合」を
-- 引けるようにするための可視化列——値そのものは動かさない。
--
-- binom (Issue #48 PR-3b §2.4): binom_of(scientific_name_raw)（二名法。取れなければ
-- NULL）。IAS は taxon_id が 346/429 しか解決せず、taxon_id 結合だと v1 の
-- ias_species（173行）が 50 行にしかならないため、binom で結合できるようにする。
CREATE TABLE IF NOT EXISTS taxon_assessment (
  assessment_id TEXT PRIMARY KEY,
  list_id TEXT NOT NULL,
  list_year INTEGER,
  taxon_id TEXT,
  scientific_name_raw TEXT,
  vernacular_name_ja_raw TEXT,
  vernacular_name_ja_resolved TEXT,
  taxon_group_ja TEXT,
  taxon_subgroup_ja TEXT,
  family_ja TEXT,
  category_raw TEXT,
  category_code TEXT,
  prev_category_raw TEXT,
  prev_category_code TEXT,
  national_category_raw TEXT,
  origin TEXT,
  source_id TEXT,
  in_scope INTEGER,
  binom TEXT,
  -- scope_reason (Issue #34): in_scope=0 の理由コード（domestic_origin /
  -- subspecies_binomial_contraction、重なれば ',' 連結）。in_scope=1 は NULL。
  scope_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_taxon_assessment_list ON taxon_assessment(list_id);
CREATE INDEX IF NOT EXISTS ix_taxon_assessment_taxon ON taxon_assessment(taxon_id);

-- 注意事項(ADR-0013)。caveat_id は web/src/lib/ai/caveats.ts が今返しているキー文字列を
-- そのまま使う(common:caveat:<key>)。cells.notes 由来は common:caveat:cells.<note の主キー>。
--
-- 計画(PHASE_A.md §A-1)では caveat 単体に scope_kind/scope_ref を持たせる7テーブル構成
-- だったが、A-5 の実装時に「1つの注記が複数のテーブルに掛かる」(例: censored は
-- measurements/meas_year/meas_month など9テーブルに掛かる)ことが分かり、caveat_id を
-- 主キーにしたままでは1:Nを表せなかった。そのため caveat は注記そのものに絞り、
-- スコープは caveat_scope に切り出した(計画の7テーブル→8テーブルの逸脱。
-- 理由の詳細は scripts/registry/build_caveat.py の docstring)。
CREATE TABLE IF NOT EXISTS caveat (
  caveat_id TEXT PRIMARY KEY,
  severity TEXT,
  kind TEXT,
  title_ja TEXT,
  body_ja TEXT,
  quote TEXT
);

-- caveat が掛かる範囲。1注記に対して複数行になりうる(1:N)。scope_kind は ADR-0013 の6種
-- (variable/place/source_edition/observation_set/dataset/taxon)、scope_ref は ID か キー=値 の選択式
-- (宣言は registry/caveat_scope.yaml。Issue #35)。「どれを先頭に出すか」という優先規則は
-- scope_kind ではなく priority 列が持つ(既定0。大きいほど優先)。
-- 順序復元の方法は scripts/registry/build_caveat.py の docstring 参照。
CREATE TABLE IF NOT EXISTS caveat_scope (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  caveat_id TEXT,
  scope_kind TEXT,
  scope_ref TEXT,
  sort_order INTEGER,
  priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_caveat_scope_scope ON caveat_scope(scope_kind, scope_ref);
CREATE INDEX IF NOT EXISTS ix_caveat_scope_caveat ON caveat_scope(caveat_id);

-- ビルドの指紋(phase-b/registry-atomic)。「在る」ことと「正しい」ことを区別するための
-- 1行だけのメタ表。UNIQUE 制約は持たせず、r01 側の運用(INSERT 前に DELETE FROM)で
-- 単一行を保証する(他の複合キーと同じく、この程度の不変条件のために表自体の設計を
-- 複雑にしない)。web/src/db/schema-registry.ts(D1)には載せない: place_relation と同じ
-- 理由で、D1 側に消費者がいない(この表を読むのは r01 --check-fresh だけ)。
-- input_fingerprint は scripts/registry/common.py の compute_input_fingerprint()
-- (ビルドの論理 + registry/ 配下の手書き入力から算出した sha256)。
-- mode は 'full'(原本DBを読む通常ビルド) / 'files_only'(--files-only、CI用)。
-- 実行時刻は持たない(決定論。他のキューブ生成物と同じ理由)。
CREATE TABLE IF NOT EXISTS registry_build (
  input_fingerprint TEXT NOT NULL,
  mode TEXT NOT NULL
);

-- ID の改称の記録(ADR-0004 規約2。置換(superseded_by)とは別物)。
-- registry/id_map/<entity>.csv の宣言から作る。受け入れ検証は「旧 ID の凍結リストの
-- 各行が id_map(または恒等)でちょうど1個の現行 ID に解決する」こと。
CREATE TABLE IF NOT EXISTS id_map (
  entity TEXT NOT NULL,
  old_id TEXT NOT NULL,
  new_id TEXT NOT NULL,
  reason TEXT,
  spec_version TEXT,
  PRIMARY KEY (entity, old_id)
);
CREATE INDEX IF NOT EXISTS ix_id_map_new ON id_map(entity, new_id);
