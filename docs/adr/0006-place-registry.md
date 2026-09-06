# ADR-0006: 空間単位を単一の `place` レジストリに統合する

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0002（多地域）, ADR-0004（識別子）, ADR-0007（observation）, ADR-0011（キューブ）

## 背景

現行では「場所」が5種類以上の別々の形で表現されている。

| 種類 | 現行の表現 | 例 |
|---|---|---|
| 観測地点 | `sites.site_id`（352行） | 文字列 ID |
| 流域 | `sites.watershed` / `watershed_meta`（110種・377行） | `83032-0024`（国土数値情報） |
| 3次メッシュ | `mesh_year.mlat` + `mlon` の**2列** | 整数ペア |
| ゾーン（R2R） | `sites.zone` の整数 1〜5 | 操作的定義（`docs/ZONE_DEFINITION.md`） |
| 町丁目 | `water_zone`（5,089行） | 2020年国勢調査 小地域コード |
| 河川区間 | `river_segments`（1,547行） | 独自 |
| 市区町村 | `sites.municipality` / `muni_code` | **290地点では水域名が入っている** |

このため:

- 「この地点を含む流域は？」「この流域に含まれるメッシュは？」に答える共通の仕組みがなく、
  集計軸ごとに専用の派生テーブルが必要になっている（`mesh_year` / `zone_year` /
  `org_watershed_year` / `landuse_watershed` …）。
- `sites.municipality` は出典によって中身が変わる（環境省 公共用水域の290地点は水域名、
  残り62地点は市区町村名）。列名と中身が一致していないため、画面では「水域・地域」と
  呼び替えて逃げている（`web/src/lib/domain.ts`）。**MCP からはこの逃げが効かない。**
- ジオメトリの置き場が `web/public/geo/*.geojson`（静的アセット）とテーブル
  （`vegetation_polygons` 等）に分かれている。

## 決定

**空間単位を `place` の1テーブルに統合し、種別は `place_kind`、包含・隣接関係は
`place_relation` の辺で表す。**

```
place           place_id, region_id, place_kind, name_ja, name_en,
                lat, lon, elevation_m, area_km2, geometry_ref, valid_from, valid_to,
                definition_ref, source_edition_id
place_relation  parent_id, child_id, relation ('within'|'overlaps'|'adjacent'|'flows_to'),
                fraction, basis, source_edition_id
place_source_ref place_id, source_edition_id, external_key   -- 出典側の識別子
```

- `place_kind` はコードリスト（ADR-0010 と同じ管理）: `site` / `watershed` / `mesh3` /
  `municipality` / `town_block` / `zone` / `river_segment` / `prefecture` / `water_service_area`。
  **新しい空間単位の追加はコードリストへの1行**であり、テーブル追加ではない。
- **操作的定義は `definition_ref` で明示する。** `zone` は place の一種として地域ごとに
  定義され、閾値と出典を持つ。「公式区分ではない」がデータに載る。
- `place_relation.fraction` で部分的包含を表す（水道の町丁目→浄水場の `share` と同じ考え方。
  `water_zone_assignment` の構造をここに一般化する）。
- ジオメトリ本体は place に埋めず `geometry_ref` で外部（R2 の GeoJSON/Parquet、
  Workers の ASSETS）を指す。属性付きの面データ（植生・保護区）は `feature` として別に持ち、
  `place` は「集計軸になる単位」に限る。
- `sites.municipality` の混入は**移行時に解消する**。水域名が入っている290地点は
  `place_relation` で `within` の市区町村を別途解決し、水域名は
  `place_kind='river_reach'` 側の名前として持つ。

### 点→place の解決規約（必須）

実測では、ファクトの多くが `sites` に紐づいていない。

```
organism_records  823,692行  site_id が 全件 NULL（座標のみ）
sensor_timeseries  site_id 77種のうち 65 が sites に存在しない（横浜の河川水位ほか）
measurements       7,846行 の site_id が sites に存在しない（厚木・地盤沈下ほか）
coordinate_uncertainty_m  617,950行（75%）が NULL＝精度不明
```

したがって「主語は place」を成立させるには、**座標から place を決める規約**が
モデルの一部として必要になる。以下を規約とする。

1. **座標を持つファクトは、取り込み時に place へ解決する。** 元の座標は捨てない
   （`lat`/`lon` は observation / occurrence 側に残す）。
2. **解決の最小単位は3次メッシュ（`mesh3`）。** より細かい単位（地点）に
   勝手に丸めない。流域・行政区は `place_relation` を辿って導く。
3. **解決に使ったポリゴンの版と出典を `basis` に記録する。**
   現行は1977年版の国土数値情報 W12 で点内包判定をしている（`domain.ts` の注記）。
   この事実は caveat として残す（ADR-0013）。
4. **精度が粗い／不明な座標（`coordinate_uncertainty_m` が NULL または解決先の単位より大きい）は、
   その単位に解決しない。** 解決できない場合は `place_id=NULL` のまま通し、
   キューブの対象外にする。**推測で割り当てない。**
5. `sites` に無い観測地点は、**移行時に place として新規登録する**
   （出典側の地点台帳を place_source_ref 経由で取り込む）。地点の欠落を放置しない。

## 影響

- **良い**: 「A を含む B」「B に含まれる A」が1つのクエリで解ける。集計軸ごとの派生テーブルが
  不要になり、ADR-0011 のキューブが成立する。新しい空間単位（漁協区域、小学校区、
  奄美の集落）を足してもスキーマが変わらない。`municipality` 問題がデータとして直る。
- **コスト**: 5,089 の町丁目 + 4,083 メッシュ + 1,547 河川区間 + 377 流域 + 352 地点 ＋
  現在 `sites` に無い地点（センサー65・測定の一部）＝
  約 11,500 行の place と、それを結ぶ `place_relation` の辺（メッシュ×流域だけで数万行）を
  作る必要がある。関係の生成は空間演算（L1→L2 のビルド時に1回）。
- **注意**: 時間で変わる境界（市町村合併、町丁目の改定）に `valid_from`/`valid_to` が要る。
  2020年国勢調査の小地域と2016年の土地利用データを結ぶときは版差を意識する必要がある。

## 検討した代替案

- **現行のまま、集計軸ごとに専用テーブル**: 移行不要だが README §1(a) の増殖が続く。却下。
- **PostGIS で空間関係を都度計算する**: 前計算が不要になるが ADR-0001（サーバレス・
  ファイル配布）と両立しない。関係を**事前に辺として持つ**ことで配布可能性を優先する。却下。
- **place と feature を統合する**: エンティティが減るが、「集計軸としての場所」と
  「属性を持つ地物」は用途も更新頻度も違う（植生ポリゴン13,206行を集計軸にはしない）。却下。
