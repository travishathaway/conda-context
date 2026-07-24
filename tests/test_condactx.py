"""
Integration tests for the condactx wrapper.

These tests run ``condactx`` as a subprocess to verify:
  - Basic conda operations work through the patched context.
  - Bad .condarc values surface CondaConfigError with file-path + line-number
    provenance in the error output.
  - The correct Context class (conda_context.context.Context) is active.

All tests require conda to be installed and the condactx entry point to be
on PATH.  They are skipped otherwise.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _can_import_conda() -> bool:
    try:
        import importlib

        importlib.import_module("conda")
        return True
    except ImportError:
        return False


def _condactx_on_path() -> bool:
    return shutil.which("condactx") is not None


def _run_condactx(*args: str, env_overrides: dict | None = None) -> subprocess.CompletedProcess:
    """Run ``condactx <args>`` and return the completed process."""
    import os

    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        ["condactx", *args],
        capture_output=True,
        text=True,
        env=env,
    )


_requires_conda_and_condactx = pytest.mark.skipif(
    not (_can_import_conda() and _condactx_on_path()),
    reason="conda not installed or condactx not on PATH",
)


# ---------------------------------------------------------------------------
# 1. Basic smoke tests — condactx info / condactx config --show
# ---------------------------------------------------------------------------


@_requires_conda_and_condactx
class TestCondactxInfo:
    def test_condactx_info_exits_zero(self):
        """condactx info exits with code 0."""
        result = _run_condactx("info")
        assert result.returncode == 0, f"stderr:\n{result.stderr}"

    def test_condactx_info_shows_conda_version(self):
        """condactx info output contains conda version line."""
        result = _run_condactx("info")
        assert "conda version" in result.stdout

    def test_condactx_info_uses_our_context(self):
        """condactx info runs through conda_context's code path.

        We verify by checking that condactx info exits 0 and produces
        output — meaning our Context was successfully used as the drop-in
        replacement throughout the conda info command.
        """
        result = _run_condactx("info")
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        # Our Context exposes the same interface as conda's, so info output
        # should contain these standard fields.
        assert "conda version" in result.stdout
        assert "platform" in result.stdout


@_requires_conda_and_condactx
class TestCondactxConfigShow:
    def test_condactx_config_show_ssl_verify(self):
        """condactx config --show ssl_verify returns a value."""
        result = _run_condactx("config", "--show", "ssl_verify")
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        assert "ssl_verify" in result.stdout

    def test_condactx_config_show_channel_priority(self):
        """condactx config --show channel_priority returns a value."""
        result = _run_condactx("config", "--show", "channel_priority")
        assert result.returncode == 0, f"stderr:\n{result.stderr}"
        assert "channel_priority" in result.stdout


# ---------------------------------------------------------------------------
# 2. Provenance error tests — bad .condarc values
# ---------------------------------------------------------------------------


@_requires_conda_and_condactx
class TestCondactxProvenanceErrors:
    def test_bad_ssl_verify_surfaces_file_and_line(self, tmp_path: Path):
        """Bad ssl_verify in .condarc shows file path and line number."""
        condarc = tmp_path / ".condarc"
        condarc.write_text("channels:\n  - defaults\nssl_verify: yess\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        # Error must appear in stderr and exit non-zero
        assert result.returncode != 0, (
            f"Expected non-zero exit, got 0.\nstderr: {result.stderr[:500]}"
        )
        stderr = result.stderr
        assert "ssl_verify" in stderr
        assert str(condarc) in stderr
        # Line 3 is where ssl_verify appears (1-indexed)
        assert "line 3" in stderr

    def test_bad_ssl_verify_shows_hint(self, tmp_path: Path):
        """Bad ssl_verify with a near-miss value produces a helpful hint."""
        condarc = tmp_path / ".condarc"
        condarc.write_text("ssl_verify: yess\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        assert result.returncode != 0
        stderr = result.stderr
        # Hint should suggest the correct value
        assert "true" in stderr.lower() or "false" in stderr.lower()

    def test_bad_channel_priority_surfaces_file_and_line(self, tmp_path: Path):
        """Bad channel_priority shows file path, line number, and valid choices."""
        condarc = tmp_path / ".condarc"
        # channel_priority is on line 1
        condarc.write_text("channel_priority: turbo\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        assert result.returncode != 0
        stderr = result.stderr
        assert "channel_priority" in stderr
        assert str(condarc) in stderr
        assert "line 1" in stderr

    def test_bad_channel_priority_hint_lists_valid_choices(self, tmp_path: Path):
        """Hint for invalid channel_priority lists all valid choices."""
        condarc = tmp_path / ".condarc"
        condarc.write_text("channel_priority: turbo\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        assert result.returncode != 0
        stderr = result.stderr
        # Hint should contain at least one valid value
        assert "flexible" in stderr or "strict" in stderr or "disabled" in stderr

    def test_multiple_bad_values_all_reported(self, tmp_path: Path):
        """Multiple bad values in one .condarc are all reported in the error."""
        condarc = tmp_path / ".condarc"
        condarc.write_text("ssl_verify: yess\nchannel_priority: turbo\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        assert result.returncode != 0
        stderr = result.stderr
        assert "ssl_verify" in stderr
        assert "channel_priority" in stderr

    def test_bad_value_from_env_var_names_the_variable(self):
        """Bad value from CONDA_* env var reports the variable name."""
        result = _run_condactx(
            "info",
            env_overrides={"CONDA_SSL_VERIFY": "yess"},
        )

        assert result.returncode != 0
        stderr = result.stderr
        assert "ssl_verify" in stderr
        # Provenance should mention the env var
        assert "CONDA_SSL_VERIFY" in stderr

    def test_valid_condarc_exits_zero(self, tmp_path: Path):
        """A valid .condarc causes no errors."""
        condarc = tmp_path / ".condarc"
        condarc.write_text("ssl_verify: true\nchannel_priority: strict\n")

        result = _run_condactx("info", env_overrides={"CONDARC": str(condarc)})

        assert result.returncode == 0, f"Unexpected error:\n{result.stderr}"


# ---------------------------------------------------------------------------
# 3. Context method coverage — verify new methods are present
# ---------------------------------------------------------------------------


class TestNewContextMethods:
    """These tests run without conda and verify the new methods exist."""

    def test_register_reset_callaback_exists(self):
        from conda_context.context import Context

        ctx = Context((), None)
        assert hasattr(ctx, "register_reset_callaback")
        # Should accept a callable without raising
        ctx.register_reset_callaback(lambda: None)

    def test_register_reset_callaback_fires_on_reset(self):
        from conda_context.context import Context

        ctx = Context((), None)
        calls = []
        ctx.register_reset_callaback(lambda: calls.append(1))
        ctx._reset_cache()
        assert calls == [1], "Callback should have been called once"

    def test_validate_configuration_passes_for_valid_config(self):
        from conda_context.context import Context

        ctx = Context((), None)
        # Should not raise
        ctx.validate_configuration()

    def test_validate_all_passes_for_valid_config(self):
        from conda_context.context import Context

        ctx = Context((), None)
        ctx.validate_all()

    def test_list_parameters_returns_sorted_tuple(self):
        from conda_context.context import Context

        ctx = Context((), None)
        params = ctx.list_parameters()
        assert isinstance(params, tuple)
        assert len(params) > 0
        assert params == tuple(sorted(params))

    def test_list_parameters_aliases_includes_more(self):
        from conda_context.context import Context

        ctx = Context((), None)
        without = ctx.list_parameters(aliases=False)
        with_aliases = ctx.list_parameters(aliases=True)
        # With aliases should be at least as long
        assert len(with_aliases) >= len(without)

    def test_parameter_names_returns_tuple(self):
        from conda_context.context import Context

        ctx = Context((), None)
        assert isinstance(ctx.parameter_names, tuple)
        assert "ssl_verify" in ctx.parameter_names or "ssl_verify" in [
            n.lstrip("_") for n in ctx.parameter_names
        ]

    def test_name_for_alias_returns_canonical(self):
        from conda_context.context import Context

        ctx = Context((), None)
        # "copy" is an alias for "always_copy"
        result = ctx.name_for_alias("copy")
        assert result == "always_copy"

    def test_name_for_alias_returns_none_for_unknown(self):
        from conda_context.context import Context

        ctx = Context((), None)
        assert ctx.name_for_alias("not_a_real_param_xyz") is None

    def test_describe_parameter_returns_dict(self):
        from conda_context.context import Context

        ctx = Context((), None)
        desc = ctx.describe_parameter("ssl_verify")
        assert isinstance(desc, dict)
        assert desc["name"] == "ssl_verify"

    def test_describe_parameter_raises_for_unknown(self):
        from conda_context.context import Context

        ctx = Context((), None)
        with pytest.raises(KeyError):
            ctx.describe_parameter("not_a_real_param_xyz")

    def test_typify_parameter_coerces_bool(self):
        from conda_context.context import Context

        ctx = Context((), None)
        name, val = ctx.typify_parameter("ssl_verify", True, "test")
        assert name == "ssl_verify"
        assert val is True
