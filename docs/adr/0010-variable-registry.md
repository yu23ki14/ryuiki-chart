# ADR-0010: 指標レジストリを設け、出典別名をエイリアスで束ねる

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0002（多地域）, ADR-0007（observation）, ADR-0012（マニフェスト）

## 背景（実測）

同じ物理量が出典ごとに別の名前で入っており、名前に単位と集計粒度が埋まっている。

```
sensor_timeseries.datastream:
  OX / Ox(ppm) / 光化学オキシダント_日平均            <- 同じ量が3つの名前
  SPM(mg/m3) / 浮遊粒子状物質（SPM）_日平均          <- 名前に単位と粒度
  河川水位_日最高 / 河川水位_日平均                   <- 名前に統計量

measurements.variable: 58種
  323,164行のうち 109,078行（34%）が unit なし
  「流量関連（公式定義未確認のため原表記のまま）」のような未解決の項目名が混ざる

source_registry.category: 124行に対し 74種の自由記述
  'gis_river' と '河川'、'水質' と '河川水質' が併存
```

指標の意味（何を測っているか・上がると良いのか悪いのか・単位は何か）は
`web/src/lib/domain.ts` の `VARIABLE_SHORT` / `VARIABLE_NOTE` / `HIGHER_IS_WORSE` /
`VARIABLE_UNIT_FALLBACK` に手書きされており、`derived.var_catalog`（58行）は
実データから数えた統計だけを持つ。**どちらもデータの正準な語彙ではない。**

## 決定

**`variable` レジストリを設け、観測はレジストリの ID を参照する。出典側の表記は
`variable_alias` の行として束ねる。**

```
variable        variable_id, region_scope, code, name_ja, name_en,
                theme, unit_id, value_type ('num'|'text'|'bool'|'category'),
                default_stat, higher_is_worse, description_ja, description_en,
                standard_refs (dwc/eMoF/STA への対応), status
variable_alias  alias, source_edition_id, variable_id, unit_id, stat, grain, note
unit            unit_id, symbol, ucum, name_ja, quantity_kind
```

1. **エイリアスは「出典 × 表記」で解決する。** 同じ `Ox` でも出典が違えば単位が違いうるので、
   `variable_alias` は `source_edition_id` を持つ。マッピングはマニフェスト（ADR-0012）に書く。
2. **名前から単位・粒度・統計量を剥がす。** `河川水位_日平均` は
   `variable=river_stage, unit=m, grain=day, stat=mean` に分解して登録する。
3. **単位は UCUM を正、日本語表記を別に持つ。** 単位不明（34%）は `unit_id=NULL` のまま
   放置せず、`status='needs_review'` として**未解決であることを可視化する**。推測で埋めない。
4. **`region_scope` は既定で `common`。** 指標レジストリの ID に地域を埋めない（ADR-0004 規約0）。
   地域固有の指標（その地域の条例・調査でしか使われない項目）だけ地域スコープにする。
   「2地域で使われたら昇格」という運用は**しない** — 昇格は ID の変更を意味し、
   ID 不変の規約に反するため。判断に迷うものは `common` に置く。
5. **`theme`** はコードリスト（水質 / 水文 / 大気 / 気象 / 生物 / 植生 / 土地利用 / 保護区 /
   社会経済 …）。`source_registry.category` の74種の自由記述をここに解決し、
   DCAT のテーマにも射影する（ADR-0003）。
6. `higher_is_worse` / `description` は**データとして**持つ。`domain.ts` の該当部分は廃止し、
   画面はレジストリを読む。

## 影響

- **良い**: 出典をまたいだ同一指標の比較ができる。単位の欠落が「レジストリ未登録」として
  検出可能になる（今は静かに NULL）。MCP が `list_variables` だけで語彙を説明できる。
  画面と MCP が同じ語彙を見る。
- **コスト**: 58種＋センサー系＋Tier1 の指標を人手で棚卸しして登録する初期作業が要る。
  未解決の指標が可視化されるため、当面 `needs_review` が並ぶ（これは良いこと）。
- **注意**: エイリアス解決を強制すると、未登録の指標を持つソースが取り込めなくなる。
  **未登録は取り込みを止めるのではなく `variable_id=NULL, alias_raw` で通し、
  `needs_review` として一覧に出す**（データを落とさない）。

## 検討した代替案

- **`domain.ts` を拡充する**: 実装は最小だが、MCP・外部利用者から読めない。本 ADR の動機に反する。却下。
- **文字列の指標名をそのまま使い、正規化しない**: 取り込みは楽だが、
  `OX`/`Ox(ppm)`/`光化学オキシダント_日平均` が別物として集計され続ける。却下。
- **国際的な語彙（NERC/BODC のような）に完全準拠する**: 相互運用は最大だが、
  日本の行政指標に対応語が無いものが多く、対応付けの手間が大きい。
  `standard_refs` で参照だけ持ち、正準は自前に置く（ADR-0003 と同じ判断）。却下。
