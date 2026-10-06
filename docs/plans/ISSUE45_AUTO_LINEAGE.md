# Issue #45 系譜（inputs）を実際の読み取りから自動生成する（設計）

## 現状
- 系譜は `pipeline_fingerprint.inputs`（`{上流表名: 消費時点の上流指紋}`）。各段が手で組む:
  b03・b06 は `fingerprint_inputs={}`、b04 は `{"observation": …}`、b09 は `{"occurrence": …}`、
  b07 は `{"occurrence", "occurrence_place"}`、b13 は表ごとに `{source: …, "registry:<join列>": registry指紋}`。
  b13 だけ `upstream_schemas={}` で (b) を再帰検証し、他は系譜の末端（`_assert_lineage_fresh` は b13 経由でのみ辿る）。
- `track_reads`/`assert_all_reads_verified`（読み取りの機械監査）は b05/b08 撤去後どの段からも呼ばれていない（テストのみ）。
  つまり今は「宣言外の JOIN を足しても検出も追従もしない」。
- 各段は上流の (a) 検証（`assert_stage_fingerprint_fresh`）を手で呼び、戻り値の指紋を手で `inputs` に渡している。

## 設計
1. **`LineageTracker`**（`scripts/migrate/common.py`）。`with common.track_lineage(conn, external={...}) as lineage:`
   で段の接続に authorizer を入れ（既存 `track_reads` を内部で使う）、読み取り集合を持つ。
   - `lineage.verify(table, *, rebuild_hint, schema=None, upstream_schemas=None)`: `assert_stage_fingerprint_fresh` を呼び、
     戻り値を `verified[(schema or "main", table)]` に保存して返す。段は（今まで通り）検証を呼ぶだけ。指紋を `inputs` に渡さない。
   - `external={schema: 指紋 or None}`: 別機構が見る ATTACH 先。registry は `{"reg": registry入力指紋}`（b13 は `registry`）。
     原本（`ryuiki`/`src`）は `None`（`pipeline_input_fingerprint` が見る）。
   - `lineage.reset()`: 読み取り集合を空にする（b13 が表ごとの区切りに使う）。`verified` は残す。
2. **`staged_table(..., lineage=tracker)`**（`fingerprint_inputs=` は引数ごと撤去）。差し替え直前に
   `tracker.resolve(output=table, staging=…)` で `inputs` を作り、同じトランザクションで記録（現行の原子性を維持）。
   resolve の規則（読み取り `(schema, table)` ごと）:
   - 自分の出力・`<table>__building`・`temp` スキーマ・SQLite カタログ表・`pipeline_fingerprint` 系のメタ表 → 無視。
   - `main`（または ATTACH 先）で `pipeline_fingerprint` 行を持つ表 → 上流。`verified` に無ければ `MigrationError`
     （＝ `assert_all_reads_verified` の機能を resolve に吸収。検証を足し忘れた JOIN は止まる）。あれば `inputs[key] = verified の指紋`。
   - `external` にある schema → `inputs["ext:<schema>.<table>"] = その指紋`（`None` の原本は inputs に入れない。読んだこと自体は許可）。
   - どれでもない表・schema（宣言のない ATTACH、指紋の無い main 表）→ `MigrationError`（暗黙の除外をやめる）。
   - キー: main の上流は従来どおり表名（`"observation"`）。非 main は `"schema.table"`。
3. **`_assert_lineage_fresh`**: `ext:` で始まるキーは再帰の対象外（指紋の照合のみ必要なら呼び出し側。現状 registry の鮮度は
   `check_v2_pipeline_fresh` の `registry.input_fingerprint` が見る）。`schema.table` キーは分解して辿る。
4. **粒度**: 出力表ごと。単一出力の段（b03/b04/b06/b09/b07）は段全体の読み取り＝その出力の読み取り
   （b09 は `with` の前に座標を読むので、tracker は段の先頭から張る）。b13 は表ごとのループ先頭で `reset()`、
   source の検証（キャッシュ分は再検証しない）は `verified` に残るので、表ごとの inputs は「その表の SELECT が読んだ
   source + registry の表（`registry.taxon` 等）」に正確に絞られる。
5. **b03/b06**: 出力接続 `dest` は上流を読まない（読むのは `:memory:` の `work` 接続で、原本と registry）。
   `dest` のみ tracker を張り `inputs={}` が自動で出る。`work` 接続の読み取りは `pipeline_input_fingerprint`
   （原本4表・registry 指紋・コード）が従来通り担う。**要判断**: `work` にも `lineage.watch(work, external=…)` を足せば
   b06 の registry 読みも系譜に載るが、段の本体（ループ内）に触るので衝突リスクが上がる。既定は触らない。
6. 手書き宣言の撤去: 各段の `fingerprint_inputs=`・`*_fingerprint` 変数・b13 の `lineage` 辞書。
   b13 の `build_summary` 内 `registry_fingerprint` は `external={"registry": …}` に渡す形に変わる。

## 変更ファイル
- `scripts/migrate/common.py`（`LineageTracker`/`track_lineage`/`resolve`、`staged_table` の引数差し替え、`_assert_lineage_fresh` の `ext:`/`schema.table` 対応、
  `assert_all_reads_verified`/`track_reads` は resolve に吸収した分を整理）
- `scripts/b03/b04/b06/b07/b09/b13_*.py`（配線のみ: tracker を張る・`verify` 呼び替え・`fingerprint_inputs=`→`lineage=`）
- `scripts/tests/test_migrate_common.py`、`scripts/tests/test_lineage_auto.py`（新規）、各 b0x テストの `fingerprint_inputs` 参照があれば追随
- `docs/PIPELINE.md` の「段階間の指紋」の段落

## 検証
- 新規テスト（フィクスチャの小 DB。`up`/`mid`/`down` の3表＋ATTACH した registry 風DB）:
  1. 読み取りを1つ足す（`down` の SELECT に `up2` を JOIN）と、`inputs` に `up2` が増える（宣言は触らない）。
  2. 上流 `up` を書き換えて指紋を再記録すると、`down` の `assert_stage_fingerprint_fresh(upstream_schemas={})` が古いと止まる。
  3. `verify` していない表を JOIN すると `staged_table` が `MigrationError`（わざと壊すと止まる）。
  4. 未宣言の ATTACH 先を読むと止まる／`external` の registry 表は `ext:registry.taxon` で入る。
  5. 出力表ごとの絞り込み: 2表を同じ段で作り、片方だけが読む上流が他方の inputs に入らない（`reset`）。
  6. `temp` テーブル・view 経由の読み取りが実表として拾われる。
- 既存: `scripts/tests` の test_migrate_common・test_b03/b04/b06/b07/b09/b13・test_check_v2_fresh を回す。
- 重い検証（メインが1回）: `build:v2`、b00（`reports/serving_fingerprint.json` 更新）、`serving:snapshot`。

## リスク
- authorizer の拾い漏れ/拾いすぎ: view は実表に展開されて報告される想定だが、テスト6で固定する。b04 の `obs_imputed`（temp view）は temp 扱いで、基底の `observation` が拾われる。
- 厳格化（未知の読み取りは止める）で、いま暗黙に通っている読み取りが本番ビルドで初めて止まる可能性。実 DB での検出は build:v2 を回すメインに依存（止まったら宣言が足りないのではなく、本当に未検証の読み取り）。
- b04/b07 の `inputs` に registry が増える（b04 は `reg`）。表の内容・`spec_version` は不変だが `pipeline_fingerprint.inputs` が変わるので b00 の実行証明は更新が要る。
- authorizer は接続に1つ。b04 の既存コードが別の authorizer を使っていないことは確認済み（grep: 他に無し）。
- b13 の表ごとの区切り（`reset`）を入れ忘れると他表の上流が混ざる（多めに申告する方向に倒れるので安全側）。

## 実装メモ（承認後の決定・設計からの差分）
- b03/b06 は `work` 接続にも `lineage.watch(work, external=...)` を1行足した（承認済み）。原本は表ごとの代理指標
  （`pipeline_input_fingerprint` と同じ取り方）を値に `ext:src.<table>` として入る。
- tracker は `track_lineage` コンテキストではなく `LineageTracker(conn)` を段の先頭で作る形にした（段の本体をインデントし直さないため）。
  `staged_table` が失敗すると authorizer を解除し、b04/b07 は成功後に `release()`、b13 は finally、b09 は接続を閉じる。
- 実測: TEMP テーブルの読み取りは `SQLITE_READ` で `temp` ではなく `main` と報告される。resolve 時点で main に実在しない表は無視する
  （DROP 済みの `__sample_ids` 等）。
- `track_reads`/`assert_all_reads_verified`/`assert_occurrence_fingerprint_fresh` は撤去（`LineageTracker.resolve` に吸収）。
