# ADR-0014: データインターフェースの共通レスポンス封筒と MCP ツール群

- 状態: 提案中 / 日付: 2026-09-06
- 関連: ADR-0005（ライセンス）, ADR-0008（時間）, ADR-0009（検閲）, ADR-0011（キューブ）, ADR-0013（caveat）

## 背景

現行の API は画面ごとに生えている（`/api/timeseries` `/api/biota` `/api/nature?kind=`
`/api/quality` `/api/geo/*` `/api/column` `/api/table` …）。任意 SQL の `/api/sql` と
全表スキャンの `/api/table` `/api/schema` は `EXPLORE_ENABLED=false` で閉じている
（公開 URL に任意 SQL を出さないため）。

MCP を出すにあたり、この構成には2つの問題がある。

1. **画面のためのエンドポイントは、外部利用者の問いに答える形になっていない。**
   ADR-0011 でキューブに統合するなら、インターフェースも軸で問う形にすべき。
2. **応答が裸のデータで、読み方が付いていない。** 単位・時間粒度・検閲・ライセンス・
   注意事項はすべて `domain.ts` 側にあり、応答に含まれない。

## 決定

### (1) 共通レスポンス封筒

**すべての読み取り応答が同じ封筒を持つ。データだけを返さない。**

```jsonc
{
  "query":    { /* 受け取った条件のエコー。既定値も明示 */ },
  "columns":  [ { "name":"value", "type":"number", "unit":"mg/L", "ucum":"mg/L" } ],
  "rows":     [ /* ... */ ],
  "coverage": { "n_rows": 1240, "n_places": 32, "n_censored": 291,
                "period": {"start":"2015-04-01","end":"2024-03-31","grain":"fiscal_year"},
                "imputation": "half_lod" },
  "provenance": [ { "source_edition_id":"...", "name":"...", "publisher":"...",
                    "fetched_at":"2026-08-29", "license":"CC-BY-4.0",
                    "attribution":"...", "n_rows": 1240 } ],
  "excluded":  { "by_license": 412, "by_embargo": 0, "reasons": ["noncommercial"] },
  "caveats":  [ { "severity":"blocking", "kind":"time_series_break",
                  "title_ja":"...", "quote":"...", "scope":"..." } ],
  "truncated": false,
  "spec_version": "2026-09-06",
  "cite_as": "..."
}
```

守る規則:

- **単位なしの数値を返さない。** `columns` に単位が無い数値列を作らない。
- **時間は必ず `period_start`/`period_end`/`grain` の3点セット**（ADR-0008）。`year: 2015` を返さない。
- **検閲行は `value=null` + `censoring`**（ADR-0009）。0 を返さない。
- **`provenance` と `caveats` は省略不可。** 空配列は「無い」の意味で、省略とは区別する。
- **除外したものは件数と理由を返す**（ライセンス・隔離。ADR-0005）。黙って減らさない。
- **打ち切りは `truncated` で明示する。** 静かに切らない。

### (2) MCP ツール（10本）

**第1段（これだけで公開できる5本）**

| ツール | 用途 |
|---|---|
| `describe_catalog` | 何があるか。地域・テーマ・出典・期間・件数の概観。**入口** |
| `search_registry` | 指標・場所・分類群を横断で探す/解決する（種別で絞れる） |
| `get_observations` | **主軸**。指標×場所×分類群×期間×粒度×統計量でキューブを引く |
| `get_occurrences` | 生物出現レコード（ライセンス区分・公開範囲で絞れる） |
| `export_dataset` | 条件に合うデータの Parquet/CSV の URL とデータパッケージ記述子を返す |

**第2段（需要を見て足す）**

| ツール | 用途 |
|---|---|
| `get_geometry` | place / feature のジオメトリ（GeoJSON、簡略化度を指定可） |
| `get_provenance` | ある行/集計の出典・版・原文（文書のページ・セル）まで辿る |
| `get_caveats` | 指標/場所/出典に紐づく注意事項（第1段では封筒に同梱されるので必須ではない） |

第1段を5本に絞るのは、ツールが多いほど LLM の選択が散り、
実装・テスト・ドキュメントの初期コストが上がるため。`search_registry` は
`search_variables` / `search_places` / `search_taxa` を `kind` パラメータで束ねたもの。

- **任意 SQL は MCP に出さない。** 軸で問う形に閉じる（安全性と、キューブの
  事前計算前提を守るため）。分析者向けには `export_dataset` から Parquet を落として
  DuckDB で自由に触れる経路を用意する（ADR-0001）。
- **Web アプリは同じ「モデルと語彙」を使うが、同じ HTTP 経路は強制しない。**
  保証したいのは「MCP で取れないものは画面にも出ていない」であって、
  同一エンドポイントの共用ではない。毎応答に provenance と caveats を載せると
  D1 の rows_read が増え、`features.ts` が探索機能を閉じた理由（課金）と衝突する。
  **例外として明示するもの**: ジオメトリ・タイル配信（現行どおり静的アセット直読み）、
  サーバコンポーネントからの直接クエリ。これらも語彙とレジストリは共有する。
- ツールの説明文（MCP の description）に**読み方の規則**を書く。
  LLM が検閲・年度・ライセンスの扱いを誤らないようにするのはツール定義の責務とする。

## 影響

- **良い**: 応答だけで正しく読める（合格条件3）。画面と MCP と外部利用者が同じものを見る。
  エンドポイントがデータ種類に比例して増えなくなる。
- **コスト**: 応答が重くなる（provenance と caveats の解決コスト）。
  現行の画面別 API をすべて置き換える移行が必要。
- **注意**: `get_observations` の表現力が不足すると画面が作れず、逆に強すぎると
  任意 SQL と変わらなくなる。**現行の全画面がこのツールだけで作れるか**を
  移行の受け入れ条件にする。

## 検討した代替案

- **GraphQL を出す**: 表現力は高いが、キューブの事前計算前提と噛み合わず、
  LLM から使うには冗長。却下。
- **`/api/sql` を公開して自由に問わせる**: 最も柔軟だが、公開 URL に任意 SQL と
  全表スキャンを出す判断は既に否とされている（`web/src/lib/features.ts`）。却下。
- **MCP をデータではなく画面の要約に対して出す**: 実装は軽いが、
  「データを再利用可能にする」目的に反する。却下。
