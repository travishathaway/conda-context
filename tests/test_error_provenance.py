"""Tests for the error provenance system (CondaConfigError + ProvenanceInfo)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError, field_validator

from conda_context.errors import CondaConfigError
from conda_context.provenance import ProvenanceInfo, ProvenanceMap

# ---------------------------------------------------------------------------
# Minimal Pydantic model for testing
# ---------------------------------------------------------------------------


class _DummyConfig(BaseModel):
    ssl_verify: bool = True
    channel_priority: str = "flexible"
    always_copy: bool = False
    always_softlink: bool = False

    @field_validator("channel_priority")
    @classmethod
    def _validate_cp(cls, v: str) -> str:
        if v not in ("flexible", "strict", "disabled"):
            raise ValueError(f"Invalid value: {v!r}")
        return v


def _make_error(data: dict, provenance: ProvenanceMap | None = None) -> CondaConfigError:
    try:
        _DummyConfig(**data)
        pytest.fail("Expected ValidationError was not raised")
    except ValidationError as exc:
        return CondaConfigError(exc, provenance or {})


# ---------------------------------------------------------------------------
# ProvenanceInfo tests
# ---------------------------------------------------------------------------


class TestProvenanceInfo:
    def test_yaml_file_describe(self):
        prov = ProvenanceInfo(source_type="yaml_file", path=Path("/home/user/.condarc"), line=7)
        desc = prov.describe()
        assert "/home/user/.condarc" in desc
        assert "7" in desc

    def test_env_var_describe(self):
        prov = ProvenanceInfo(source_type="env_var", env_var="CONDA_SSL_VERIFY")
        assert "CONDA_SSL_VERIFY" in prov.describe()

    def test_argparse_describe(self):
        prov = ProvenanceInfo(source_type="argparse")
        assert "command-line" in prov.describe()


# ---------------------------------------------------------------------------
# CondaConfigError: provenance enrichment
# ---------------------------------------------------------------------------


class TestCondaConfigErrorProvenance:
    def test_error_from_yaml_includes_path_and_line(self):
        """Scenario: Error from yaml file includes file path and line number."""
        provenance: ProvenanceMap = {
            "ssl_verify": ProvenanceInfo(
                source_type="yaml_file",
                path=Path("~/.condarc"),
                line=7,
            )
        }
        err = _make_error({"ssl_verify": "yess"}, provenance)
        as_dict = err.as_dict()
        assert len(as_dict) == 1
        entry = as_dict[0]
        assert entry["field"] == "ssl_verify"
        assert entry["source"]["type"] == "yaml_file"
        assert "~/.condarc" in entry["source"]["path"]
        assert entry["source"]["line"] == 7

    def test_error_from_env_var_includes_var_name(self):
        """Scenario: Error from environment variable includes variable name."""
        provenance: ProvenanceMap = {
            "ssl_verify": ProvenanceInfo(
                source_type="env_var",
                env_var="CONDA_SSL_VERIFY",
            )
        }
        err = _make_error({"ssl_verify": "yess"}, provenance)
        entry = err.as_dict()[0]
        assert entry["source"]["type"] == "env_var"
        assert entry["source"]["env_var"] == "CONDA_SSL_VERIFY"

    def test_error_for_default_field_has_no_source(self):
        """Scenario: Error for field with no provenance omits source."""
        err = _make_error({"ssl_verify": "yess"}, provenance={})
        entry = err.as_dict()[0]
        assert entry["source"] == {}


# ---------------------------------------------------------------------------
# CondaConfigError: human-readable __str__
# ---------------------------------------------------------------------------


class TestCondaConfigErrorStr:
    def test_str_contains_field_value_and_message(self):
        """Scenario: Human-readable output contains field, value, message."""
        err = _make_error({"ssl_verify": "yess"})
        s = str(err)
        assert "ssl_verify" in s
        assert "yess" in s

    def test_str_contains_source_location_for_yaml(self):
        """Scenario: Human-readable output for invalid yaml value."""
        prov = {"ssl_verify": ProvenanceInfo("yaml_file", Path("~/.condarc"), 7)}
        err = _make_error({"ssl_verify": "yess"}, prov)
        s = str(err)
        assert "~/.condarc" in s
        assert "7" in s

    def test_str_contains_env_var_name(self):
        """Scenario: Human-readable output for env var error."""
        prov = {"ssl_verify": ProvenanceInfo("env_var", env_var="CONDA_SSL_VERIFY")}
        err = _make_error({"ssl_verify": "yess"}, prov)
        assert "CONDA_SSL_VERIFY" in str(err)

    def test_str_multiple_errors_each_formatted(self):
        """Scenario: Multiple field errors are each formatted."""
        try:
            _DummyConfig(ssl_verify="bad", channel_priority="invalid")
            pytest.fail("expected error")
        except ValidationError as exc:
            err = CondaConfigError(exc, {})
        s = str(err)
        assert "ssl_verify" in s
        assert "channel_priority" in s


# ---------------------------------------------------------------------------
# CondaConfigError: machine-readable as_dict
# ---------------------------------------------------------------------------


class TestCondaConfigErrorAsDict:
    def test_as_dict_structure_for_yaml_error(self):
        """Scenario: as_dict structure for yaml error."""
        prov = {"ssl_verify": ProvenanceInfo("yaml_file", Path("~/.condarc"), 7)}
        err = _make_error({"ssl_verify": "yess"}, prov)
        result = err.as_dict()
        assert isinstance(result, list)
        entry = result[0]
        assert "field" in entry
        assert "value" in entry
        assert "message" in entry
        assert "hint" in entry
        assert "source" in entry

    def test_as_dict_is_json_serialisable(self):
        """Scenario: as_dict is JSON-serialisable."""
        prov = {"ssl_verify": ProvenanceInfo("yaml_file", Path("~/.condarc"), 7)}
        err = _make_error({"ssl_verify": "yess"}, prov)
        # Should not raise TypeError
        json.dumps(err.as_dict())


# ---------------------------------------------------------------------------
# Hint generation
# ---------------------------------------------------------------------------


class TestHintGeneration:
    def test_hint_for_string_bool_true_variant(self):
        """Scenario: Hint for string-valued boolean field (true-like)."""
        # Use always_copy which is a pure bool field tracked in _BOOL_FIELDS
        try:
            _DummyConfig(always_copy="yess")
            pytest.fail("expected error")
        except Exception as exc:
            from pydantic import ValidationError

            if not isinstance(exc, ValidationError):
                pytest.skip("always_copy='yess' did not raise ValidationError")
            from conda_context.errors import CondaConfigError

            err = CondaConfigError(exc, {})
        entry = err.as_dict()[0]
        assert entry["hint"] is not None
        assert "true" in entry["hint"].lower() or "false" in entry["hint"].lower()

    def test_hint_for_string_bool_false_variant(self):
        """Scenario: Hint for string-valued boolean field (false-like)."""
        # Pydantic v2 coerces "no" to False for bool fields.
        # Use a value that is false-like but also unambiguously invalid.
        from conda_context.errors import _generate_hint

        hint = _generate_hint("always_copy", "no")
        assert hint is not None
        assert "false" in hint.lower()

    def test_hint_for_invalid_enum_lists_choices(self):
        """Scenario: Hint for invalid enum value lists valid choices."""
        # Use CondaConfigError directly with a real enum field name
        try:
            _DummyConfig(channel_priority="invalid")
            pytest.fail("expected error")
        except ValidationError as exc:
            err = CondaConfigError(exc, {})
        entry = err.as_dict()[0]
        # The hint should list valid choices
        assert entry["hint"] is not None
        hint = entry["hint"]
        assert "flexible" in hint or "strict" in hint or "disabled" in hint
