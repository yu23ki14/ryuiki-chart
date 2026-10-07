# 出現件数に座標なしの記録を含める・MCP の入力検査と注記（2026-10-07）

利用者の検証（MCP 経由）で次の4点が見つかった。メインが原因を確かめてある。

1. `get_occurrences` で eDNA に絞ったアユの件数が 42 件。原本の検出は 122 件ある。
   - 原因: species_years・species_catalog が grid01 系列から数えている。座標のある検出しか入らない（eDNA は検出の 39% だけに座標がある）。
   - 2021年度が 0 件なのは、アユの 2021 年の 5 件が座標の無い地点だったため。
   - watershed×year 系列（place_id NULL のセルを含む）には 122 件ある。
2. `species_months` が空で返る。
   - 原因: アユの summary_species_catalog.n が 79 で、v1 の足切り SPECIES_MIN_N=80 に 1 件足りない。出典で絞ったかどうかには関係しない。理由を返していないのが問題。
3. MCP の未知の引数（例 `bogus_param`）が、黙って捨てられる。
4. 注記: 結果に含まれない出典の注記（GBIF の途切れなど）まで付く。facetsForOccurrence が organism_records 系の注記を常に足しているため。

## オーナー決定
件数 n は、日付のある全記録で数える（座標の無い記録も含める）。meshN（格子の数）は、座標のある記録の grid01 で数える。応答には、出典別の「座標が無いため格子に置けなかった件数」を機械的に出す。

GBIF・iNaturalist は全件に座標があるので、n は変わらないはず（変われば理由を調べる）。変わるのは eDNA とクマ目撃。

## 担当 A: 件数の定義（パイプライン・集計層）
- 対象: `aggregations/serving.yaml`（summary_species_catalog・summary_group_year・summary_effort_year のうち、n を出すもの）、`scripts/b13_build_summary.py`（語彙の拡張が要るときだけ）、`web/src/lib/cube/occurrence.ts`・`catalog.ts`（speciesYears・speciesCatalog と、その source 指定の経路）。
- 定義: n は watershed×year 系列（place_id NULL のセルを含む。dated の全記録）から取る。meshN・mesh_n は grid01 から取る。
  - 年の扱い（survey_period 等）は既存の grid01 側の定義にそろえる。2系列の期間の対応を確かめる。
  - 月の系列は grid01 にしかない。species_months は今のまま grid01 で数え、座標なしの件数を出せるかを判断する。watershed×month 系列を b07 に足すのは、キューブが膨らむので避けたい。必要なら理由を書いて提案する。
- 応答の `coverage`（または既存の envelope の適切な場所）に、出典別・年別の no_coordinate 件数を出す（= watershed 系列の n − grid01 系列の n）。MCP の get_occurrences と AI の get_biota_trend の両方。
- 受け入れ基準（メインが本物で検査する。担当は fixture で同じ検査をテストにする）:
  - 本物の v2 で、eDNA に絞った speciesYears の n が、ryuiki.sqlite の edna_detections を「taxon の canonical_binomial × 採水年」で数えた件数と全行一致する（canonical_binomial の無い name_only は除く）。
  - GBIF・iNat に絞った n は、変更前と全行一致する。
  - species_catalog の n も同じ定義。出典の指定あり／なしの両経路が一致する検査は残す。

## 担当 B: MCP の入力検査・注記・空の理由
- 対象: `web/src/lib/mcp/tools.ts`、`web/src/lib/cube/caveats.ts`（facetsForOccurrence）、関連テスト。
- 未知の引数: MCP のツールの入力スキーマを、未知のキーで isError を返す形にする（zod の strictObject 等。z.tuple は使わない）。AI 側（ai/tools.ts）は、モデルが余計なキーを付けて詰まるのを避けるため、今回は対象外。
- 注記: organism_records 系の注記（organismSite・effort・regimes・gbifCutoff・share など）を、それぞれが関係する出典の facet に紐づける。結果に含まれる出典の注記だけが付くようにする。どの注記がどの出典に関係するかは、registry/caveat_scope.yaml の既存の scope と各注記の本文から決める。scope の付け替えが要るなら registry を直す（注記の本文は変えない。本文を変えるならオーナー確認が要るので報告して止まる）。
  - 受け入れ: eDNA だけに絞ると eDNA の4件だけ（＋出典に依らない共通の注記があればそれ）。GBIF だけに絞ると eDNA の注記は付かない。未指定なら今と同じ集合。
- 空の理由: species_months・species_mesh_years が SPECIES_MIN_N の足切りで空になったときは、どの種が何件で足切りされたかを応答に出す（例: `suppressed: [{binom, n, min_n: 80}]`）。足切りそのものは外さない。
