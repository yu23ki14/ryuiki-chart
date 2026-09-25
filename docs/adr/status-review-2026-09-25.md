# ADR 状態判定の根拠（2026-09-25）

[README](README.md) の状態列（`提案中` / `承認済`）を26本すべてについて1本ずつ判定した根拠を
ここに残す。判定基準は README に書いたとおり:

> `承認済` は「決定がコードとして実装され、実データのゲートまたはテストで検証されたもの」に限る
> （方針だけが固まっている、実装が計画されている、はここに含まない）。決定が複数の項目からなり、
> 一部だけが実装・検証されている場合は `承認済（一部未実装: ...）` のように未実装の範囲を
> 具体的に注記する。それ以外は `提案中` のまま置く。

このファイルは ADR 番号を持たない判定記録であり、[README](README.md) の一覧表には**載せない**
（一覧は決定そのものを持つ ADR ファイルだけを載せる）。2026-09-25、Issue #36 の実装として作成。

## 承認済（14本）

| ADR | 状態 | 根拠（ファイル:行） |
|---|---|---|
| [0004](0004-identifiers.md) 識別子 | 承認済（一部未実装） | scoped ID (`<scope>:<entity>:<local_key>`) を registry 全体で発行（`scripts/registry/build_place.py`、`scripts/taxon_namespaces.py`）。不変条件は `scripts/r01_build_registry.py:291` `_assert_region_id_scope_invariant()`（`:646` で呼び出し）が全行検証。一部未実装: 規約1の区切り文字問題は `docs/adr/0004-identifiers.md` 2026-09-25追記、`docs/plans/PHASE_B_INTAKE.md:30`（#12） |
| [0006](0006-place-registry.md) place レジストリ | 承認済（一部未実装） | `place`/`place_relation`/`place_source_ref` を実装（`scripts/registry/build_place.py`）、`place_watershed` サテライトは `docs/plans/PHASE_B_PLACE_ATTRIBUTES.md`、点→流域解決は `scripts/b09_build_occurrence_place.py`（ADR-0026「実測」節で機械検証6件・完全一致）。一部未実装: `feature`（`protected_areas`等）への統合、`sites.municipality`の水域名混入解消は未着手（`docs/adr/0006-place-registry.md:101`「`sites.municipality` の混入は移行時に解消する」に対応する実装が見つからない） |
| [0007](0007-observation-fact.md) observation | 承認済 | `scripts/b03_build_observation.py` が `observation` テーブルを構築。`docs/plans/PHASE_B_FACT_SLICE.md:3`「状態: 実データで一度緑になった」、`docs/plans/PHASE_B_RECONCILIATION.md:885-894`「Phase B の全体の合格」で最終的に33テーブル全数の再現を確認 |
| [0008](0008-time-representation.md) 時間3点セット | 承認済 | `period_start`/`period_end`/`grain` を `observation`（b03）・`occurrence`（`scripts/b06_build_occurrence.py`）双方に実装。ADR-0008本体の2026-09-08/09-15追記がADR-0021/0024による拡張実装を確認済みと記録 |
| [0009](0009-censored-values.md) 検閲 | 承認済（一部未実装） | `scripts/migrate/censoring.py` が `censoring`/`censoring_limit`/`value_num=NULL` を実装、`scripts/b03_build_observation.py:985` が `imputation='zero'` の代入行数を検証、`scripts/b04_build_cube.py:91`「## imputation='zero'」。一部未実装: 決定4のlod併記は Issue #30（`意図的な変更: 定量下限のlod併記と、v1の検閲判定バグの決着`）で未着手 |
| [0010](0010-variable-registry.md) 指標レジストリ | 承認済 | `registry/variable.yaml`/`variable_alias` を実装、`web/src/lib/registry/generated.test.ts` が陳腐化を検知、`docs/plans/PHASE_B_INTAKE.md`「#1・#7を解決した本PR」節・`docs/plans/PHASE_B_LANDUSE.md`（P-1b、2026-09-24追記）で実データ検証 |
| [0011](0011-aggregation-cube.md) キューブ | 承認済 | `observation_agg`（`scripts/b04_build_cube.py:389` `build_cube()`）・`occurrence_agg`（`scripts/b07_build_occurrence_cube.py`）を実装。`docs/plans/PHASE_B_RECONCILIATION.md:556`「12. 全体の合格」・`:885-894` で v1派生33テーブル全数の一致（一致25/宣言済み差分8/不一致0）を確認 |
| [0016](0016-migration-plan.md) 移行計画 | 承認済（一部未実装） | Phase A・Bの受け入れ基準（v1数値の再現）を `scripts/b02_run_all_gates.py` で33テーブル全数について確認（`docs/plans/PHASE_B_RECONCILIATION.md:885-894`）。一部未実装: Phase C・Dは未着手（本ファイル記載の各ADRの「Phase C/D」送りの項目が該当） |
| [0019](0019-taxon-registry.md) taxon レジストリ | 承認済 | `scripts/registry/build_taxon.py`（namespace分割）・`scripts/registry/build_taxon_assessment.py`（`taxon_assessment`）を実装、`docs/plans/PHASE_B_TAXON_ASSESSMENT.md`・`docs/plans/PHASE_B_OCCURRENCE.md`（F1〜F4の実測、`org_norm`816,856行の差分0確認）で検証 |
| [0021](0021-observation-grain-and-cube-key.md) 粒度・キューブ鍵 | 承認済 | `scripts/b04_build_cube.py:37-38`（`obs_stat`/`value_grain`/`input_grain` を次元キーに追加）を実装、`docs/plans/PHASE_B_FACT_SLICE.md` §9〜10 で実測・検証（`atsugi_river_water_quality` 3,840行の食い違い件数が宣言と一致） |
| [0022](0022-place-region-scope.md) region_id/place_relation | 承認済（一部未実装） | 決定1・2を `scripts/registry/build_place.py`・`scripts/r01_build_registry.py:291,646` で実装・機械検証（実測: common→NULL 4,460件、jp-14→jp-14 500件、辺290件）。一部未実装: 決定3（`observation`/`occurrence`の region決め方統一）は `docs/adr/0022-place-region-scope.md:108`「先取りしている」が明記する既知の結合のまま、決定4（地域そのものを表すplace）も未着手 |
| [0024](0024-local-time-and-time-labels.md) 時刻帯・ラベル | 承認済（一部未実装） | `scripts/migrate/time_label_conventions.yaml`・`scripts/b03_build_observation.py`（hour_ending変換）・`scripts/b05_project_v1.py:934` `verify_hourly_daily_rollup()`（`:1089`で呼び出し）で機械検証。一部未実装: 「時刻帯は地域の属性」の結線は `scripts/migrate/source_regions.yaml`（occurrence側、ADR-0025 D1）のみで、`observation`側は `docs/adr/0024-local-time-and-time-labels.md` 本文「注意」節が自ら「未接続」と明記 |
| [0025](0025-occurrence-fact-and-cube.md) occurrence fact/cube | 承認済（一部未実装） | `scripts/b06_build_occurrence.py`（D1）・`scripts/b07_build_occurrence_cube.py`（D2）・`scripts/b08_project_occurrence_v1.py:1138` `build_occurrence_cube_projections()`（D3）が存在し、`docs/plans/PHASE_B_RECONCILIATION.md:885-894` の全体ゲートで検証。一部未実装: D4（`occurrence_agg`への`place_kind='watershed'`セル追加）は `docs/adr/0025-occurrence-fact-and-cube.md:128`「O-2 への申し送り」節が明記するとおりO-2bへ |
| [0026](0026-occurrence-place-watershed.md) occurrence_place | 承認済（一部未実装） | `scripts/b09_build_occurrence_place.py`を実装。ADR本文「実測」節（`docs/adr/0026-occurrence-place-watershed.md:189-219`）に機械検証1〜6の実測値（母集団823,692、解決737,407、際どい交差0、`org_watershed_year`/`org_watershed`完全一致）を記載。一部未実装: D4は0025と同じくO-2bへ |

## 提案中のまま（12本）

| ADR | 状態 | 根拠（不実装・不足の裏付け） |
|---|---|---|
| [0001](0001-storage-layers.md) Parquet/R2 | 提案中 | `core/*.parquet`/`cube/*.parquet`層が存在しない。データは一貫して sqlite（`data/db/*.sqlite`）と D1。`grep -rl "core/\*\.parquet"` 相当の実装ファイルなし |
| [0002](0002-multi-region.md) 多地域 | 提案中 | region_idパーティション機構自体は0004/0022経由で実装済みだが、ADR-0002本文に実装追記が無く、対象地域が神奈川県（jp-14）のみで2地域目でのストレステスト実績が無い（`docs/add_area.md`の手順は未実施） |
| [0003](0003-standards-at-the-boundary.md) 標準アダプタ | 提案中 | DwC-A書き出し `scripts/x01_dwca.py` は存在するが、`docs/plans/PHASE_B_INTAKE.md:35`（#17）が `taxonID`列の名前空間欠落を未解決と明記。SensorThings/DCATの実装は見つからない |
| [0005](0005-source-editions.md) source_edition | 提案中 | `docs/plans/PHASE_B_INTAKE.md:27`（#9）「`source_registry`/`source_edition`（ADR-0005）が実装される Phase C で置換が要る」と明記。列名としての `source_edition_id` の使用（`scripts/b03_build_observation.py`等）はあるが、版管理・行単位ライセンス解決の実体は無い |
| [0012](0012-source-manifests.md) マニフェスト | 提案中 | `scripts/migrate/source_regions.yaml`等の宣言ファイル群は前段。`docs/adr/0022-place-region-scope.md:108`「ADR-0012のマニフェストが本来持つべき`region:`欄を、この宣言ファイルとして先取りしている」とADR自身が明記＝0012本体は未実装 |
| [0013](0013-caveats.md) caveat | 提案中 | `scripts/registry/build_caveat.py` は Phase A実装のまま。`docs/plans/PHASE_B_INTAKE.md:20`（#2）「`caveat_scope.scope_kind`が...ADR-0013本来の`variable`/`place`/`source_edition`/...になっていない」と未解決を明記。Phase Bのどの縦線もcaveatを消費しない（同項目「着手判定」参照） |
| [0014](0014-response-envelope.md) 応答封筒 | 提案中 | API/MCPレスポンスのenvelope実装（`caveats`/`provenance`等の共通構造）が `web/src/app/api` 配下に見つからない |
| [0015](0015-domain-extensions.md) ドメイン拡張パッケージ | 提案中 | 拡張パッケージ機構の実装が見つからない |
| [0017](0017-write-path-scope.md) 書き込み系ストア | 提案中 | 本Issue（#36）で「設計をシビックテック側に委ねる」旨を追記したのみ（`docs/adr/0017-write-path-scope.md` 2026-09-25追記）。決定自体は元々「対象外」という境界宣言であり、実装対象ではない |
| [0018](0018-publication-scope.md) 公開範囲・座標一般化 | 提案中 | `publication_scope`列自体は Phase A から存在し、`scripts/m03_organisms.py:11`・`scripts/b06_build_occurrence.py:50,160,193`が値をそのまま運ぶ。README §レビュー記録（`docs/adr/README.md:183-184`）にPhase Aでの値監査記録があるが、「公開経路で強制する」という決定の中核（配信境界での座標一般化・非公開データの遮断）の実装は見つからない |
| [0020](0020-freshness-rebuild.md) 鮮度・再ビルド | 提案中 | ADR本文 `docs/adr/0020-freshness-rebuild.md:70`「ただしPhase A〜B（ADR-0016）の間はこれで良い」と自ら明記し、`update_mode`宣言・差分保存・応答への`fetched_at`同梱は未実装。`web/scripts/ensure-registry.sh`の`--check-fresh`は決定の一部（レジストリの指紋チェックのみ）で決定全体ではない |
| [0023](0023-unit-canonicalization.md) 単位正準化 | 提案中 | 決定1（出典単位のまま変換しない）は結果的に成立しているが新規実装物ではない。決定2〜4（`unit`テーブルへの`canonical_unit_id`/`scale_to_canonical`追加、キューブの二軸化）は`grep -rn "canonical_unit_id\|scale_to_canonical"`でコード上に痕跡なし。ADR本文 `docs/adr/0023-unit-canonicalization.md:99`「本ADRは方針決定であり、2026-09-15時点でコード化されていない」と明記 |

判定できなかった ADR はない（26本すべてについて実装ファイルまたはドキュメント記述による根拠を
確認できた）。
