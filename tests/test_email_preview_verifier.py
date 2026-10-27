"""Post-generation numeric checks operate on synthetic preview text only."""

from idx_agent.email.verify import verify_preview_numbers


def test_catches_altered_square_feet_without_logging_the_numbers(capsys):
    result = verify_preview_numbers(
        "Home 1\n$719,000\n2 beds · 960 sqft",
        "Home 1\n$719,000\n2 beds · 1,240 sqft",
        trace_id="abc123",
    )
    assert result.status == "mismatch"
    assert result.mismatch_count == 1
    logged = capsys.readouterr().err
    assert '"event": "draft_preview_numeric_mismatch"' in logged
    assert '"trace_id": "abc123"' in logged
    assert '"mismatch_count": 1' in logged
    assert "960" not in logged and "1,240" not in logged and "719,000" not in logged


def test_same_numbers_allow_numeric_formatting_changes(capsys):
    result = verify_preview_numbers(
        "Price $1,240.00; 960 sqft", "Price $1240; 960 sqft", trace_id="abc123"
    )
    assert result.status == "match"
    assert result.mismatch_count == 0
    assert capsys.readouterr().err == ""


def test_reordering_additions_and_missing_numbers_are_mismatches():
    for reply in ("960 sqft, 2 beds", "2 beds, 960 sqft, 5 baths", "2 beds"):
        assert (
            verify_preview_numbers("2 beds, 960 sqft", reply, trace_id="abc123").status
            == "mismatch"
        )


def test_absent_or_unusable_inputs_are_not_treated_as_a_pass():
    for payload, reply, trace in (
        (None, "960", "abc"),
        ("960", None, "abc"),
        ("none", "none", "abc"),
        ("960", "960", "bad trace!"),
        ("x" * 100_001, "960", "abc"),
    ):
        assert (
            verify_preview_numbers(payload, reply, trace_id=trace).status
            == "unavailable"
        )


def test_same_numbers_attached_to_wrong_fields_do_not_pass():
    result = verify_preview_numbers(
        "2 beds, 960 sqft", "2 sqft, 960 beds", trace_id="abc123"
    )
    assert result.status == "mismatch"
    assert result.mismatch_count == 2
