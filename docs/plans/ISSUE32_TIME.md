# Issue #32 / #33(3,4,6) 設計: 日付の癖の退役・厚木の月粒度・時刻帯の結線

状態: 設計（実装前。メインの承認待ち）。2026-10-06 時点の実測。

## 1. 現状の実測

### #32-1 ラベル日割りの癖
- `grep` で b03/b04/web の cube 層を確認: ラベルの日付で割る分岐は**残っていない**。`b05_project_v1.py`・
  `sensor_daily`/`rain_daily`/`sensor_hour_month` は #48 PR-5 で撤去済み（`scripts/` に b05/b08 無し）。
  残るのは説明コメントだけ（`scripts/b04_build_cube.py:97`、`scripts/migrate/cube_invariants.py:140,203`、
  `web/src/lib/cube/observation.ts:873`）。b04 は `substr(period_start,1,10)` で正しい日割り、
  `cube_invariants.py` T6 が「キューブ n = ラベル日割り n −00時ラベル +翌日00時ラベル」を全日検証している。
- つまり退役は PR-5 で自動的に完了。動く値は「なし」（v1 表ごと消滅）。

### #32-2 厚木の月粒度
- 原本 `measurements` の `atsugi_river_water_quality` は 4,560 行。うち 720 行は `measured_on` が 10 桁
  （2002-04〜2004 年度、採水日あり）、**3,840 行が 4 桁の年度番号**（FY2005〜2020 の 16 年度×12 か月×4 地点×5 項目）。
- `source_ref`（`...#<月ラベル>:<地点>:<項目>`）の月ラベルは 3 形式: `N月` 3,180 行、`平成N年N月`/`令和N年N月`/`令和元年N月`
  計 660 行（`平成31年4月` 等の和暦付きは FY と整合。10 桁行 720 行は月ラベルと `measured_on` の月が全件一致）。
  全 3,840 行で月が取れる。暦年は「月 4〜12 → measured_on の年度、月 1〜3 → 年度+1」で決まり、和暦付き 660 行で
  独立に照合できる（実装時に全件検証する）。
- 現行キューブ（`data/db/v2.sqlite`、atsugi 4 地点）: day 2,160 セル / **fiscal_year 960 セル（n=11,520。各セル n=12 の
  mean/min/max）** / month 720 / year 240。`summary_place_variable` の atsugi 行は fiscal_year 20 + year 20。
- **重要な発見**: 月粒度に復元しても `value_grain='day'`（日間平均値）と `period_grain='month'` は一致しない
  （採水日は月内の 1 日で特定不能、原本は「8〜9日」等の範囲表記）。よって Issue の「エントリが不要になる」は成り立たない:
  `period_exceptions.yaml` のエントリは**残り**、`period_grain_override: fiscal_year → month`、`restoration_plan`
  を「復元済み。残る不一致は日が原理的に特定できないことによる恒久的なもの」に書き換える（expected_row_count 3840 は不変）。
  → 承認事項 A。

### #32-3 時刻帯
- `+09:00` の直書き: `scripts/migrate/period.py:61 _EXPECTED_TZ_SUFFIX`（センサー 25 桁ラベルの検査）。
  region 経由は既に `scripts/migrate/source_regions.yaml` の `regions.jp-14.utc_offset` があり b06 の 'Z'→ローカル変換が使う。
  **web 側には時刻帯の読み出し口が無い**（`Tokyo|timeZone|utc_offset` が web/src に 0 件）。レジストリ（registry/ → registry.sqlite →
  D1 → generated.ts）に region の表が無い（`place.region_id` の列のみ）。
- つまり時刻帯の「正」が `source_regions.yaml` の中にあり、レジストリからは引けない。

### #32-4 そらまめ君 hour_ending
- 探索範囲: env.go.jp（press/1562・2700、manual_kento mat07.pdf）、tenbou.nies.go.jp（`/download/`、`gis/explain/atm/moni.html`）、
  同 `TJ_manu.pdf`（大気環境時間値データファイル仕様）、soramame.env.go.jp トップ。
- 見つかったこと: `TJ_manu.pdf` の列は `01h`〜`24h`（`00h` が無い）で「1時間値測定データ」。これは hour_ending と整合する
  構造的な状況証拠だが、**「1時の値は0〜1時の平均」と明言した一次資料は取得できなかった**（PDF/ページに定義文なし）。
  一般検索の要約（「前1時間の値」）は一次ではない。

### #33-3/4/6
- 3/4: ADR-0026 に境界上の点の保留記述（「影響」）、ADR-0011:160 に `roll_up_to`。
- 6: 原本更新で測り直しが要る宣言は 7 ファイル（`scripts/migrate/` の `occurrence_place_declarations`・`occurrence_cube_declarations`・
  `occurrence_period_shapes`・`period_exceptions`・`source_regions`・`time_label_conventions`・`unit_evidence_declarations`）と
  標本の `data/sample/declaration_counts.yaml`（`s01_build_sample.py` が再生成）。DEPLOYMENT.md「原本データが変わった」節は
  `build:v2`→seed のみで、宣言値の測り直しに触れていない。

## 2. 決定

1. **#32-1**: コード変更なし。ADR-0024 に「PR-5 で v1 表ごと消滅済み。退役で動いた値: なし。決定3/4 の v1 射影（b05）への
   言及は歴史」と追記。ADR-0024 冒頭の「PR-2 で退役予定」2 つの追記も解決済みに更新。
2. **#32-2**: b03 に「月ラベル復元」を実装。原本（measurements）は触らない（m05 を再実行しない）。
   - `period_exceptions.yaml` のエントリに任意キー `restore_month_from: source_ref_month_label` を追加。
   - `scripts/migrate/period.py` に `restore_month_from_source_ref(measured_on_fy, source_ref)` を追加（`YYYY-MM` を返す。
     月ラベル解析不能・和暦付きが FY と不整合なら `MigrationError`）。b03 は `measurements` 行で、4 桁かつ宣言ありのとき
     これで 7 桁の measured_on を作り `compute_period` に渡す。`period_raw` は原表記（4 桁）のまま残す。
   - `compute_period` の 7 桁分岐: `value_grain != 'month'` のとき、4 桁分岐と同じく `exceptions` の宣言があれば
     `period_grain_override`（month）を許す（宣言が無ければ従来どおり PeriodMismatchError）。
   - テスト: 全 3,840 行の復元値が (FY, 月) と整合・和暦付き 660 行の独立照合・わざと壊す（月ラベル欠落・FY との矛盾）で止まる。
3. **#32-3**: レジストリに region 表を新設して時刻帯の唯一の置き場にする。
   - `registry/region.yaml`（新規手書き）: `jp-14: {name_ja, tz_name: Asia/Tokyo, utc_offset: "+09:00", evidence}`。
   - `scripts/registry/build_region.py` + `r01_build_registry.py` → `registry.sqlite` の `region` 表（`schema-registry.ts` に追加、
     `db:generate`、シード対象に追加）。
   - `web/scripts/build-registry-ts.mjs` が `REGION_TIME`（client 安全）を `generated-client.ts` に出す。
     `lookup-client.ts` に `regionTimeZone(regionId): {tzName, utcOffset}`（未知の region は例外。黙って JST に倒さない）。
     応答封筒（ADR-0014/`cube/envelope.ts`）が使う読み出し口はこれ。
   - 使用箇所の置き換え（主要のみ）: `source_regions.yaml` の `regions.<id>.utc_offset` を**撤去**し、`source_regions.py` が
     `registry/region.yaml` を読む（二重管理をやめる）。`period.py` の `_EXPECTED_TZ_SUFFIX` は region.yaml の jp-14 offset から導く。
     `source_regions.yaml` の「未使用 region 宣言は止める」検査は region.yaml 側の参照検査に移す。
   - 整合検査: `place.region_id`（common 以外）と `observation.region_id` に現れる全 region_id が `region` 表に存在すること
     （r01 で機械検証。わざと未知 region を入れると止まる）。
   - ADR-0024 の「未実装」注記を更新。
4. **#32-4**: `time_label_conventions.yaml` の soramame の `evidence` に「`TJ_manu.pdf`（https://tenbou.nies.go.jp/download/TJ_manu.pdf）
   の列が 01h〜24h で 00h が無い。hour_ending と整合する状況証拠だが定義文は未確認」と URL 付きで追記。convention は現状維持。
   ADR-0024 の同記述も更新（「一次資料で明言は未確認」は維持）。
5. **#33-3/4**: 実装せず、ADR-0026（境界上の点）と ADR-0011（ロールアップ）に「トリガー」と「方針案」を追記。
   - 境界上: トリガー=面が辺を共有する place_kind（市区町村等）を `occurrence_place` に足す PR。方針案=入った面を全て記録せず、
     決定的な規則（place_id の辞書順最小）で 1 つに割り当て、割当件数を宣言ファイルで件数検証し、境界上の件数を注記で出す。
   - ロールアップ: トリガー=zone/watershed/municipality 単位の集計を API/画面が要求する最初の PR。方針案=`n_places` を持つ
     ロールアップセルを place_relation 経由で作り、非加重平均は作らない（セル平均の平均は不可、観測行から再集計）。
6. **#33-6**: DEPLOYMENT.md「原本データが変わった」の直後に「宣言ファイルの測り直しチェックリスト」節を追加
   （上記 7 ファイル＋ sample の declaration_counts、各ファイルの測り方=該当 b0x の検証が出す実測値と宣言値の差を見る手順、
   rowid 固有の `occurrence_place_declarations.yaml` を明記、`docs/add_area.md` §4 から参照）。

## 3. 変更ファイル一覧（予定）
- 月粒度: `scripts/migrate/period.py`、`scripts/migrate/period_exceptions.yaml`、`scripts/b03_build_observation.py`、
  `scripts/tests/test_migrate_period.py`・`test_b03_build_observation.py`、`docs/adr/0021-*.md`（restoration の更新）、
  `docs/plans/PHASE_B_INTAKE.md`（復元済み追記）。
- 時刻帯: `registry/region.yaml`（新）、`scripts/registry/build_region.py`（新）、`scripts/r01_build_registry.py`、
  `scripts/migrate/source_regions.py`・`source_regions.yaml`・`period.py`、`web/src/db/schema-registry.ts`＋`drizzle/migrations`（生成）、
  `web/scripts/seed-d1-local.mjs`（表の追加）、`web/scripts/build-registry-ts.mjs`、`web/src/lib/registry/lookup-client.ts`＋テスト、
  `web/src/lib/table-meta.ts`、`registry/README.md`、CLAUDE.md の表数（40→41）、ADR-0024・ADR-0002 の追記。
- 文書: ADR-0024/0026/0011、`DEPLOYMENT.md`、`scripts/migrate/time_label_conventions.yaml`。

## 4. 検証方法
- 触った箇所だけ: `pytest scripts/tests/test_migrate_period.py test_b03_build_observation.py test_migrate_source_regions.py`、
  registry の生成テスト（`web/src/lib/registry/generated.test.ts`・新設の region テスト）、`cd web && pnpm run build:registry`。
- 月粒度の実測は b03 の厚木だけ（`--only` 相当が無ければ、対象 source だけ流すテスト）で件数と grain 内訳を確認。
- 重い検証（b00 全量・serving:snapshot 全量・build:v2 全量）はメインが 1 回。

## 5. スナップショット・キューブが動くか
- **動く（厚木のみ、2 の #32-2）**。実測ベースの見積り（実装後に build:v2 で確定）:
  - `observation`: 3,840 行の `period_grain` が fiscal_year→month、`period_start/end` が年度境界→月初〜月末。`period_raw` 不変。
  - `observation_agg`（atsugi）: fiscal_year 960 セル（n=11,520）が消え、`grain=month, input_grain=month` の出典配布セルが
    3,840 行×{mean,min,max}=11,520 セル（各 n=1）に置き換わる。day/month(from day)/year(from day) は不変。
    差し引き +10,560 セル（全体 1,999,844 → 約 2,010,404）。
  - `summary_place_variable`: atsugi の fiscal_year 20 行が month（input_grain=month、y_from..y_to は 2005〜2021）に変わる。
  - `data/sample/serving_snapshot.json`: atsugi を含むクエリが動く——site 一覧の中津川（5 行、`fiscal_year,n=192`）、
    series の `fiscal_year/相模川/DO`・`玉川/SS`。avg は同値（全月の単純平均 = 旧 FY 平均の平均、n=12 均等なので一致する見込み）。
    変数横断（`basis=fiscal_year` の全地点系クエリ）への波及は `--mode diff` で確認。PR には before/after 表を貼る。
  - 時刻帯結線・文書変更ではスナップショットは動かない。
- 注意: 月セルは年度/暦年へロールアップされない（b04 の積み上げは日次セル起点のみ）ため、atsugi の fiscal_year 集計値は
  cube から消える。年度平均が要る画面は月セルからの再集計になる。→ 承認事項 B。

## 6. メインへの承認事項
- A: `period_exceptions.yaml` のエントリは消えず override=month で残る（Issue の閉じる条件の文言が実態と違う）。この読みでよいか。
- B: 月セルの年度ロールアップは作らない（スコープ外）でよいか。fiscal_year 行が cube から消える影響を許容するか。
- C: `source_regions.yaml` の `regions:` を撤去して `registry/region.yaml` に一本化する（宣言ファイルの形が変わる）でよいか。


---

## 7. 実装の記録（2026-10-06。メイン承認後。レビュー反映済み）

### 承認で決まったこと
- A: `period_exceptions.yaml` のエントリは残し override=month（ADR-0021 追記に理由）。
- B（2026-10-07 オーナー確認済み。厚木の年度のみ・暦年は作らない）: 月 → 年度のロールアップを実装。当初の「一般規則」はレビューで撤回し、**宣言駆動**にした
  （`rollup_to: [fiscal_year]` と宣言した出典だけ。厚木は年度、暦年は作らない。jma_monthly は新セル 0）。
- C: `source_regions.yaml` の `regions:` を撤去し `registry/region.yaml` に一本化。旧形式が残っていれば止める。
- 25桁ラベルの時刻帯は固定の jp-14 ではなく、行の region（`place.region_id`）の `utc_offset` と照合する（b03 が渡す）。

### 実測（b03→b04 を scratchpad の別ファイルに全量で流して計測。`data/db/v2.sqlite` は無変更）
- b04 全量が不変条件（月→年度の保存則・無作為抽出セルの独立再計算・T6）込みで通った（123 秒）。
- `observation_agg` 全体: 1,999,844 → 2,011,364（+11,520 = 厚木の月セル。mean/min/max × 3,840 観測行）。
  fiscal_year は 厚木 960 → 960（`input_grain` が fiscal_year → month に変わるだけ）。day・year(day 側)・jma 系は 0 増減。
- **宣言済み差分（C）**: 厚木の月セル 11,520（`grain=month`・`input_grain=month`・`value_grain=day`）が月系列・季節性・
  zone_month_of_year の集計に入る。日付あり 1 回採水（`input_grain=day` の 720 行）と同じ扱い。
- **旧 fiscal_year セル 960 と新ロールアップの突き合わせ: 960 件中 960 件一致、不一致 0**
  （value_zero/value_lod は相対誤差 1e-9、n・n_censored・n_not_detected は完全一致）。
- 暦年・jma_monthly の積み上げは作らない（初版の実測で year 3,099・jma fiscal_year 2,319 セルが出ていたが撤回）。

### web 側
- 「出典が配った粒度のセルか」の規則は `web/src/lib/cube/cell-basis.ts` の1か所（`isSourceGrainCell`・
  `sourceGrainCellSql`・`basisOfCell`）。`observation.ts` の `inputGrain:"same"`・`series.ts`・`SiteDetail.tsx` は
  これを使う。`serving_queries.yaml` の WHERE は同じ式を直書きし、`cell-basis.test.ts` が一致を確かめる。
- 厚木の fiscal_year 行（`input_grain=month`）は従来どおり basis=fiscal_year として画面・API に出る。暦年値の行は増えない。

### 時刻帯
`registry/region.yaml` → `region` 表 → `REGION_TIME`（regionId/tzName/utcOffset）→ `regionTimeZone()`。D1 の表数 40 → 41。

### スナップショットが動く範囲
厚木 `fiscal_year` 行（中津川の site 一覧 5 行、相模川 DO・玉川 SS の series）の `input_grain` だけ。avg は一致する
（旧 960 セルとの突き合わせで値が一致）。`--mode diff` で確認すること。
