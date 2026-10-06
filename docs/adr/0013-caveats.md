# ADR-0013: 注意事項（caveat）を一級エンティティにし、応答に必ず同梱する

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0009（検閲）, ADR-0010（指標）, ADR-0014（応答）

## 背景

このデータには「知らないと誤読する」事実が多数ある。現在それらは3か所に散っている。

1. **`web/src/lib/domain.ts` の `DATA_CAVEATS`**（アプリのコード）
   - 日付形式の混在、定量下限の 0 潰し、同一地点・日・項目の重複
2. **`cells.notes`（207行）**（データ）
   - 行政文書の表に付随する注記。**「時系列比較を阻害する注記」のフラグを持っている**。
     これは既にこのプロジェクトが「注記は一級の情報」と気づいていた証拠。
3. **各種ドキュメント**（`docs/ZONE_DEFINITION.md`、`docs/SYNTHETIC_DATA.md`、
   `docs/COLLECTOR_CONTRACT.md` の隔離記録）

`domain.ts` の注記は**画面にしか出ない**。MCP クライアント、API 利用者、Parquet を
落とした第三者は誰も読めない。公開パイプラインを名乗る以上、これは欠陥である。

## 決定

**`caveat` をコアのエンティティにし、対象に紐づけて持つ。API/MCP の応答は
関係する caveat を必ず同梱する。**

```
caveat
  caveat_id, region_id,
  scope_kind,     -- 'variable'|'place'|'source_edition'|'observation_set'|'dataset'|'taxon'
  scope_ref,      -- 対象の ID（範囲指定も可: variable × place × 期間）
  severity,       -- 'blocking'（この注記を無視した比較は誤り）|'warning'|'info'
  kind,           -- 'time_series_break'|'unit_change'|'method_change'|'definition_change'
                  -- |'censoring'|'coverage_gap'|'synthetic'|'embargo'|'known_error'
  title_ja, title_en, body_ja, body_en,
  quote,          -- 原文引用（要約しない。収集規約の禁止事項）
  source_edition_id, period_start, period_end
```

1. **`severity='blocking'` の caveat が付く範囲をまたぐ集計は、応答で明示的に警告する。**
   `cells.notes` の「時系列比較を阻害する注記」フラグをこれに一般化する。
2. **原文は引用のみ。要約しない**（`docs/COLLECTOR_CONTRACT.md` の禁止事項に従う）。
   要約が要る場合は `title` を別に付け、`quote` は原文のまま残す。
3. `domain.ts` の `DATA_CAVEATS` / `VARIABLE_NOTE` / `MUNICIPALITY_LABEL` の
   説明部分は caveat と `variable` レジストリに移し、`domain.ts` は廃止する。
4. **合成データ（`is_synthetic=1`）は caveat の一種**として扱う（`kind='synthetic'`）。
   隔離中の出典（`redistributable=0`）も `kind='embargo'` で表す（ADR-0005）。
5. caveat は**データの欠陥ではなく仕様**として管理する。新しい癖を見つけたら
   コードに if を書かず caveat を足す。

## 影響

- **良い**: 「知らないと誤読する」情報が、画面・API・MCP・Parquet 配布のすべてに
  同じ形で載る。LLM が読んだときに注意事項を無視できない構造になる。
  新しい癖の発見が、コード変更ではなくデータ追加になる。
- **コスト**: 応答が重くなる（毎回 caveat が付く）。`scope_ref` の範囲指定
  （指標×場所×期間）の解決に手間がかかる。多言語（ja/en）の維持。
- **リスク**: caveat が増えすぎると誰も読まなくなる。`severity` を厳格に運用し、
  `blocking` は「これを無視した比較は誤り」に限定する。

## 検討した代替案

- **ドキュメントに書いて済ませる（現行）**: コストゼロだが、機械が読めない。却下。
- **データの値そのものを補正して caveat を不要にする**: 利用は楽だが、
  「推測で埋めない」に反し、補正の妥当性を利用者が検証できなくなる。
  補正が正しいと確信できるものだけ ADR-0009 のように**構造で**解決し、
  残りは caveat で伝える。部分的に採用。
- **注記をすべて `variable` の説明文に畳む**: 単純だが、場所固有・期間固有の注記
  （この地点は2018年に測定法が変わった）が表せない。却下。


## 追記（2026-10-06、Issue #35）: severity/kind の判定基準・scope の語彙・レビュー結果

状態: 実装済み。レビューは**オーナー委任で claude が行った**（各注記の `review.reviewer` は
「claude（オーナー委任）」）。**2026-10-07 オーナー確認済み**（全18件の severity/kind を変更なしで確定。
各 `review.owner_confirmed_on: '2026-10-07'`、`build_caveat` の検査が必須項目として要求する）。設計・実測の根拠は
`docs/plans/ISSUE35_CAVEAT.md`。

### severity の判定基準

「本文に禁止表現があるか」で機械的に決めない（Phase A の機械分類は `landuseDefinitionChange` の
blocking を漏らした）。**数値・系列に実際に効く範囲**で決める。

- **blocking**: その注記を無視して比較・集計・解釈すると**結論が誤る**もの。
- **warning**: 無視すると誤解釈しうるが、比較そのものが無効になるわけではないもの
  （値の出自・割り当ての推定・誤読しやすい癖）。
- **info**: 処理規則や由来の説明。知っておくと良いが、無視しても数値の解釈は変わらないもの。
- 同じ危険を2つの blocking が重複して述べない（`effort` が危険の本体で、`share` は方法の説明なので warning）。
  blocking が増えすぎて読まれなくなるリスク（上の「リスク」）への対処。

### kind の判定基準

`kind` は危険の**性質**を表す。enum は「版・時間・方法をまたぐ変化」が中心なので、単一時点の
加工規則や出自の説明（日平均化・分類補完・分類規則・列名と中身の不一致）には付けず、
**null を「該当なし」という判断として許す**（無理に当てはめると誤分類）。
`unitUnknown` は出典間の単位差なので `unit_change`。`cells.notes` 由来の `footnote`/`comparability`/
`survey_scope`（127件）は enum 外のまま原本の値を残していたが、**enum に3値を追記して正式化**する
（行ごとに丸めない）。cells.notes の severity は原本の `blocks_timeseries` フラグ（人が付けた区分）で、機械分類ではない。

### レビュー結果（17件＋新規1件）

blocking は9件のまま（`share` が warning に下がり、`landuseDefinitionChange` が blocking に上がった）。
warning は `organismSite`・`share`・`flowTidalBackflow`（新規）、info は `measuredOn`・`duplicates`・`zone`・
`inatBackfill`・`fishClass`・`municipality`。severity が null の注記は無くなった。
本文は実データと突き合わせ、次の4件の数値を直した（根拠の実測は設計書 §1）: `measuredOn`（件数が古い）・
`effort`（「記録した人の数」は記録者列が大半 NULL で裏付けられない）・`gbifCutoff`（8,750 は2024年1月の件数）・
`inatBackfill`（「96%解決」は再現できない）。`organismSite` には流域に割り当てられない記録が約10%ある事実を足し、
`synthetic` の本文は現在の D1 に実在する範囲に縮めた。変えた項目は各注記の `review.changed` に残してある。

### scope の語彙（`caveat_scope.scope_kind`）

`scope_kind` は本 ADR の6種（variable/place/source_edition/observation_set/dataset/taxon）に寄せた。
`scope_ref` は **ID そのもの、または `キー=値`（`&` 連結）の選択式**（「範囲指定も可」の具体化）。
照合は文字列の完全一致で、選択式は実行時に解釈しない。選択式のキーは kind ごとに許すものだけを宣言する。

| 旧 | 新 |
|---|---|
| `table:sites`（配信表） | `dataset:sites`（配信表は dataset として扱う） |
| `table_prefix` | 廃止（行が無かった） |
| `place_kind:X` | `place:place_kind=X` |
| `source_id:X` | `source_edition:source_id=X`（版を特定できないので出典 ID の選択式） |
| `variable_theme:X` | `variable:theme=X` |
| `dataset:synthetic`（実在しない値） | `observation_set:is_synthetic=1` |
| `variable:<id>`（unitUnknown） | `observation_set:variable=<id>&unit_id=null`（「その変数かつ単位が付かない系列」） |
| `cell:<doc_id>` | `source_edition:doc_id=<doc_id>`（行政文書 = 出典の版） |
| `cell_table:<doc>#<t>` | `observation_set:doc_table=<doc>#<t>`（文書内の表 = 観測値の集合） |

宣言の正は `registry/caveat_scope.yaml`（以前は `scripts/registry/build_caveat.py` の Python 定数）。
`build_caveat.py` は読んで検査するだけ。検査: kind が語彙内／注記キーが `caveat.yaml` に存在／選択式のキーが許可内／
`variable:` の ID と `theme=` が `variable.yaml` に存在／(kind, ref, caveat) の重複なし／全注記が scope か `unscoped` に載る
／全注記に完全な `review`。`scripts/tests/test_registry_caveat.py` が、わざと壊すと止まることを固定している。

効く範囲に合わせて scope を直したもの: `aboveLod` を `measurements` 全体から `variable:water.transparency` に
（26行すべて透明度）、`share` を `dataset:organism_records` から `place:place_kind=grid01` のみに
（流域の表は割合を持たず生の件数）。流量の感潮域の逆流（4,668行中180行・83地点中14地点）は
`variable:common:variable:hydro.flow` の独立した注記 `flowTidalBackflow` にし、`variable.yaml` の
`description_ja` への埋め込みを外した（画面の変数説明は `variableNote()` が注記を添える）。
`landuseDefinitionChange` は本文が名指しするのは3区分（幹線交通用地・道路・鉄道）だけだが、他の10区分は
日本語名が一致するだけで定義の一致を確認できていないので、推測で狭めず `theme=landuse` 全体のままにしてある。
