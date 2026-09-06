# ADR-0007: 観測値を単一の縦持ちファクト `observation` に集約する

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0003（標準）, ADR-0008（時間）, ADR-0009（検閲）, ADR-0010（指標）, ADR-0011（キューブ）

## 背景

現行では「ある場所・ある時に測った値」が3つの表に別々の語彙で入っている。

| テーブル | 行数 | 主語 | 指標列 | 時間列 | 値列 |
|---|---|---|---|---|---|
| `measurements` | 323,164 | `site_id` | `variable`（58種） | `measured_on` | `value` + `unit` |
| `sensor_timeseries` | 717,839 | `site_id` | `datastream` | `phenomenon_time` | `result` + `unit` |
| `mammal_mesh` | 75,240 | メッシュ | 種名（列） | `survey_label` | 有無 |

同じ物理量が両方に入っている実例がある（`OX` は `sensor_timeseries` に、
光化学オキシダントは行政文書由来で `measurements` にも現れる）。加えて Tier 1 追加時に
`wildlife_sightings` `vegetation_polygons` 等が別テーブルとして増えた（README §1(d)）。

## 決定

**主語・指標・時間・値の4点で表せる観測は、すべて単一の `observation` に入れる。**

```
observation
  observation_id, region_id,
  variable_id,                      -- ADR-0010 のレジストリ参照
  place_id, place_kind,             -- ADR-0006
  taxon_id,                         -- 生物に関する量のときのみ（例: メッシュ×種の確認）
  feature_id,                       -- 地物に関する量のときのみ
  period_start, period_end, grain,  -- ADR-0008
  value_num, value_text, unit_id,
  censoring, censoring_limit,       -- ADR-0009
  stat,                             -- 'instant'|'mean'|'max'|'min'|'sum'|'presence' ...
  method_id, instrument_id, event_id, observer_id,
  quality_stage, is_synthetic,
  source_edition_id, source_ref
```

原則:

1. **主語は「place または座標」。** 座標しか持たないファクト（`organism_records` は
   823,692行すべて `site_id` が NULL）は、ADR-0006 の点→place 解決規約で place を導く。
   解決できない場合は `place_id=NULL` のまま保持し、キューブの対象外にする
   （データは落とさない／推測で割り当てない）。taxon / feature は任意。
   「メッシュ×種の確認記録」は place + taxon で表せるので `mammal_mesh` は専用テーブルを要さない。
2. **`stat` を持つ。** 出典が既に集計値を配っている場合（`河川水位_日平均`）、
   名前に埋めず `variable_id=水位, grain=day, stat=mean` と分解する。
   これが README §1(c) の「名前に単位と集計粒度が埋まっている」の解。
3. **`observation` と `occurrence` は分ける。** 生物の出現記録（823,692行）は
   「個体を見た」という別種の事実で、DwC Occurrence への射影があり、同定根拠・
   ライセンス区分など固有の属性を持つ。無理に量として表さない。
4. 物理的には `grain` と `region_id` でパーティションする（Parquet）。高頻度センサー
   （718k行）と年次値（105k行）が同じ論理テーブルでも I/O が干渉しないようにする。

## 影響

- **良い**: 新しい測定系の追加でテーブルが増えない。指標をまたぐ比較（降雨と濁度、
  シカ密度と植生）が結合なしで書ける。ADR-0011 のキューブが単一の入力から作れる。
  eMoF / SensorThings への射影が1箇所で済む。
- **コスト**: 約110万行の縦持ち1本になり、幅の広い行が増える（taxon_id / feature_id は
  多くの行で NULL）。列指向（Parquet）と D1 側の適切なインデックスが前提。
  値の型が `value_num` / `value_text` に分かれ、利用側は指標レジストリで型を知る必要がある。
- **リスク**: 「何でも observation に入れられる」ため、本来 `feature` や `occurrence` に
  属すべきものが流れ込みやすい。**判定基準**（主語が place で、値が指標レジストリに
  登録済みの量であること）をマニフェストの検証で強制する（ADR-0012）。

## 検討した代替案

- **測定系ごとにテーブルを分けたまま、ビューで統合**: 移行が軽いが、ビューの列合わせを
  ソース追加のたびに直す必要があり、増殖の問題が形を変えて残る。却下。
- **完全な EAV（主語も型なしにする）**: さらに柔軟だが、主語の型が消えると
  クエリもキューブも書けない。主語は place を必須にすることで型を保つ。却下。
- **ワイド形式（指標を列にする）**: 分析は楽だが、58種＋センサー多数の指標が列として
  増え続け、多地域で指標集合が違うと破綻する。却下。
