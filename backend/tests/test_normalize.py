"""TDD — normalize.py (IC§9): vessel name + ISO 6346 container validation."""

import pytest

from app.core.normalize import normalize_container_no, normalize_vessel_name


class TestNormalizeVesselName:
    def test_trim_collapse_upper(self):
        assert normalize_vessel_name("  ever  given ") == "EVER GIVEN"

    def test_mixed_case_and_tabs(self):
        assert normalize_vessel_name("\tEver\t Given\n") == "EVER GIVEN"

    def test_already_normalized(self):
        assert normalize_vessel_name("EVER GIVEN") == "EVER GIVEN"


class TestNormalizeContainerNo:
    def test_iso_6346_reference_example(self):
        # IC§9 canonical example — check-digit 3 is correct
        assert normalize_container_no("csqu 305438-3") == "CSQU3054383"

    def test_plain_valid(self):
        assert normalize_container_no("CSQU3054383") == "CSQU3054383"

    def test_seed_containers_valid(self):
        # all 4 seed containers (IC§13 / seed.py) must pass validation
        for c in ("CSQU3054383", "MSKU9070323", "TGHU7654320", "CBHU8437299"):
            assert normalize_container_no(c) == c

    def test_wrong_check_digit_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQU3054384")

    def test_bad_format_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("ABC12345678")  # 3 letters

    def test_too_short_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("CSQU305438")

    def test_lowercase_digits_in_prefix_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("C5QU3054383")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            normalize_container_no("")
