"""x01_dwca: organism_records.occurrence_status → DwC occurrenceStatus（不在記録を present と書かない）。"""
import x01_dwca


def test_absent_is_written_as_absent_everything_else_as_present():
    assert x01_dwca.dwc_occurrence_status("ABSENT") == "absent"
    assert x01_dwca.dwc_occurrence_status("PRESENT") == "present"
    assert x01_dwca.dwc_occurrence_status(None) == "present"  # iNaturalist 等（不在の概念が無い出典）
