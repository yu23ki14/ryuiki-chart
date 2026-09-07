"""scripts/b01_derived_baseline.py の決定論テスト。

「同じ derived.sqlite に対して2回実行するとバイト単位で一致する」
（docs/plans/PHASE_B_RECONCILIATION.md, scripts/r01_build_registry.py と同じ基準）を、
フィクスチャ sqlite に対して確認する。b01 は自前で作った sqlite しか読まないので、
本物の 14GB の derived.sqlite が無い CI でも実行できる。
"""
import json
import subprocess
import sys

import b01_derived_baseline as b01

from .fixtures import make_fixture_db

ROOT = b01.ROOT


def test_build_baseline_twice_yields_identical_json(tmp_path):
    db_path = tmp_path / "fixture.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")

    baseline1, _ = b01.build_baseline(db_path, keys_yaml)
    baseline2, _ = b01.build_baseline(db_path, keys_yaml)

    out1 = tmp_path / "out1.json"
    out2 = tmp_path / "out2.json"
    b01.write_json(baseline1, out1)
    b01.write_json(baseline2, out2)

    assert out1.read_bytes() == out2.read_bytes()


def test_build_baseline_json_has_no_nondeterministic_fields(tmp_path):
    """実行時刻・ホスト名のような非決定的な値を埋め込んでいないことの回帰テスト。"""
    db_path = tmp_path / "fixture.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")

    baseline, _ = b01.build_baseline(db_path, keys_yaml)
    dumped = json.dumps(baseline)
    for forbidden in ("generated_at", "timestamp", "hostname", "created_at"):
        assert forbidden not in dumped


def test_render_markdown_is_deterministic(tmp_path):
    db_path = tmp_path / "fixture.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")
    baseline, key_sources = b01.build_baseline(db_path, keys_yaml)

    destinations = {}
    md1 = b01.render_markdown(baseline, destinations, key_sources)
    md2 = b01.render_markdown(baseline, destinations, key_sources)
    assert md1 == md2
    assert "t_dims" in md1
    assert "t_pk" in md1


def test_render_markdown_shows_declared_key_reason(tmp_path):
    """回帰テスト（レビュー指摘 A-5）。`derived_keys.yaml` の宣言キーには
    「なぜ自動で決まらないか」の理由が必ず添えられる決まりなので、
    `derived_baseline.md` の「キーの由来の内訳」節にもその理由を出す。
    """
    db_path = tmp_path / "fixture.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    reason = "テスト用の宣言理由: この列組み合わせでなければ一意にならないため"
    keys_yaml.write_text(
        f"t_dims:\n  key: [site, year, kind]\n  reason: \"{reason}\"\n",
        encoding="utf-8",
    )
    baseline, key_sources = b01.build_baseline(db_path, keys_yaml)
    assert baseline["tables"]["t_dims"]["key_source"] == "declared"

    md = b01.render_markdown(baseline, {}, key_sources)
    assert "t_dims" in md
    assert reason in md


def test_cli_two_runs_are_byte_identical(tmp_path):
    """実際に CLI（サブプロセス）を2回起動して比較する、より実環境に近い確認。"""
    db_path = tmp_path / "fixture.sqlite"
    make_fixture_db(db_path, include_dupe=False)
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")
    destinations_yaml = tmp_path / "destinations.yaml"
    destinations_yaml.write_text("{}\n", encoding="utf-8")

    script = ROOT / "scripts" / "b01_derived_baseline.py"

    def run(out_json, out_md):
        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--db",
                str(db_path),
                "--keys-yaml",
                str(keys_yaml),
                "--destinations-yaml",
                str(destinations_yaml),
                "--out-json",
                str(out_json),
                "--out-md",
                str(out_md),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return result

    out_json1, out_md1 = tmp_path / "b1.json", tmp_path / "b1.md"
    out_json2, out_md2 = tmp_path / "b2.json", tmp_path / "b2.md"
    run(out_json1, out_md1)
    run(out_json2, out_md2)

    assert out_json1.read_bytes() == out_json2.read_bytes()
    assert out_md1.read_bytes() == out_md2.read_bytes()


def test_all_fixture_tables_get_a_key_source_recorded(tmp_path):
    keys_yaml = tmp_path / "derived_keys.yaml"
    keys_yaml.write_text("{}\n", encoding="utf-8")

    # t_dupe は宣言が無いと例外で止まる設計（common.py 側で個別にテスト済み）。
    # ここでは t_pk / t_dims の2テーブルだけの DB で baseline が作れることを確認する。
    only_ok_tables = tmp_path / "ok_only.sqlite"
    make_fixture_db(only_ok_tables, include_dupe=False)

    baseline, key_sources = b01.build_baseline(only_ok_tables, keys_yaml)
    assert set(baseline["tables"]) == {"t_pk", "t_dims"}
    assert baseline["tables"]["t_pk"]["key_source"] == "pk"
    assert baseline["tables"]["t_dims"]["key_source"] == "auto"
    assert key_sources == {"pk": 1, "auto": 1}
