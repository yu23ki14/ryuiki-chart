# ADR-0023: 単位の正準化は取り込み時に潰さず、レジストリの換算係数とキューブの軸に分けて持つ

- 状態: 提案中 / 日付: 2026-09-15
- 関連: ADR-0007（observation）, ADR-0010（指標）, ADR-0011（キューブ）, ADR-0021（キューブの鍵）,
  `docs/plans/PHASE_B_INTAKE.md` 申し送り #5

## 背景（実測）

`data/db/registry.sqlite` の `variable_alias` を実測すると、同じ `variable_id` が出典によって
異なる `unit_id` で届く変数が**8つ**ある（`GROUP BY variable_id HAVING COUNT(DISTINCT unit_id) > 1`
で実測。2026-09-15）。

| variable_id | unit_id の組 | 倍率 | 非正準側の出典 | 正準側の出典 |
|---|---|---:|---|---|
| `weather.air_temp` | `degc` / `0_1degc` | ×10 | `hiratsuka_taiki` | `jma_daily_yokohama`/`jma_monthly_kanagawa` |
| `weather.humidity` | `percent` / `0_1percent` | ×10 | `hiratsuka_taiki` | 同上 |
| `weather.precipitation` | `mm` / `0_1mm` | ×10 | `hiratsuka_taiki` | 同上 |
| `weather.wind_speed_mean` | `m_per_s` / `0_1m_per_s` | ×10 | `hiratsuka_taiki` | 同上 |
| `air.no2` | `ppm` / `ppb` | ×1000 | `hiratsuka_taiki`（`ppb`） | `soramame_hourly_kanagawa`（`ppm`） |
| `air.photochemical_oxidant` | `ppm` / `ppb` | ×1000 | 同上 | 同上 |
| `air.so2` | `ppm` / `ppb` | ×1000 | 同上 | 同上 |
| `air.spm` | `mg_per_m3` / `ug_per_m3` | ×1000 | `hiratsuka_taiki`（`ug_per_m3`） | `soramame_hourly_kanagawa`（`mg_per_m3`） |

**非正準側（×10・×1000のどちらも）は全部 `hiratsuka_taiki` 由来**（実測。`sagamihara_taiki_hourly`
の `OX`/`RAIN` は単位が読み取れず `unit_id=NULL` のまま——`docs/plans/PHASE_B_INTAKE.md` 申し送り
#5 が「推測しない」と決めた対象で、本 ADR が扱う「単位は分かっているが出典間でスケールが違う」
ケースとは別の問題）。

ADR-0021 はキューブの次元キーに `unit_id` を持つので、**1セルに単位の違う値が混ざることは無い**
（構造的に安全）。危ういのは、キューブを読む消費者側（チャート・地点間の比較・複数出典をまたぐ
平均）が `unit_id` の違う複数セルを同じ尺度として並べてしまうこと——`hiratsuka_taiki` の気温と
`jma_daily_yokohama` の気温は、換算せずに並べると値が10倍ずれる。

### 換算の往復誤差（実測。`data/db/v2.sqlite` の `observation.value_num` を対象）

`hiratsuka_taiki` の×10系列4本（気温・湿度・雨量・風速の日平均、`n=18,346〜18,725`/系列）について、
`value_num / 10.0 * 10.0`（正準単位に換算してから出典単位に戻す）が元の IEEE754 double と
一致するかを検証すると、**17.1%〜20.0%が元の値に戻らない**（気温17.1%・雨量17.2%・湿度20.0%・
風速18.4%。丸め誤差の蓄積で `/10.0*10.0 != 元の値` になる行の比率）。一方、`ppb`/`ug_per_m3` 側の
×1000系列4本（NO2・Ox・SO2・SPM、`n=18,913〜23,731`/系列）で同じ手法（`/1000.0*1000.0`）を試すと
不一致は **0.01%〜0.29%** と、×10系列よりはるかに小さい（2026-09-15実測。手法：Python の
`sqlite3` で `observation` を読み取り専用で開き、変数ごとに `value_num` 全件を走査）。

→ **取り込み時に正準単位へ換算すると、元の出典値の一部がビット単位で再現できなくなる。**
ADR-0016 の受け入れ基準（`imputation='zero'` で v1 の値を誤差0で再現する）とは両立しない。

## 決定（4つ）

### 1. 出典単位のまま v1 を再現する（実施済み）

`observation.value_num`/`unit_id` は常に出典が報告した実際のスケールを保持する。センサーの縦線
（`sensor_daily`/`rain_daily`/`sensor_hour_month`。`docs/plans/PHASE_B_FACT_SLICE.md` §9）は
この方針のまま実装済みで、`b02_derived_compare.py` の突合（誤差許容0）が通っている。

### 2. 換算係数は `variable_alias`（alias）ではなく `unit` レジストリに持たせる

`0.1℃→℃` や `ppb→ppm` は「特定の出典の系列（alias）」の性質ではなく「**単位そのものの性質**」
である。申し送り #5 が最初に挙げた「alias に `scale_to_canonical` のような列を持たせる」案は、
実測すると同じ換算係数（×10 または ×1000）が変数をまたいで重複する（weather 系4本はすべて
×10、air 系4本はすべて ×1000）ことが分かり、単位ペアが持つ性質を alias 側に複製することになる。
`unit` テーブルに `canonical_unit_id` / `scale_to_canonical`（今回の8変数はすべて線形換算で
オフセット無しだが、将来のためのオフセット列も併設）を持たせれば、同じ `unit_id` を使う全 alias
が1箇所の宣言を共有できる。

### 3. キューブに「出典単位 / 正準単位」の軸を `imputation` と同じ形で並存させる

`observation_agg` の次元キーに正準化の有無を表す軸を足し、出典単位のセルと正準単位のセルを両方
持つ（`imputation ∈ {zero, lod}` を両方持つのと同じ考え方）。v1 の射影（`b05`）は出典単位側の
セルを使う（現状のまま。挙動は変えない）。

### 4. 実装は「キューブを読む最初の消費者」より前の別 PR

本 ADR は方針決定であり、2026-09-15 時点でコード化されていない（`docs/plans/PHASE_B_INTAKE.md`
申し送り #5 参照）。センサーの縦線（v1 互換の射影）はこの決定の影響を受けない。正準単位の軸が
無くても既存の受け入れ基準は満たせるため、複数出典を横断して比較する最初の消費者（新しい API・
チャート等）が現れる前に実装すればよい。

## 影響

- **良い**: v1 の再現性を保ったまま、将来「気温を複数地点で比較する」ような消費者が正準単位側の
  セルを安全に使える。換算ロジックが `unit` レジストリ1箇所に集約され、alias が増えても重複しない。
- **コスト**: `unit` テーブルに `canonical_unit_id`/`scale_to_canonical`（必要ならオフセット）の
  列が増える。`observation_agg` の次元キーが1列増え、セル数が出典単位側・正準単位側の分だけ増える。
- **注意**: 8変数のうち×10系列は丸め誤差が大きい（往復不一致17.1%〜20.0%）。正準単位側のセルを
  作った後も、出典単位側のセル（v1 互換）は温存し続ける必要がある——「正準化したから出典単位を
  捨ててよい」という設計にはできない。

## 検討した代替案（却下理由）

- **取り込み時（`b03`）に正準単位へ換算する**: 背景の往復誤差（17.1%〜20.0%）のため、ADR-0016 の
  「誤差許容0」で v1 を再現するゲートと両立しない。`observation` 自体が「出典が実際に報告した値」
  でなくなり、ADR-0007 の「原表記を残す」（`unit_raw` 列）の精神にも反する。却下。
- **応答の境界（ADR-0014 のレスポンス封筒）だけで換算する**: ADR-0011 が「事前計算しなかった軸は
  `dist/` の Parquet への DuckDB 直クエリに任せる」と決めており、その経路の利用者は応答封筒を経由
  しないため換算済みの値を得られない。境界だけでは不十分で、データ自体（キューブ）に正準単位の
  セルを持たせる必要がある。却下。
- **alias に `scale_to_canonical` を持たせる（申し送り #5 の原案）**: 決定2のとおり、単位ペアの
  性質を alias 側に複製することになり重複が生じる。却下、`unit` レジストリに変更。
