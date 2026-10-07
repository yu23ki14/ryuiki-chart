# ADR-0001: 原本を Parquet に置き、D1 は再構築可能な配信キャッシュとする

- 状態: 承認済（一部未実装: R2 への `dist/` 配信。2026-10-08 オーナー承認。`dist/` の書き手・検査は Phase D で実装〔`scripts/d01_build_dist.py`・`scripts/d02_check_dist.py`〕） / 日付: 2026-09-06
- 関連: ADR-0005（版・ライセンス）, ADR-0011（キューブ）, ADR-0012（マニフェスト）, ADR-0018（公開範囲。ADR-0028 で置換済み）
- 改定: 2026-10-06 Issue #40 Phase D（末尾の「改定（Phase D）」。`core/` と `dist/` の分離を撤回し `dist/` のみ。書き手は pyarrow）

## 背景

現行は Cloudflare D1 が事実上の原本で、61テーブルを直接持っている。ここから以下が起きている。

- D1 の制約が設計を縛る。1クエリのバインドパラメータ100個上限のために `queryChunked` という
  回避層が必要になり、`wrangler d1 export` は大きいテーブルで OOM するため独自の
  `db:export` を書いている（`CLAUDE.md`）。
- 第三者がデータを丸ごと再利用する経路がない。DwC-A（生物のみ）を除けば、データを得るには
  この Web アプリの API を叩くしかない。**公開パイプラインを謳う以上これは不足**。
- 「D1 のこの行が正しいのか」を確かめる基準がない。原本が可変なストアの中にある。

一方、収集側は既に `data/raw/` （不変）→ `data/processed/*.{csv,jsonl}` という素直な
ファイル系の流れを持っており、SQLite はその後段に付いている。

## 決定

**L2（正準モデル）の Parquet を原本とし、D1 は L3 を流し込んだ配信キャッシュとする。**

```
L0  raw          data/raw/<source_id>/                     取得したまま・ハッシュ付き・不変
L1  staging      data/processed/<source_id>.{csv,jsonl}    ソース別に正規化（現行維持）
L2  canonical    dist/*.parquet     出典単位のパーティション・全件   <- 配布する（改定: core/ は撤回。末尾参照）
L3  serving      cube/*.parquet + D1                       集計キューブ・ジオ束
```

- **D1 はいつ捨てて作り直してもよい。** L2 から L3 が決定的に再生成できることを CI で担保する。
- ~~L2 は `core/`（内部・全件）と `dist/`（公開・行フィルタ済み）に分ける。~~ **（撤回。末尾「改定（Phase D）」）**
  当初の決定: `core/` は再配布不可・隔離中の版も保持し、`dist/` はライセンス条件でフィルタした派生物とする。
- 配布は R2 上の `dist/` Parquet ＋ Frictionless Data Package の記述子。利用者は
  DuckDB で直接読める（`SELECT * FROM 'https://.../observation.parquet'`）。
- L1→L2、L2→L3 は再実行可能かつ冪等。入力ハッシュが同じなら出力も同じ。

## 影響

- **良い**: D1 の制約が「配信の都合」に閉じ、モデリングから切り離される。第三者がフル
  データセットを落として分析できる。数値の再現性が「どの Parquet か」で言えるようになる。
- **コスト**: ビルド段が二層になる。Parquet を書く依存（DuckDB / pyarrow）が増える。
  D1 への投入は引き続き .sql 経由の一括投入になる（`wrangler d1 execute --remote --file`）。
- **運用**: 「D1 が壊れたら作り直す」が正式手順になり、D1 上の手作業修正は禁止になる。
  現在 `DEPLOYMENT.md` にあるアセットのハッシュ重複排除回避策と同じ思想。
- **リスク**: 一度公開した Parquet の撤回は難しい（Cloudflare のアセットは内容ハッシュで
  重複排除される。`DEPLOYMENT.md`）。`core/`→`dist/` のフィルタが誤ると再流出になるため、
  フィルタは CI の必須チェックにし、撤回手順を別 ADR（takedown）で定める。

## 検討した代替案

- **D1 を原本のまま拡張する**: 移行は最小だが、上記の制約と配布の問題が残る。データ種類が
  増えるほど不利になり、今回の目的（公開パイプライン）に正面から反する。却下。
- **PostgreSQL/PostGIS を原本にする**: 空間演算は強くなるが、運用主体（シビックテック）に
  常時稼働の DB を持たせる負担が増え、「落として使える」性質を失う。却下。
- **原本を SQLite ファイルのまま配布する**: 現行の延長で移行は楽。ただし列指向でないため
  大きいファクトの部分読み出しが効かず、スキーマ進化の扱いも弱い。却下。

## 改定（Phase D、2026-10-06、Issue #40）

1. **`core/` と `dist/` の分離を撤回し、`dist/` のみにする。** 分離の唯一の理由は「再配布不可・隔離中の版を
   `dist/` から除く」ことだったが、ADR-0028 とオーナー決定により `redistributable`/`license_class` は
   出力を絞る根拠にしない（扱うデータは全て公開済み）。`core/` を作ると `dist/` と同一内容の複製になる。
   合成データは v2 に入らない（b03/b06 が除外）ので、`dist/` との差分も無い。
   **`core/` を再導入する条件**: 出力を絞る根拠が復活したとき（非公開データの取り込み）。その時は
   `dist/` を `core/` から決定的に導く派生物として戻し、フィルタを CI の必須チェックにする。
2. 本文中の「ライセンス条件でフィルタ済みの `dist/`」「行フィルタ済み」は撤回する。`dist/` は全件で、
   各版の `license_id`/`license_class`/`redistributable`/`attribution` を `datapackage.json` の `sources[]` に
   **情報として**載せる。写像漏れ（`unknown`）・未確認（`unconfirmed`）の件数も出す（黙って埋めない）。
   例外は合成データだけで、書き手（`scripts/d01_build_dist.py`）は v2 に合成行が居たら除かず**落とす**。
3. **書き手は pyarrow**（`requirements.txt` に版を固定。`duckdb` は入れない。DuckDB は利用者側の読み出し例として
   `dist/README.md` に書くだけ）。理由: DuckDB で SQLite を読むには拡張を初回にネットから取得する
   （CI・オフラインで不安定）。CSV 経由は NULL・型・改行の取り違えの温床。
4. **出典単位のパーティション**: `observation/source_table=<…>/`・`occurrence/source_id=<…>/`。キューブ・
   `occurrence_place`・`registry/*` は 1 表 1 ファイル。ADR-0020 決定2（L2 は出典単位で作り直せる）の構造を
   先に用意するもので、入力指紋（書き出し仕様＋スキーマ＋入力の行集合のダイジェスト）が前回と同じ
   パーティションは書き直さない。
5. **決定性**: 行は主キー（公開 ID）順、圧縮 zstd、行グループ長固定、`datapackage.json` に時刻を入れない。
   同じ入力から同じバイトになることを CI（sample-gate）と `scripts/tests/test_dist.py` が検査する。ライブラリの
   版でバイトが揺れても、`datapackage.json` の `rows_sha256`（行集合のダイジェスト。順序に依らない）で同一性を言える。
   `period_start/period_end` は文字列のまま（ADR-0024）。値は v2 と1ビットも違わない（座標・`value_zero`/`value_lod`・
   `censoring`）ことを行集合のダイジェストで検査する。
6. 公開範囲の機械検査（ADR-0028 下での読み替え。設計書 `docs/plans/ISSUE40_PHASE_D.md` D6）のうち `dist/` に
   効く 1〜4 を `scripts/d02_check_dist.py`（`scripts/dist/check.py`）が実装する: 合成データが出ない／座標が v2 と同一／
   旗で絞らない（`redistributable=0` の出典の行も v2 と同数）／旗が registry の `source_edition` と一致。
7. takedown 手順（別 ADR とした分）は本改定の範囲外。「`dist/` は決定的に作り直せる」ことが撤回の前提になる。
