# ADR-0028: 座標の一般化はしない — 入力・外部ソースの値をそのまま配信する

- 状態: 承認済 / 日付: 2026-09-25
- 関連: ADR-0018（置換対象。公開範囲と座標一般化）, ADR-0001（`dist/` 生成）,
  ADR-0005（ライセンス）, ADR-0013（caveat）, ADR-0014（応答封筒）

## 背景

オーナーの決定（2026-09-25）:「座標のぼかしは無し。入力されたもしくは外部ソースから取得した
ものは全てそのまま返す」。理由は、扱うデータがすべてすでにインターネットで公開されている
ため。このプロジェクトが扱う生物出現データは GBIF・iNaturalist・環境省・国土交通省・
神奈川県オープンデータ等、公開データの統合であり、非公開の一次データを新たに公開するもの
ではない。

この決定は次を覆す。

- **要求定義 FR-4.5**「公開範囲を段階制御する（非公開／限定共有／全公開）。希少種の位置情報は
  自動的に粗い位置に丸める」（`app_description.md`）。
- **ADR-0018**「公開範囲と座標の一般化をデータとして持ち、公開経路（`dist/` 生成・API/MCP）で
  強制する」。ADR-0018 は `publication_rule`（`action: 'publish'|'generalize'|'withhold'`）を
  データとして持つ設計を決定したが、`docs/adr/status-review-2026-09-25.md` の判定時点で
  「公開経路で強制する」という決定の中核（`publication_rule` テーブル、API/MCP での強制）は
  実装されておらず、`publication_scope` 列自体は Phase A から出典側の旗としてそのまま運ばれて
  いるだけだった。実際に「一般化」を実行していた唯一の箇所は `scripts/x01_dwca.py` の
  `generalize()`（FR-4.5、レッドリスト該当種の座標を 0.1 度グリッドに丸める。実データで
  2,080 件が該当、`docs/FINAL_REPORT.md` §4）である。

## 撤去したコード

- `scripts/x01_dwca.py`: `generalize()` / `is_sensitive()` / `SENSITIVE_CODES` / `_CODE_RE` を
  削除した。`occurrence.txt` の `decimalLatitude`/`decimalLongitude` は
  `organism_records.lat`/`lon` をそのまま出す。`coordinateUncertaintyInMeters` も、
  一般化時に合成していた `10000` を使わず、原本の `coordinate_uncertainty_m` をそのまま出す。
  `informationWithheld`/`dataGeneralizations`（Darwin Core の標準語彙としては列を残すが、
  値は常に空文字列）と、統計 `stats['n_gen']` を削除した。
- `scripts/x03_verify_dwca.py`: 一般化件数のチェックを「FR-4.5 の実効性を測る」ものから
  「ADR-0028 により常に 0 であることを確認する回帰検知」に変更した。

## 見つけたが変更していないもの（棚卸し）

`scripts/`・`web/src/`・`web/scripts/` を `publication_scope`・`限定共有`・`generaliz`・
`一般化`・`round(`（緯度経度を扱う箇所）で grep した結果:

- `publication_scope` 列自体（`scripts/m03_organisms.py`、`scripts/b06_build_occurrence.py`、
  `scripts/schema_app.sql`、`web/src/db/schema.ts`、`scripts/m99_validate.py` の集計、各種テスト
  フィクスチャ）は出典側の旗をそのまま運ぶだけで、これを根拠に出力を絞る・フィルタする処理は
  どこにも無い。この決定の「`publication_scope` の列は、出典の旗としてデータには残してよいが、
  出力を絞る根拠にはしない」に既に合致しているため、これらは変更していない。
- `scripts/c3*.py`・`scripts/c8*.py`・`scripts/m01_sites.py`・`scripts/process_biodic_mesh_vg.py`
  等の `round(lat, ...)`/`round(lon, ...)` は、重複排除キーの生成やメッシュ中心座標の算出
  （小数点以下の精度の切り詰めであり、秘匿目的の一般化ではない）で、公開範囲による出し分けとは
  無関係なため変更していない。
- `web/src/`・`web/scripts/` 側に座標を丸める・伏せる・`publication_scope` で絞るコードは
  見つからなかった（`web/src/db/schema.ts` の `publicationScope` 列定義のみで、読み出し側での
  使用箇所は無い）。
- ADR-0014（応答封筒、`docs/adr/0014-response-envelope.md:78`）の `get_occurrences` ツール仕様
  に「ライセンス区分・公開範囲で絞れる」という記述があるが、これは未実装のツール仕様
  （ADR-0014 自体が `提案中`。`get_observations` 相当の実装が無いことは
  `docs/adr/status-review-2026-09-25.md` が確認済み）であり、コードは存在しない。ADR-0018 と
  異なりこの ADR-0028 が直接覆す決定ではないため本文は書き換えていないが、実装時はこの決定
  （公開範囲でフィルタしない）に従うべき既知の食い違いとしてここに記録する。
- `docs/REBUILD.md`「座標一般化（FR-4.5）件数 | 27 | 2,080」の行、`docs/FINAL_REPORT.md` §4
  「FR-4.5（希少種位置一般化）検証結果」は、いずれも実行日時点のスナップショット（歴史的記録）
  であり、`docs/adr/status-review-2026-09-25.md` と同じ理由で書き換えない。

## 決定

1. 座標・位置情報について、公開範囲（`publication_scope`）や分類群のレッドリスト該当性による
   一般化・秘匿・出し分けを行わない。入力された値、または外部ソースから取得した値を、配信経路
   （API・MCP・DwC-A の出力・D1）でそのまま返す。
2. `publication_scope` 列は、出典側の旗（どのレコードがレッドリスト該当種由来か等のメタデータ）
   としてデータに残してよい。ただしこの列を根拠に「出力する/しない」「丸める/丸めない」を
   判定するコードを書かない。
3. ADR-0018 が提案した「公開経路での強制」の仕組み（`publication_rule` テーブル、
   `action='generalize'|'withhold'`）は導入しない。

## 影響

- **良い**: 座標一般化のバグ（当初は判定の不備で `n_gen` が常に 0 だった、後に「学名結合
  できない動物レッドリスト種は検出されない」という既知の限界が残った、`docs/FINAL_REPORT.md`
  §4）自体が意味を失う——一般化しないので判定の正しさを保守する必要が無くなる。DwC-A・API・
  MCP の出力が「その場しのぎの一般化ロジックの不備で一部だけ粗い」という一貫性の問題からも
  解放される。
- **コスト**: 将来、非公開の一次データや盗掘・密猟リスクの高い新しい出典を扱うようになった
  場合、この決定は再度見直しが必要になる。
- **リスク**: 希少種の正確な位置が第三者にそのまま渡る。オーナー判断により、扱うデータは
  既にインターネット上で公開されているため実質的なリスク増加は無いとみなす。

## 検討した代替案

- **ADR-0018 の設計（`publication_rule` を作り込む）をそのまま実装する**: 却下。今回のオーナー
  判断が「一般化自体をしない」であるため、ルールエンジンを作る意味が無い。
- **`publication_scope` 列そのものを削除する**: 却下。旗としての情報的価値（どのレコードが
  レッドリスト該当種由来か）は残る方が、将来の別の判断・分析に使える。「出力を絞る根拠にしない
  こと」と「データとして持つこと」は両立する。
