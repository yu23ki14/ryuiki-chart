# ADR-0024: 時刻は時刻帯なしのローカル時刻で持ち、時刻ラベルの意味は出典ごとに宣言する

- 状態: 提案中 / 日付: 2026-09-15
- 関連: ADR-0002（多地域）, ADR-0007（observation）, ADR-0008（時間の3点セット）,
  ADR-0011（キューブ）, ADR-0014（応答封筒）, ADR-0021（キューブの鍵）

## 背景（実測）

**SQLite の日時関数は `+09:00` 付きの文字列を UTC に正規化してから日付を取り出す。**

```
sqlite> SELECT date('2015-04-02T00:00:00+09:00');
2015-04-01
```

（2026-09-15、Python 同梱の `sqlite3` モジュール 3.49.1 で実測・再現確認済み。`datetime()`/
`strftime()` も同様に UTC 側へ正規化する。）`observation.period_start` に `+09:00` 付きの文字列を
そのまま入れて SQLite の日付関数で日を取り出すと、9時間分ずれて前日になる。

ADR-0002（多地域）・ADR-0008（時間の3点セット）・ADR-0014（応答封筒）のいずれも時刻帯そのものには
触れていなかった（3ファイルを実測で確認。時刻の「粒度」「区間」は扱うが「タイムゾーン」の記述が
無い）。

`sensor_timeseries` の毎時値（`sagamihara_taiki_hourly`・`soramame_hourly_kanagawa`）は**区間の
終わり**でラベルされている——収集スクリプトのコメントが根拠:

- `scripts/c13_sagamihara_taiki.py:86`:
  `# 「1時」= 00:00〜01:00 の値。JMA/そらまめ君同様、時刻ラベルをそのまま採用`
- `scripts/c11_soramame.py:121`: `# 「24時」は翌日 00:00 として ISO 表記`

合成センサー（`synthetic_sensor`）は瞬時値（`phase-b/synthetic-instant`、PR #10）。25桁の時刻
ラベル（`sensor_timeseries` 717,839行中、毎時・瞬時の全行）はすべて `+09:00` 表記であることを
実測済み（`scripts/migrate/period.py` の `_strip_tz`。b03 の T1 不変条件検証でも全行確認）。

## 決定

### 1. `period_start`/`period_end` は時刻帯なしのローカル時刻

`YYYY-MM-DD`（日次以上）または `YYYY-MM-DDTHH:MM:SS`（時刻帯を含む原表記は残さない）にする。
`+09:00` を含む原表記は `period_raw` に別途残す。**時刻帯は地域（region）の属性**として持つ設計
にするが、それを実際の値（UTC オフセット）へ変換する結線は**本 ADR の時点では未実装**——応答の
境界（将来の ADR-0014 の実装）で付ける想定で、ADR-0002 の地域コードリストに時刻帯属性を足す設計
が別途要る。時刻の計算（hour_ending の −1時間）は `substr(label,1,19)` で時刻帯を落としてから
行う。

**不変条件（`b03` が全行で検証）**: `period_start`/`period_end` が `+`/`Z` を含まない、
`date(period_start) = substr(period_start,1,10)`。

### 2. 時刻ラベルの意味は出典ごとに宣言する（`scripts/migrate/time_label_conventions.yaml`）

`value_grain='hour'` の出典だけが宣言を要る（`instant`・`day` 以上は展開規則が自明なので不要）。
`hour_ending`: `period_start = ラベル − 1時間`、`period_end = ラベル`。宣言に無い `source_id` に
`value_grain='hour'` で出会うと `UnknownTimeLabelConventionError` で即座に止まる。宣言が1件も
使われなかった場合・実測件数が `expected_row_count` と食い違う場合も止める
（`period_exceptions.yaml` と同じ流儀。腐った宣言を残さない）。

- `sagamihara_taiki_hourly`（`expected_row_count=175,344`）: 根拠は c13:86 の自己言及。相模原市
  「大気の状況」データの一次資料（測定局運用マニュアル等）は未確認。
- `soramame_hourly_kanagawa`（`expected_row_count=168,793`）: 根拠は c11:121-123 のコメント＋
  c13 の「そらまめ君同様」という伝聞のみ。環境省「そらまめ君」・「環境大気常時監視マニュアル
  第6版」を Web 検索で確認しようとしたが、該当ページ・PDF からラベルの区間定義を確認できる
  テキストを抽出できず、**一次資料での確認には至らなかった**（2026-09-15）。「収集スクリプトの
  記載のみ・一次資料未確認」として正直に yaml に記録している（推測で `hour_beginning` と断定しない）。

合成センサーは `phase-b/synthetic-instant` で alias を `instant` に直すため、
`period_start = period_end = ラベル（時刻帯なし）`、`period_grain='instant'`、宣言不要。

### 3. キューブは区間の始まりの日付で日に割り当てる（正しい日割り）

キューブ（`b04`）は毎時・瞬時の観測を `substr(period_start,1,10)`（区間の始まりの日付）で日次
セルに積み上げる。v1（`web/scripts/build-derived.mjs`）は `substr(phenomenon_time,1,10)`
（**ラベルの日付**）で日割りしており、hour_ending のラベルは区間の終わりなので、23時〜24時の
値がラベルの日（＝翌日）に入るという、区間の境界をはみ出す集計になっている（v1 の癖）。
**このラベル日割りはキューブに焼き込まない。** v1 互換の射影（`b05`）が L2（`observation`）から
直接、ラベル日割りで再現する（`docs/plans/PHASE_B_FACT_SLICE.md` D10 と同じ理由の2例目
——「メンバーの区間がセルの区間をはみ出す集計は、原理的にキューブのセルになれない」）。

理由（アドバイザー指摘、3点）:

1. 焼き込むと L3 のセルが「`[D, D]` と名乗りながら `D−1` の23〜24時を含む」という、セル自身の
   期間宣言と実際のメンバーの区間が食い違う嘘を持つことになる。
2. 後（v1 退役後）に正しい日割りへ直そうとすると、実測した変更量（下記）が一度に動き、キーを
   1件ずつ列挙する宣言済み差分（`scripts/reconcile/expected_diffs.yaml`）では扱えない規模になる。
3. 日割りの規則を `imputation` のような軸として持たせても、鍵の語彙に「v1 のバグ由来の挙動」の
   名前が居座ることになる。

### 4. 毎時→日次の正しさは機械で検証する（ゲートが直接見なくなる経路の代替）

`sensor_daily` の毎時分（`sagamihara`/`soramame`）はキューブを経由しないため、
`scripts/b02_derived_compare.py` の突合ゲートはキューブの日割りの正しさを直接確認できない。
代わりに `b05_project_v1.py` の `verify_hourly_daily_rollup` が、`value_grain='hour'` の各系列・
各日について、キューブの日次セルの件数が v1形（L2 のラベル日割り）から機械的に導ける期待値と
全日で一致することを検証する（崩れれば `MigrationError`）。あわせて、系列ごとの全期間の
Σn・min・max がキューブの日次セルと L2 で一致することも確認する。**検証式そのものの正は
`scripts/b05_project_v1.py` の `verify_hourly_daily_rollup` の docstring**（D-1: 同じ式を
ここに書き下さない。ここでは「機械検証で代替する」という決定だけを書く）。

**ラベル00時の件数は数え方が2通りある**（実測。`value_grain='hour'` の行を `sensor_timeseries`
の `source_id` で引き戻して集計）:

| 数え方 | sagamihara | soramame | 計 |
|---|---:|---:|---:|
| 全行（`result IS NULL` も含む） | 7,306 | 7,020 | 14,326 |
| `value_num IS NOT NULL` に限る | 7,263 | 6,498 | 13,761 |

実際に `verify_hourly_daily_rollup` が使うのは**後者**（`value_num IS NOT NULL` に限った数え方。
キューブ側の `WHERE v IS NOT NULL` と対応させるため、L2 側の集計も `value_num IS NOT NULL` で
絞っている）。

## 影響

- **良い**: 時刻帯の取り違えが SQLite の日時関数レベルで構造的に起きなくなる（不変条件で全行
  検証）。時刻ラベルの意味（hour_ending か否か）がコードに埋め込まれず、宣言として読める。
  日割りの正しさを機械検証に変えたことで、v1 のバグ由来の癖をキューブに持ち込まずに済む。
- **コスト**: `period_raw`（原表記）を別列で持つ必要がある。`sensor_daily` の毎時分だけキューブを
  経由しない特別扱いが残る（D10 の原則どおりだが、コードパスが1つ増える）。
- **注意**: 時刻帯を「地域の属性」にする設計は本 ADR ではまだコード化されていない
  （ADR-0002 のコードリスト拡張と、応答境界での変換が別途要る）。`soramame_hourly_kanagawa` の
  hour_ending という前提は一次資料未確認のまま採用している——将来一次資料が見つかれば
  `time_label_conventions.yaml` の `evidence` を更新すること。

## 検討した代替案（却下理由）

- **キューブにラベル日割りを焼き込んで後で直す**（最初の設計）: 決定3の理由1〜3で却下。
- **日割りの規則そのものを次元（軸）にする**: v1 のバグ由来の値がキーの語彙として永続することに
  なり、正しいモデルに間違った概念が居座る。却下。
- **`period_start`/`period_end` を UTC で持つ**: `sensor_timeseries` は全行 `+09:00` 固定で UTC
  への変換は一律9時間の引き算で済む一方、JST のまま持てば人が読める・原表記（`period_raw`）との
  対応が直感的。UTC 化は「時刻帯を持たない」という決定の利点（境界まで判断を持ち込まない）を
  失う。却下。

## ADR-0008 への参照

[ADR-0008](0008-time-representation.md) に本 ADR を参照する追記（時刻帯と時刻ラベルの意味の
明確化）をした。ADR-0008 自体の決定（区間＋粒度の3点セット）は書き換えていない。
