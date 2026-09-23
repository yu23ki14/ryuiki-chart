# ADR-0011: 派生33テーブルを単一キューブ＋宣言的集計定義に置き換える

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0006（place）, ADR-0007（observation）, ADR-0008（時間）, ADR-0009（検閲）

**2026-09-08 追記（ADR-0021 で拡張）**: 次元キーの `stat` だけでは、出典が既に別々の統計量として
配っている系列（`pH（最大値）`/`pH（最小値）` 等）が同じ格に混ざることが Phase B の実装で判明した。
`obs_stat`（入力側の統計量）・`value_grain`・`input_grain` を次元キーに追加している。詳細は
[ADR-0021](0021-observation-grain-and-cube-key.md)。

**2026-09-15 追記（センサーの縦線・ADR-0024）**: 「メンバーの区間がセルの区間をはみ出す集計」
（v1 が hour_ending の24時ラベルを翌日のセルに含めてしまうラベル日割りのような、セルの期間宣言
と実際のメンバーの区間が食い違う集計）と、「climatology の軸」（`sensor_hour_month` の月×時刻の
平年値のように、`grain` の語彙に無い集計軸）は、どちらもキューブのセルにしない
（`docs/plans/PHASE_B_FACT_SLICE.md` D10 の原則の実例が2つ目・3つ目に増えた。1つ目は
`meas_clim`/`site_var`/`var_catalog`）。射影（`scripts/b05_project_v1.py`）が L2
（`observation`）から直接作ることがある——本節が既に許している「事前計算しなかった軸は `dist/`
の Parquet への直クエリに任せる」と同じ考え方を、v1 互換の射影という形で先取りしたもの。

**2026-09-22 追記（[ADR-0025](0025-occurrence-fact-and-cube.md) D2）**: 本 ADR の
「入力は `observation` と `occurrence` の2つ」は物理表を1つに限っていない。
**1ファクト＝1キューブ表**（`observation` → `observation_agg`、`occurrence` →
`occurrence_agg`）とし、鍵の規律（`staged_table`・`COALESCE(c,'')` の
`UNIQUE INDEX`・`built_from`/`spec_version`）は両者で共通にする、と明確化した。

**2026-09-22 追記（P-3、`docs/plans/PHASE_B_DOCUMENTS.md`）**: `doc_series`/`quality_monthly`
を「キューブ（入力 `observation`）」に分類していたのは誤りだった。実際の入力は
`observation` ではなく、`doc_series`/`doc_series_meta` は `cells.sqlite`（ADR README §4 の
`document`/`cell` エンティティの v1 実体）、`quality_monthly` は `ryuiki.sqlite` の
`quality_transitions`（ADR-0017 が読み取り基盤の対象外とする書き込み系ログ）。どちらも
主語が place ではなく、ADR-0007 の observation の判定基準を満たさない。この2表を
「`document`/`cell` の証跡層からの射影」（旧 `doc_meta` を吸収）と「ADR-0017 書き込み系
ログの射影」の2カテゴリへ切り出した（下表・`scripts/reconcile/adr0011_destinations.yaml`）。
`cells`/`quality_transitions` は v2 の新しいファクトに変換せず、**v1 の表のまま L2 に
持ち越す**（ADR-0017 原則4「デモに含まれる合成の可変データは当面 L2 の一部として扱う」と
同じ書き方。射影は `scripts/b10_project_documents_v1.py` が cells.sqlite/ryuiki.sqlite を
読み取り専用で ATTACH し、v1 と同じ SQL をそのまま再実行する）。

## 背景（実測）

`derived.sqlite` の**33テーブル**は、画面・AIツール・チャート部品ごとに個別対応で作られている。
決定的なのは参照の数ではなく**形**である。

列構成を並べると、全部が同じ骨格をしている。

```
meas_year          : site_id, variable, kind, year        -> n, avg, min, max, n_censored, unit
meas_month         : site_id, variable, ym                -> n, avg, unit
meas_daily         : site_id, variable, d                 -> value, n_raw, n_censored, unit
meas_clim          : (site), variable, month              -> n, avg, unit
zone_year          : zone,    variable, kind, year        -> n_sites, n, avg, unit
zone_clim          : zone,    variable, month             -> n_sites, n, avg, unit
sensor_daily       : site_id, datastream, d               -> n, avg, min, max, unit
sensor_hour_month  : site_id, datastream, month, hour     -> n, avg
rain_daily         : d                                    -> mm, n_hours
mesh_year          : mlat, mlon, year                     -> n, species_n, rl_n
species_mesh_year  : binom, mlat, mlon, year              -> n
species_year2      : binom, year                          -> n, mesh_n
species_month      : binom, month                         -> n
org_watershed_year : watershed_id, year                   -> n, species_n, alien_n, redlist_n
org_group_year     : year, taxon_group, source_id         -> n, species_n, mesh_n
landuse_watershed  : watershed_id, year, landuse_code     -> n_cells, area_km2
effort_year        : year                                 -> n, species_n, mesh_n, n_inat, n_gbif
quality_monthly    : month                                -> ...
```

**すべて `(場所, [分類群], 指標, 期間, 粒度) -> 統計量`。** 33テーブルは1本のキューブの射影。
この形のままだと *データ種類 × 集計軸 × 画面* でテーブルが増え続け、
可視化をシビックテックに開くほど破綻する（可視化の自由度＝集計軸の自由度だから）。

（**2026-09-22 追記**: 「骨格が同じに見える」ことと「同じキューブの1セルとして表せる」
ことは別だった。「33テーブルの行き先」表のとおり、実際にキューブへ入るのは23表
（`cube_observation` 12 + `cube_occurrence` 11）で、残り10表は `variable` レジストリ・
`place` の属性・`taxon`/`taxon_assessment`・L2 ファクト本体・`document`/`cell` の証跡層・
ADR-0017 書き込み系ログのような、キューブ以外の行き先に整理される。`quality_monthly`
は上の例で「同じ骨格」の実例として挙げているとおり見た目はキューブのセルに見えるが、
実際の入力は `observation` ではなく書き込み系ログで、判定基準（ADR-0007）を満たさない
——P-3 でこの区別が実例として見つかった。詳細は下記「33テーブルの行き先」表と
その直前の追記。）

## 決定

**L3 を単一の `observation_agg` キューブ1本にし、どの集計を作るかは宣言的な
集計定義（YAML）で表す。テーブルを手書きしない。**

```
observation_agg
  region_id, variable_id, place_id, place_kind, taxon_id,
  period_start, period_end, grain,
  stat,                 -- 'mean'|'min'|'max'|'sum'|'count'|'n_distinct'|'presence'
  value, unit_id,
  n, n_censored, n_places, imputation,   -- ADR-0009
  coverage_ratio,       -- 期間内のうち実データがあった割合
  built_from, spec_version, built_at     -- 再現性
```

集計定義の例:

```yaml
# aggregations/water_quality.yml
- name: water_quality_by_site
  source: observation
  filter: { theme: water_quality }
  group_by: [place_id, variable_id]
  periods:  [day, month, year, fiscal_year, climatology_month]
  stats:    [mean, min, max, count]
  imputation: [zero, lod]        # 必須。上下限を併記（ADR-0009）
- name: water_quality_by_zone
  extends: water_quality_by_site
  roll_up_to: [zone, watershed, municipality]   # place_relation を辿る（ADR-0006）

# 生物系は occurrence を入力にする
- name: biota_by_mesh
  source: occurrence                    # ← observation ではない
  group_by: [place_id, taxon_id]
  periods:  [year]
  stats:    [count, n_distinct_taxon, presence]
  flags:    [is_alien, red_list]        # org_watershed_year の alien_n / redlist_n 相当
```

**入力は `observation` と `occurrence` の2つ。** 生物系の派生（`mesh_year` /
`species_mesh_year` / `species_year2` / `species_month` / `species2` / `mesh_all` /
`mesh_species` / `org_watershed` / `org_watershed_year` / `org_group_year` /
`effort_year`）は `occurrence` を入力とし、`count` / `n_distinct` / `presence` の
統計量で作る。observation だけを入力にすると生物系10テーブル超の行き先が無くなる。

- **新しい集計軸の追加は YAML に1行。** テーブルもマイグレーションも増えない（合格条件2）。
- ロールアップは `place_relation` の `within` を辿る。`fraction` があるものは加重する。
- **粒度をまたぐ再集計をしない。** 日→月→年の順で積み上げ、年度と暦年は別系列として作る（ADR-0008）。
- `built_from` / `spec_version` により、キューブの各行がどの L2 版とどの定義から作られたかを辿れる。
- キューブに載らない特殊な派生（`watershed_rollup` の面積・重心、`redlist_change` の版間比較、
  `org_norm` の正規化コピー）は**キューブではなく L2 のレジストリ属性**に移す
  （`place` の属性 / `taxon_assessment` / `occurrence` 本体）。

### 35テーブルの行き先

### 33テーブルの行き先（合計が 33 に一致することを確認済み）

| 行き先 | 現行テーブル | 数 |
|---|---|---|
| キューブ（入力 `observation`） | meas_daily, meas_month, meas_year, meas_clim, zone_year, zone_clim, sensor_daily, sensor_hour_month, rain_daily, landuse_watershed, landuse_change, site_var | 12 |
| キューブ（入力 `occurrence`） | mesh_year, mesh_all, mesh_species, species_mesh_year, species_month, species_year2, species2, org_watershed, org_watershed_year, org_group_year, effort_year | 11 |
| `variable` レジストリ | var_catalog | 1 |
| `place` の属性 | watershed_meta, watershed_rollup | 2 |
| `taxon` / `taxon_assessment`（ADR-0019） | redlist_map, redlist_change, ias_species | 3 |
| L2 のファクト本体に統合 | org_norm（`occurrence` に吸収） | 1 |
| `document`/`cell` の証跡層からの射影（cells.sqlite。v1 表のまま持ち越し） | doc_series, doc_series_meta | 2 |
| ADR-0017 書き込み系ログの射影（quality_transitions。v1 表のまま持ち越し） | quality_monthly | 1 |

`watershed_rollup` は宣言（`place_attribute`）を動かしていないが、D10型の結合射影
（`watershed_meta`/`org_watershed`/`site_var`/`landuse_watershed` の4表を組み合わせる
だけで、独立したキューブのセルにはしない）であることに注記しておく
（`scripts/reconcile/adr0011_destinations.yaml` のコメント参照）。

## 影響

- **良い**: 可視化側が「用意されたテーブル」ではなく「軸の組み合わせ」でデータを取れる。
  MCP のツールが1つで済む（ADR-0014 の `get_observations`）。集計ロジックがコードから
  データ（YAML）に移り、レビューできるようになる。
- **コスト**: キューブの行数は現行派生の合計（実測 2,070,295行）より増える可能性が高い
  （軸の組み合わせを先に作るため）。**全組み合わせは作らない。**
  初期の事前計算は次に絞る:
  `place_kind ∈ {site, watershed, mesh3}` × `grain ∈ {day, month, year, fiscal_year}`
  × `imputation ∈ {zero, lod}`。それ以外の軸は `dist/` Parquet への DuckDB 直クエリに任せ、
  需要が確認できたものだけ事前計算に足す。この線引きは手順5（物理設計）で確定する。
- **リスク**: 事前計算しなかった軸の問い合わせが遅くなる。L2 Parquet への直接クエリ
  （DuckDB）を逃げ道として用意する。

## 検討した代替案

- **派生テーブルを整理して数を減らす**: 短期的には効くが、増殖の構造は変わらない。却下。
- **キューブを持たず、都度集計する**: 保守は最小だが、D1 で 110 万行のファクトを
  毎回走査するのは配信要件を満たさない。却下。
- **画面ごとの派生テーブルを自動生成する**: 手書きは減るが、外部の可視化作者が
  自分の軸を足せないままで、目的（シビックテックに開く）に反する。却下。
