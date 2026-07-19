"""Tests for the CondarC write API."""

from __future__ import annotations

from pathlib import Path

import pytest

from conda_context.condarc import CondarC
from conda_context.errors import CondaConfigError


def _write_condarc(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------


class TestLoad:
    def test_load_existing_file(self, tmp_path):
        """Scenario: Load existing file returns CondarC with all pairs."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\noffline: true\n")
        c = CondarC.load(rc)
        assert c.get("ssl_verify") is False
        assert c.get("offline") is True

    def test_load_nonexistent_raises(self, tmp_path):
        """Scenario: Load non-existent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            CondarC.load(tmp_path / "nonexistent.condarc")

    def test_comments_preserved_after_round_trip(self, tmp_path):
        """Scenario: Comments are preserved after round-trip."""
        content = "# My important comment\nssl_verify: true\n"
        rc = _write_condarc(tmp_path, ".condarc", content)
        c = CondarC.load(rc)
        c.set("offline", True)
        c.save()
        written = rc.read_text()
        assert "# My important comment" in written


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


class TestCreate:
    def test_create_does_not_write_to_disk(self, tmp_path):
        """Scenario: Create does not write to disk immediately."""
        target = tmp_path / "new.condarc"
        CondarC.create(target)
        assert not target.exists()

    def test_save_after_create_writes_file(self, tmp_path):
        """Scenario: Save after create writes a valid YAML file."""
        target = tmp_path / "new.condarc"
        CondarC.create(target).set("ssl_verify", False).save()
        assert target.exists()
        content = target.read_text()
        assert "ssl_verify" in content


# ---------------------------------------------------------------------------
# set / get / get_all
# ---------------------------------------------------------------------------


class TestSetGet:
    def test_set_new_scalar_key(self, tmp_path):
        """Scenario: Set a new scalar key."""
        c = CondarC.create(tmp_path / "test.condarc")
        c.set("ssl_verify", False)
        assert c.get("ssl_verify") is False

    def test_set_overrides_existing_key(self, tmp_path):
        """Scenario: Set overrides an existing key."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: true\n")
        c = CondarC.load(rc)
        c.set("ssl_verify", False)
        assert c.get("ssl_verify") is False

    def test_set_invalid_type_raises_immediately(self, tmp_path):
        """Scenario: Set with invalid type raises immediately."""
        c = CondarC.create(tmp_path / "test.condarc")
        with pytest.raises((CondaConfigError, Exception)):
            c.set("ssl_verify", "yess")

    def test_get_all_returns_all_keys(self, tmp_path):
        """Scenario: get_all returns only this file's keys."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\nchannels:\n  - defaults\n")
        c = CondarC.load(rc)
        result = c.get_all()
        assert "ssl_verify" in result
        assert "channels" in result
        assert result["ssl_verify"] is False


# ---------------------------------------------------------------------------
# unset
# ---------------------------------------------------------------------------


class TestUnset:
    def test_unset_removes_key(self, tmp_path):
        """Scenario: Unset removes key."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\n")
        c = CondarC.load(rc)
        c.unset("ssl_verify")
        assert c.get("ssl_verify") is None

    def test_unset_absent_key_is_noop(self, tmp_path):
        """Scenario: Unset on absent key is a no-op."""
        c = CondarC.create(tmp_path / "test.condarc")
        c.unset("ssl_verify")  # should not raise


# ---------------------------------------------------------------------------
# List mutations
# ---------------------------------------------------------------------------


class TestListMutations:
    def test_prepend_channel(self, tmp_path):
        """Scenario: prepend_channel adds channel to front."""
        rc = _write_condarc(tmp_path, ".condarc", "channels:\n  - defaults\n")
        c = CondarC.load(rc)
        c.prepend_channel("pytorch")
        assert c.get("channels") == ["pytorch", "defaults"]

    def test_append_channel(self, tmp_path):
        """Scenario: append_channel adds channel to back."""
        rc = _write_condarc(tmp_path, ".condarc", "channels:\n  - defaults\n")
        c = CondarC.load(rc)
        c.append_channel("conda-forge")
        assert c.get("channels") == ["defaults", "conda-forge"]

    def test_remove_from_removes_value(self, tmp_path):
        """Scenario: remove_from removes a specific value."""
        rc = _write_condarc(tmp_path, ".condarc", "channels:\n  - pytorch\n  - defaults\n")
        c = CondarC.load(rc)
        c.remove_from("channels", "pytorch")
        assert c.get("channels") == ["defaults"]

    def test_remove_from_absent_value_is_noop(self, tmp_path):
        """Scenario: remove_from absent value is a no-op."""
        rc = _write_condarc(tmp_path, ".condarc", "channels:\n  - defaults\n")
        c = CondarC.load(rc)
        c.remove_from("channels", "nonexistent")  # should not raise
        assert c.get("channels") == ["defaults"]


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------


class TestSave:
    def test_save_writes_atomically_no_partial_write_on_error(self, tmp_path):
        """Scenario: Save with validation error leaves file unchanged."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: true\n")
        original_content = rc.read_text()
        c = CondarC.load(rc)
        # Manually corrupt the data to trigger cross-field error
        c._data["always_copy"] = True
        c._data["always_softlink"] = True
        with pytest.raises((CondaConfigError, Exception)):
            c.save(strict=True)
        # File should be unchanged
        assert rc.read_text() == original_content

    def test_save_strict_false_skips_cross_field(self, tmp_path):
        """Scenario: Save with strict=False skips cross-field validation."""
        rc = _write_condarc(tmp_path, ".condarc", "offline: false\n")
        c = CondarC.load(rc)
        c.set("offline", True)
        # Should succeed even if strict=False
        c.save(strict=False)
        assert "offline" in rc.read_text()


# ---------------------------------------------------------------------------
# diff
# ---------------------------------------------------------------------------


class TestDiff:
    def test_diff_reflects_pending_mutations(self, tmp_path):
        """Scenario: diff reflects pending mutations."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: true\n")
        c = CondarC.load(rc)
        c.set("ssl_verify", False)
        d = c.diff()
        assert "ssl_verify" in d
        assert d["ssl_verify"] == (True, False)

    def test_diff_empty_before_mutations(self, tmp_path):
        """Scenario: diff is empty before any mutations."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: true\n")
        c = CondarC.load(rc)
        assert c.diff() == {}
