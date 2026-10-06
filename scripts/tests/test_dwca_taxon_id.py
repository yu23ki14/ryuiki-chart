"""DwC-A の taxonID の名前空間前置（Issue #34 D4）: 書き出し側 `dwca_taxon_id` と検証側 x03。"""
import pytest

import x03_verify_dwca as x03
from taxon_namespaces import check_dwca_taxon_id, dwca_taxon_id


def test_dwca_taxon_id_prefixes_namespace_by_source():
    assert dwca_taxon_id("gbif_kanagawa_occurrences", "8026") == "gbif:8026"
    assert dwca_taxon_id("inaturalist_kanagawa", 8026) == "inat:8026"
    assert dwca_taxon_id("inaturalist_kanagawa", None) == ""
    assert dwca_taxon_id("gbif_kanagawa_occurrences", "") == ""


def test_dwca_taxon_id_rejects_unknown_source_with_key():
    with pytest.raises(ValueError):
        dwca_taxon_id("mystery", "1")
    assert dwca_taxon_id("mystery", "") == ""


def test_check_accepts_matching_and_empty_rejects_bare_wrong_namespace_and_bad_format():
    gbif_oid = "gbif_kanagawa_occurrences__12"
    assert check_dwca_taxon_id("", gbif_oid) is None
    assert check_dwca_taxon_id("gbif:8026", gbif_oid) is None
    assert check_dwca_taxon_id("8026", gbif_oid)            # 前置なし
    assert check_dwca_taxon_id("inat:8026", gbif_oid)       # 名前空間の取り違え
    assert check_dwca_taxon_id("gbif:abc", gbif_oid)        # 形式
    assert check_dwca_taxon_id("foo:1", gbif_oid)
    # 公開 ID 形式（Issue #39 Phase C）
    assert check_dwca_taxon_id("gbif:8026", "common:occ:gbif.12") is None
    assert check_dwca_taxon_id("inat:8026", "common:occ:gbif.12")  # 名前空間の取り違え


def _write_archive(d, taxon_id):
    cols_ev = ["eventID", "eventDate"]
    cols_oc = ["occurrenceID", "eventID", "scientificName", "taxonID"]
    cols_em = ["eventID"]
    (d / "event.txt").write_text("\t".join(cols_ev) + "\nev1\t2020-01-01\n", encoding="utf-8")
    (d / "occurrence.txt").write_text(
        "\t".join(cols_oc) + f"\ngbif_kanagawa_occurrences__1\tev1\tFoo bar\t{taxon_id}\n", encoding="utf-8")
    (d / "extendedmeasurementorfact.txt").write_text("\t".join(cols_em) + "\nev1\n", encoding="utf-8")
    fields = lambda cols: "".join(f'<field index="{i+1}" term="{c}"/>' for i, c in enumerate(cols[1:]))
    (d / "meta.xml").write_text(
        '<archive xmlns="http://rs.tdwg.org/dwc/text/">'
        f'<core><files><location>event.txt</location></files>{fields(cols_ev)}</core>'
        f'<extension><files><location>occurrence.txt</location></files>{fields(cols_oc)}</extension>'
        f'<extension><files><location>extendedmeasurementorfact.txt</location></files>{fields(cols_em)}</extension>'
        '</archive>', encoding="utf-8")


def test_x03_passes_with_prefixed_taxon_id_and_fails_without(tmp_path, monkeypatch):
    monkeypatch.setattr(x03, "D", tmp_path)
    _write_archive(tmp_path, "gbif:8026")
    assert x03.main() == 0
    _write_archive(tmp_path, "8026")
    assert x03.main() == 1
    _write_archive(tmp_path, "inat:8026")
    assert x03.main() == 1
