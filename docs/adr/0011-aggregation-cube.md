# ADR-0011: 派生33テーブルを単一キューブ＋宣言的集計定義に置き換える

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0006（place）, ADR-0007（observation）, ADR-0008（時間）, ADR-0009（検閲）

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
| キューブ（入力 `observation`） | meas_daily, meas_month, meas_year, meas_clim, zone_year, zone_clim, sensor_daily, sensor_hour_month, rain_daily, landuse_watershed, landuse_change, quality_monthly, doc_series, site_var | 14 |
| キューブ（入力 `occurrence`） | mesh_year, mesh_all, mesh_species, species_mesh_year, species_month, species_year2, species2, org_watershed, org_watershed_year, org_group_year, effort_year | 11 |
| `variable` レジストリ | var_catalog | 1 |
| `place` の属性 | watershed_meta, watershed_rollup | 2 |
| `taxon` / `taxon_assessment`（ADR-0019） | redlist_map, redlist_change, ias_species | 3 |
| L2 のファクト本体に統合 | org_norm（`occurrence` に吸収） | 1 |
| `document` / `variable` のメタ | doc_series_meta | 1 |

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
