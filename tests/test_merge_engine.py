"""Tests for the MergeEngine — layered configuration resolution."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from conda_context.merge import MergeEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_condarc(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Source priority
# ---------------------------------------------------------------------------


class TestSourcePriority:
    def test_cli_arg_overrides_condarc(self, tmp_path):
        """Scenario: CLI arg overrides condarc value."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\n")
        engine = MergeEngine(
            search_path=(rc,),
            argparse_args=Namespace(ssl_verify=True),
        )
        merged, _ = engine.resolve()
        assert merged["ssl_verify"] is True

    def test_env_var_overrides_condarc(self, tmp_path):
        """Scenario: Env var overrides condarc value."""
        rc = _write_condarc(tmp_path, ".condarc", "always_yes: false\n")
        engine = MergeEngine(
            search_path=(rc,),
            environ={"CONDA_ALWAYS_YES": "1"},
        )
        merged, _ = engine.resolve()
        assert merged["always_yes"] is True

    def test_lower_priority_file_wins_when_higher_absent(self, tmp_path):
        """Scenario: Lower-priority file wins when higher-priority is absent."""
        system_rc = _write_condarc(tmp_path, "system.condarc", "ssl_verify: false\n")
        engine = MergeEngine(search_path=(system_rc,), environ={})
        merged, _ = engine.resolve()
        assert merged["ssl_verify"] is False


# ---------------------------------------------------------------------------
# Sequence merge semantics
# ---------------------------------------------------------------------------


class TestSequenceMerge:
    def test_channels_prepend(self, tmp_path):
        """Scenario: Channels from user condarc prepend system channels."""
        system_rc = _write_condarc(tmp_path, "system.condarc", "channels:\n  - defaults\n")
        user_rc = _write_condarc(tmp_path, "user.condarc", "channels:\n  - pytorch\n")
        engine = MergeEngine(search_path=(system_rc, user_rc), environ={})
        merged, _ = engine.resolve()
        assert merged["channels"] == ["pytorch", "defaults"]

    def test_append_flag_puts_items_at_end(self, tmp_path):
        """Scenario: List append flag overrides prepend."""
        system_rc = _write_condarc(tmp_path, "system.condarc", "channels:\n  - defaults\n")
        user_rc = _write_condarc(
            tmp_path,
            "user.condarc",
            "channels:\n  - pytorch\n  - append\n",
        )
        engine = MergeEngine(search_path=(system_rc, user_rc), environ={})
        merged, _ = engine.resolve()
        assert merged["channels"] == ["defaults", "pytorch"]


# ---------------------------------------------------------------------------
# Map merge semantics
# ---------------------------------------------------------------------------


class TestMapMerge:
    def test_distinct_keys_both_present(self, tmp_path):
        """Scenario: Distinct keys from two sources are both present."""
        system_rc = _write_condarc(tmp_path, "sys.condarc", "proxy_servers:\n  http: proxy1\n")
        user_rc = _write_condarc(tmp_path, "user.condarc", "proxy_servers:\n  https: proxy2\n")
        engine = MergeEngine(search_path=(system_rc, user_rc), environ={})
        merged, _ = engine.resolve()
        assert "http" in merged["proxy_servers"]
        assert "https" in merged["proxy_servers"]

    def test_key_collision_higher_priority_wins(self, tmp_path):
        """Scenario: Key collision resolved by priority."""
        system_rc = _write_condarc(tmp_path, "sys.condarc", "proxy_servers:\n  http: proxy1\n")
        user_rc = _write_condarc(tmp_path, "user.condarc", "proxy_servers:\n  http: proxy2\n")
        engine = MergeEngine(search_path=(system_rc, user_rc), environ={})
        merged, _ = engine.resolve()
        assert merged["proxy_servers"]["http"] == "proxy2"


# ---------------------------------------------------------------------------
# ProvenanceMap population
# ---------------------------------------------------------------------------


class TestProvenanceMap:
    def test_provenance_recorded_for_yaml_field(self, tmp_path):
        """Scenario: Provenance recorded for yaml-sourced field."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\n")
        engine = MergeEngine(search_path=(rc,), environ={})
        _, prov = engine.resolve()
        assert "ssl_verify" in prov
        info = prov["ssl_verify"]
        assert info.source_type == "yaml_file"
        assert info.path == rc
        assert info.line == 1  # first line

    def test_provenance_recorded_for_env_var(self, tmp_path):
        """Scenario: Provenance recorded for environment variable."""
        engine = MergeEngine(
            search_path=(),
            environ={"CONDA_ALWAYS_YES": "1"},
        )
        _, prov = engine.resolve()
        assert "always_yes" in prov
        info = prov["always_yes"]
        assert info.source_type == "env_var"
        assert info.env_var == "CONDA_ALWAYS_YES"

    def test_default_field_absent_from_provenance(self, tmp_path):
        """Scenario: Fields at default have no provenance entry."""
        engine = MergeEngine(search_path=(), environ={})
        _, prov = engine.resolve()
        assert prov.get("ssl_verify") is None


# ---------------------------------------------------------------------------
# Search path expansion
# ---------------------------------------------------------------------------


class TestSearchPathExpansion:
    def test_directory_expanded_to_yaml_files(self, tmp_path):
        """Scenario: Directory in search path is expanded."""
        d = tmp_path / "condarc.d"
        d.mkdir()
        (d / "a.yaml").write_text("ssl_verify: false\n")
        (d / "b.yaml").write_text("offline: true\n")
        engine = MergeEngine(search_path=(d,), environ={})
        merged, _ = engine.resolve()
        assert "ssl_verify" in merged
        assert "offline" in merged

    def test_nonexistent_path_silently_skipped(self):
        """Scenario: Non-existent paths are silently skipped."""
        engine = MergeEngine(search_path=(Path("/nonexistent/.condarc"),), environ={})
        merged, _ = engine.resolve()
        assert merged == {}

    def test_malformed_yaml_emits_warning_and_skips(self, tmp_path, caplog):
        """Scenario: Malformed YAML files emit a warning and are skipped."""
        bad = _write_condarc(tmp_path, "bad.yaml", "key: {invalid: yaml: here\n")
        engine = MergeEngine(search_path=(bad,), environ={})
        import logging

        with caplog.at_level(logging.WARNING, logger="conda_context.merge"):
            merged, _ = engine.resolve()
        assert merged == {}
        assert any("bad.yaml" in r.message for r in caplog.records)
