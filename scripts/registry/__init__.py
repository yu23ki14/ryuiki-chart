"""語彙レジストリ（unit / variable / place / taxon / caveat）のビルドパッケージ。

docs/plans/PHASE_A.md §A-1 の土台。実際のデータを作るのは
build_unit_variable.py（A-2）/ build_place.py（A-3）/ build_taxon.py（A-4）/
build_caveat.py（A-5）で、それぞれ独立に並行作業できるようファイルを分けてある。
オーケストレーションは scripts/r01_build_registry.py が持つ（ここには置かない）。
"""
