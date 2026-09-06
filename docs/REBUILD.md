# 再構築手順（REBUILD） — GBIF収集完了後にやること

> **【2026-08-29 実行済み】本書の再実行手順はすべて実行され、完了した。**
> 結果は `docs/FINAL_REPORT.md` §0.1 に記録している。以降この手順を再度実行する必要はない
> （`m03_organisms.py` は冪等なので実行しても害はない）。実行時に判明した本書との差異は次の2点:
>
> 1. **手順1のUPDATE文は使えない。** 完走時点で `source_registry` には `gbif_kanagawa` と
>    `gbif_kanagawa_occurrences` の**両方**が存在していたため、`UPDATE ... SET source_id=...` は
>    主キー衝突する。旧登録 `gbif_kanagawa`（第2ラウンド時点586,300行）は削除もリネームもせず、
>    `notes` 冒頭に `【SUPERSEDED 2026-08-29】` を付して無効化を明示する方針に変更した
>    （F-5「旧行を消さずにsupersedeする」の方針に合わせた）。**集計時はこの1件を除外すること。**
> 2. **手順6の孤児検査は0件**（第3ラウンドが修正後のコードで走ったため）。
>    `x01_dwca.py` の GBIF_ALIAS フォールバックはもう不要だが、旧名だけが
>    登録されている環境のために残してある。
>
> また、本書には無かった手順として `python3 scripts/x03_verify_dwca.py`（DwC-Aの構造検証。
> それまで手作業だった検証をスクリプト化したもの）を追加した。**手順5と7の間で実行すること。**
>
> **【2026-08-29 追記】配布パッケージ（`data/dist/`）は廃止した。**
> 元データ（`data/db/` + `data/processed/`）の重複コピーでしかなく混乱の元になるため、
> ディレクトリと構築スクリプト `scripts/x02_build_dist.py` を削除した。
> DwC-A の zip は `data/dwca/dwca_ryuiki_kanagawa.zip` に移した（`x01_dwca.py` の出力先も変更済み）。
> 本書中の「配布パッケージ」に関する手順・数値は**すべて無効**である。


本書は、本タスク（ライセンス欠陥3件の修正）実行時点でまだ完走していなかった
GBIF収集（`scripts/c02_gbif_repair.py`）が完了した後、何をどの順番で再実行すればよいかを
まとめたものである。本タスク中に実際にこの順序でコマンドを実行し、結果を確認した
（`docs/FINAL_REPORT.md` §5〜7参照）。

## 前提: 本タスクで行った修正

1. `organism_records` に `record_license` / `license_class` / `commercial_ok` の3列を追加し、
   iNaturalist・GBIFの実際のライセンス値をマッピングして埋めた（`scripts/m03_organisms.py`）。
2. `scripts/x01_dwca.py` を修正し、既定で `license_class` が `noncommercial`/`unknown` の
   occurrence をDwC-Aから除外するようにした（`--include-noncommercial` で無効化可）。
3. `scripts/c02_gbif.py` / `scripts/c02_gbif_repair.py` の `register()` 呼び出しを
   `source_id="gbif_kanagawa"` から `source_id="gbif_kanagawa_occurrences"` に修正した
   （`organism_records.source_id` の実データ名に統一）。
4. （配布パッケージ構築スクリプト `x02_build_dist.py` を正式配置したが、
   **配布パッケージ自体を廃止したため 2026-08-29 に削除した**。下記参照）

## 重要な注意: 実行中だったGBIF収集プロセスについて

本タスク実行開始時点で `scripts/c02_gbif_repair.py` が起動済みだった（pid確認済み）。
このプロセスは**修正前のコードを既にメモリに読み込んで実行中**のため、上記3.の修正は
このプロセスの今回の完走には反映されない可能性がある。つまり、このプロセスが完走した際、
`source_registry` には次のいずれかの状態が起こりうる:

- (a) `source_id='gbif_kanagawa_occurrences'` として登録される
  （プロセスが再起動されるか、修正後のコードで再実行された場合）
- (b) `source_id='gbif_kanagawa'` として登録される
  （起動済みプロセスがそのまま完走した場合。本タスク実行時点で最も可能性が高い）

`scripts/x01_dwca.py` はどちらのケースでも動作するよう
`GBIF_ALIAS = {"gbif_kanagawa_occurrences": "gbif_kanagawa"}` によるフォールバックを
維持しているため、**(a)(b)いずれであっても以下の再実行手順はそのまま使える。**
ただし (b) の場合、`source_registry` の表記と実データの表記が一致しないままになるため、
`docs/LICENSE_MATRIX.md`・台帳の整合性を厳密に保ちたい場合は、GBIF収集完了後に以下を
実行して名称を統一すること（`register()`はINSERT OR REPLACEなので、再度
`gbif_kanagawa_occurrences`という名前で`register(...)`を呼び出す形でも良いが、直接UPDATEする
のが簡便）:

```sql
-- data/db/ryuiki.sqlite に対して実行（DELETE/DROPではなくUPDATEのみ。既存データは失われない）
UPDATE source_registry SET source_id='gbif_kanagawa_occurrences' WHERE source_id='gbif_kanagawa';
```

## 再実行手順（この順序で実行し、本タスク中に実際に検証済み）

```bash
cd /home/yu23ki14/cfj/ryuiki-demo && . .venv/bin/activate

# 1. GBIF収集が完了し、source_registryに登録されたことを確認する
python3 -c "
import sqlite3
c = sqlite3.connect('data/db/ryuiki.sqlite')
print(c.execute(\"select source_id, redistributable, record_count from source_registry \
  where source_id like '%gbif_kanagawa%'\").fetchall())
"
# -> ('gbif_kanagawa_occurrences', 1, ...) または ('gbif_kanagawa', 1, ...) が出れば登録済み。
#    上のUPDATE文で名前を統一しておくと以降の確認がしやすい。

# 2. アプリDBへの取り込み（GBIFのjsonlが増えていれば新規分も取り込み、
#    既存行のrecord_license/license_class/commercial_okも最新化される。冪等・再実行安全）
python3 scripts/m03_organisms.py

# 3. レコード単位ライセンスの実測集計を確認する（新しいライセンス値が出現した場合、
#    scripts/m03_organisms.py の標準出力に "!! 未知のライセンス表記を検出" という警告が出る。
#    その場合は LICENSE_MAP に追記してから再実行すること。憶測でopen/noncommercialに
#    割り当てないこと）
cat data/processed/license_code_mapping.csv

# 4. DwC-A再生成（既定でnoncommercial/unknownを除外。GBIF由来のopen/restrictedレコードが
#    新たに含まれるようになるはず）
python3 scripts/x01_dwca.py
cat data/dwca/EXCLUDED_LICENSE.md

# 5. （旧「配布パッケージ再構築」の手順はここにあったが、配布パッケージを廃止したため削除）

# 5b. DwC-Aの構造検証（meta.xml整合・eventID参照整合・列数不整合・
#     eventDateのISO8601適合性・座標一般化件数を再計算する。読み取り専用）
python3 scripts/x03_verify_dwca.py

# 6. source_id孤児の再検査（gbif_kanagawa_occurrencesの孤児が解消されているはず）
python3 -c "
import sqlite3, csv
conn = sqlite3.connect('data/db/ryuiki.sqlite')
reg = set(r[0] for r in conn.execute('select source_id from source_registry'))
for t in ['organism_records','measurements','sensor_timeseries','sites','events']:
    cols = [c[1] for c in conn.execute(f'pragma table_info({t})')]
    if 'source_id' not in cols: continue
    for sid, cnt in conn.execute(f'select source_id, count(*) from {t} group by source_id'):
        if sid is not None and sid not in reg:
            print('ORPHAN', t, sid, cnt)
"
# -> 何も出力されなければ孤児は解消済み。

# 7. 検証スクリプト・インベントリの再生成（既存の運用手順。docs/DATA_INVENTORY.md 等が更新される）
python3 scripts/m99_validate.py
```

## 期待される結果の変化（※以下は実行前の見込み。実測値は次節を参照）

### 【実測】2026-08-29 実行後の確定値

| 項目 | 実行前 | 実行後 |
|---|---:|---:|
| `organism_records` | 646,134 | **823,692** |
| `data/dwca/occurrence.txt` | 30,165 | **626,065** |
| `data/dwca/event.txt` | 63,158 | **659,058** |
| `data/dwca/extendedmeasurementorfact.txt` | 315,318 | 315,318（変化なし） |
| ソース単位（未登録/redistributable=0）による occurrence 除外 | 480,802 | **0** |
| レコード単位ライセンスによる occurrence 除外 | 135,167 | 197,627（noncommercial 176,397 + unknown 21,230） |
| 座標一般化（FR-4.5）件数 | 27 | **2,080** |

`docs/LICENSE_MATRIX.md`・`docs/FINAL_REPORT.md` の該当数値は更新済み。


GBIF収集が完了し `redistributable=1` で登録されると、以下の数値が変わる見込みである
（本タスク実行時点、GBIF収集途中経過480,802件時点でのライセンス内訳をもとにした試算。
実際の最終件数・内訳はその時点のGBIF収集結果に依存するため、上の手順6で必ず再集計すること）:

- `data/dwca/occurrence.txt` の件数: 本タスク完了時点の30,165件（iNaturalistのopen/restrictedのみ）
  から、GBIF由来のopen/restricted相当分（本タスク時点の速報値で約42万件規模）が追加され、
  大幅に増加する。ただしGBIF由来のnoncommercial（CC BY-NC。本タスク時点で約6万件）は
  引き続きDwC-Aから除外される。
- `docs/LICENSE_MATRIX.md`・`docs/FINAL_REPORT.md` の該当数値は、上記手順を実行したうえで
  再度手動更新すること（本タスクでは反映していない。GBIF収集完了後の値は未確定のため）。

## やらないこと（禁止事項の再確認）

- GBIF APIを追加で叩かない（`scripts/c02_gbif.py`/`c02_gbif_repair.py`の再実行以外で）。
- `data/processed/gbif_kanagawa_occurrences.jsonl` を削除・切り詰めない。
- `organism_records`等の既存実データ行をDELETEしない（ALTER TABLE ADD COLUMNとUPDATEのみ）。
- ライセンス表示のないレコードを推測で`open`に分類しない。
