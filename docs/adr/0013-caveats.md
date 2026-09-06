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
