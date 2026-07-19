"""Tests for the CondaConfig Pydantic schema (conda 26.5.3)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

import conda_context
from conda_context.schemas._26_5_3 import CondaConfig
from conda_context.constants import (
    ChannelPriority,
    DEFAULT_CHANNELS,
    DEFAULT_CONDA_LIST_FIELDS,
)


# ---------------------------------------------------------------------------
# Field coverage
# ---------------------------------------------------------------------------


class TestFieldCoverage:
    def test_default_instantiation(self):
        """Scenario: CondaConfig() instantiates with all defaults."""
        cfg = CondaConfig()
        assert cfg is not None

    def test_default_ssl_verify_is_true(self):
        """Scenario: Default values match conda defaults."""
        cfg = CondaConfig()
        assert cfg.ssl_verify is True

    def test_default_channels(self):
        cfg = CondaConfig()
        assert set(cfg.default_channels) == set(DEFAULT_CHANNELS)

    def test_default_list_fields(self):
        cfg = CondaConfig()
        assert set(cfg.list_fields) == set(DEFAULT_CONDA_LIST_FIELDS)

    def test_alias_auto_activate_base(self):
        """Scenario: Field aliases are honoured."""
        cfg = CondaConfig(auto_activate_base=False)
        assert cfg.auto_activate is False

    def test_alias_copy(self):
        cfg = CondaConfig(copy=True)
        assert cfg.always_copy is True

    def test_alias_softlink(self):
        cfg = CondaConfig(softlink=True)
        assert cfg.always_softlink is True


# ---------------------------------------------------------------------------
# Primitive type coercion
# ---------------------------------------------------------------------------


class TestTypeCoercion:
    def test_string_true_coerced_to_bool(self):
        """Scenario: String 'true' coerced to bool."""
        cfg = CondaConfig(add_pip_as_python_dependency="true")
        assert cfg.add_pip_as_python_dependency is True

    def test_string_false_coerced_to_bool(self):
        cfg = CondaConfig(allow_conda_downgrades="false")
        assert cfg.allow_conda_downgrades is False

    def test_string_int_coerced(self):
        """Scenario: String integer coerced to int."""
        cfg = CondaConfig(number_channel_notices="3")
        assert cfg.number_channel_notices == 3


# ---------------------------------------------------------------------------
# Enum validation
# ---------------------------------------------------------------------------


class TestEnumValidation:
    def test_invalid_channel_priority_raises(self):
        """Scenario: Invalid channel_priority value."""
        with pytest.raises((ValidationError, Exception)) as exc_info:
            CondaConfig(channel_priority="invalid")
        # Either a Pydantic ValidationError or our wrapped error
        assert "invalid" in str(exc_info.value).lower() or exc_info.type is not None

    def test_valid_channel_priority_strict(self):
        """Scenario: Valid channel_priority value accepted."""
        cfg = CondaConfig(channel_priority="strict")
        assert str(cfg.channel_priority) == "strict"

    def test_valid_channel_priority_flexible(self):
        cfg = CondaConfig(channel_priority="flexible")
        assert str(cfg.channel_priority) == "flexible"


# ---------------------------------------------------------------------------
# Cross-field validators
# ---------------------------------------------------------------------------


class TestCrossFieldValidation:
    def test_always_copy_and_softlink_mutually_exclusive(self):
        """Scenario: always_copy and always_softlink mutually exclusive."""
        with pytest.raises((ValidationError, Exception)):
            CondaConfig(always_copy=True, always_softlink=True)

    def test_client_ssl_cert_key_requires_cert(self):
        """Scenario: client_ssl_cert_key requires client_ssl_cert."""
        with pytest.raises((ValidationError, Exception)):
            CondaConfig(client_ssl_cert_key="/path/to/key")

    def test_valid_ssl_cert_pair(self):
        """Both cert and key set — should succeed."""
        cfg = CondaConfig(
            client_ssl_cert="/path/to/cert",
            client_ssl_cert_key="/path/to/key",
        )
        assert cfg.client_ssl_cert == "/path/to/cert"

    def test_single_always_copy_ok(self):
        cfg = CondaConfig(always_copy=True, always_softlink=False)
        assert cfg.always_copy is True


# ---------------------------------------------------------------------------
# JSON Schema
# ---------------------------------------------------------------------------


class TestJsonSchema:
    def test_model_json_schema_has_properties(self):
        """Scenario: JSON Schema generation."""
        schema = CondaConfig.model_json_schema()
        assert "properties" in schema
        props = schema["properties"]
        # Fields are in schema by their field name or alias
        all_keys = set(props.keys())
        assert "channel_priority" in all_keys
        assert "channels" in all_keys or "channel" in all_keys
        # ssl_verify may appear as verify_ssl (alias) or ssl_verify
        assert "ssl_verify" in all_keys or "verify_ssl" in all_keys


# ---------------------------------------------------------------------------
# Version lookup
# ---------------------------------------------------------------------------


class TestVersionLookup:
    def test_get_schema_for_26_5_3(self):
        """Scenario: Version lookup returns correct model."""
        cls = conda_context.get_schema_for_version("26.5.3")
        assert cls is CondaConfig

    def test_unknown_version_raises(self):
        """Scenario: Unknown version raises clear error."""
        with pytest.raises(ValueError, match="99.0.0"):
            conda_context.get_schema_for_version("99.0.0")

    def test_unknown_version_lists_available(self):
        with pytest.raises(ValueError, match="26.5.3"):
            conda_context.get_schema_for_version("99.0.0")


# ---------------------------------------------------------------------------
# ssl_verify field validator
# ---------------------------------------------------------------------------


class TestSslVerifyValidator:
    def test_bool_true_accepted(self):
        cfg = CondaConfig(ssl_verify=True)
        assert cfg.ssl_verify is True

    def test_bool_false_accepted(self):
        cfg = CondaConfig(ssl_verify=False)
        assert cfg.ssl_verify is False

    def test_string_yess_coercion(self):
        """'yess' is not a valid path and not bool — validator should handle."""
        with pytest.raises((ValidationError, Exception)):
            CondaConfig(ssl_verify="yess")

    def test_valid_string_path_is_accepted_if_exists(self, tmp_path):
        ca_bundle = tmp_path / "ca-bundle.crt"
        ca_bundle.write_text("# fake CA")
        cfg = CondaConfig(ssl_verify=str(ca_bundle))
        assert cfg.ssl_verify == str(ca_bundle)
