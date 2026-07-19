"""Tests for the Context class."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from conda_context.context import Context, fresh_context, reset_context, stack_context


def _write_condarc(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Public field access
# ---------------------------------------------------------------------------


class TestContextPublicFields:
    def test_scalar_field_access(self, tmp_path):
        """Scenario: Scalar field access returns correct type."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\n")
        ctx = Context(search_path=(rc,))
        assert ctx.ssl_verify is False

    def test_sequence_field_access(self, tmp_path):
        """Scenario: Sequence field access returns tuple."""
        rc = _write_condarc(tmp_path, ".condarc", "channels:\n  - defaults\n  - conda-forge\n")
        ctx = Context(search_path=(rc,))
        # channels is a computed property that may require conda
        # test raw _channels which is always available
        assert isinstance(ctx._channels, tuple)

    def test_default_ssl_verify(self):
        ctx = Context((), None)
        assert ctx.ssl_verify is True


# ---------------------------------------------------------------------------
# Private attributes
# ---------------------------------------------------------------------------


class TestPrivateAttributes:
    def test_raw_data_is_dict(self, tmp_path):
        """Scenario: raw_data is a dict."""
        rc = _write_condarc(tmp_path, ".condarc", "ssl_verify: false\n")
        ctx = Context(search_path=(rc,))
        assert isinstance(ctx.raw_data, dict)
        assert "ssl_verify" in ctx.raw_data

    def test_cache_cleared_on_reset(self):
        """Scenario: _cache_ cleared by _reset_cache."""
        ctx = Context((), None)
        ctx._cache_["something"] = 42
        ctx._reset_cache()
        assert ctx._cache_ == {}


# ---------------------------------------------------------------------------
# Mutation protocol
# ---------------------------------------------------------------------------


class TestMutationProtocol:
    def test_set_argparse_args_updates_value(self, tmp_path):
        """Scenario: _set_argparse_args updates context values."""
        ctx = Context((), None)
        ctx._set_argparse_args(Namespace(always_yes=True))
        assert ctx.always_yes is True

    def test_set_search_path_reloads(self, tmp_path):
        rc = _write_condarc(tmp_path, ".condarc", "offline: true\n")
        ctx = Context((), None)
        assert ctx.offline is False
        ctx._set_search_path((rc,))
        assert ctx.offline is True


# ---------------------------------------------------------------------------
# reset_context / stack_context / fresh_context
# ---------------------------------------------------------------------------


class TestContextManagement:
    def test_stack_context_restores_original(self, tmp_path):
        """Scenario: stack_context restores original state on exit."""
        rc = _write_condarc(tmp_path, ".condarc", "offline: true\n")
        original_offline = _get_context_offline()
        with stack_context((rc,)):
            pass
        assert _get_context_offline() == original_offline

    def test_fresh_context_uses_defaults(self):
        """Scenario: fresh_context provides empty configuration."""
        with fresh_context():
            ctx = _get_current_context()
            assert ctx.ssl_verify is True  # default
            assert ctx.offline is False  # default


def _get_context_offline() -> bool:
    from conda_context import context as ctx_module
    return ctx_module.context.offline


def _get_current_context() -> Context:
    from conda_context import context as ctx_module
    return ctx_module.context


# ---------------------------------------------------------------------------
# Tier 1 computed properties
# ---------------------------------------------------------------------------


class TestTier1ComputedProperties:
    def test_subdir_reflects_platform(self):
        """Scenario: subdir reflects current platform (or override)."""
        ctx = Context((), None)
        subdir = ctx.subdir
        # Must be a non-empty string of the form "platform-arch"
        assert isinstance(subdir, str)
        assert len(subdir) > 0
        assert "-" in subdir

    def test_subdir_override(self, tmp_path):
        """Scenario: subdir respects _subdir override."""
        rc = _write_condarc(tmp_path, ".condarc", "subdir: osx-arm64\n")
        ctx = Context(search_path=(rc,))
        assert ctx.subdir == "osx-arm64"

    def test_fetch_threads_default_when_both_zero(self):
        """Scenario: fetch_threads default when both overrides are zero."""
        ctx = Context((), None)
        # Both _fetch_threads and _default_threads default to 0
        assert ctx.fetch_threads == 5

    def test_platform_is_string(self):
        ctx = Context((), None)
        assert ctx.platform in ("linux", "osx", "win", "unknown", "zos")

    def test_bits_is_int(self):
        ctx = Context((), None)
        assert ctx.bits in (32, 64)


# ---------------------------------------------------------------------------
# Tier 2 computed properties
# ---------------------------------------------------------------------------


class TestTier2ComputedProperties:
    def test_envs_dirs_returns_tuple(self):
        ctx = Context((), None)
        assert isinstance(ctx.envs_dirs, tuple)
        assert len(ctx.envs_dirs) > 0

    def test_pkgs_dirs_returns_tuple(self):
        ctx = Context((), None)
        assert isinstance(ctx.pkgs_dirs, tuple)

    def test_conda_prefix_is_sys_prefix(self):
        import sys
        ctx = Context((), None)
        assert ctx.conda_prefix == __import__("os.path", fromlist=["abspath"]).abspath(sys.prefix)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------


class TestModuleLevelSingleton:
    def test_module_context_is_context_instance(self):
        """Scenario: Module-level context is a Context instance."""
        from conda_context.context import context as module_context
        assert isinstance(module_context, Context)
