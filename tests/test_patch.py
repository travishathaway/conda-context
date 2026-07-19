"""Tests for the patch helpers module."""

from __future__ import annotations

import sys
import types
import warnings

import pytest

from conda_context.patch import (
    _CondaContextImportHook,
    install_import_hook,
    patch_module,
    unpatch_module,
)


def _can_import_conda() -> bool:
    try:
        import importlib

        importlib.import_module("conda")
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Import hook tests (don't require conda installed)
# ---------------------------------------------------------------------------


class TestInstallImportHook:
    def setup_method(self):
        """Remove any leftover hooks before each test."""
        sys.meta_path[:] = [h for h in sys.meta_path if not isinstance(h, _CondaContextImportHook)]

    def teardown_method(self):
        """Remove hooks and clear module cache after each test."""
        sys.meta_path[:] = [h for h in sys.meta_path if not isinstance(h, _CondaContextImportHook)]
        sys.modules.pop("conda.base.context", None)

    def test_install_returns_hook(self):
        """Scenario: install_import_hook returns an uninstallable hook."""
        hook = install_import_hook()
        assert isinstance(hook, _CondaContextImportHook)
        hook.uninstall()

    def test_hook_is_in_meta_path_after_install(self):
        """Scenario: Hook is in sys.meta_path after installation."""
        hook = install_import_hook()
        assert hook in sys.meta_path
        hook.uninstall()

    def test_hook_removed_after_uninstall(self):
        """Scenario: Import hook can be uninstalled."""
        hook = install_import_hook()
        hook.uninstall()
        assert hook not in sys.meta_path

    def test_double_uninstall_is_safe(self):
        """Scenario: Calling uninstall twice does not raise."""
        hook = install_import_hook()
        hook.uninstall()
        hook.uninstall()  # should not raise

    def test_hook_find_spec_for_target(self):
        """Hook returns a spec for the target module name."""
        hook = _CondaContextImportHook()
        spec = hook.find_spec("conda.base.context", None)
        assert spec is not None
        assert spec.name == "conda.base.context"

    def test_hook_find_spec_ignores_other_modules(self):
        """Hook returns None for non-target module names."""
        hook = _CondaContextImportHook()
        assert hook.find_spec("conda.cli.main", None) is None
        assert hook.find_spec("os", None) is None


# ---------------------------------------------------------------------------
# patch_module idempotency (does not require conda)
# ---------------------------------------------------------------------------


class TestPatchModuleIdempotency:
    def setup_method(self):
        """Reset patched state before each test."""
        import conda_context.patch as p
        p._PATCHED = False

    def teardown_method(self):
        """Reset patched state after each test."""
        import conda_context.patch as p
        p._PATCHED = False

    def test_patch_module_idempotent_when_conda_absent(self):
        """Scenario: Second call to patch_module is no-op if first raises."""
        import conda_context.patch as p
        p._PATCHED = True  # simulate already patched
        # Should return immediately without raising
        patch_module()
        assert p._PATCHED is True


# ---------------------------------------------------------------------------
# Late-patch warning test
# ---------------------------------------------------------------------------


class TestLatePatchWarning:
    def setup_method(self):
        import conda_context.patch as p
        p._PATCHED = False

    def teardown_method(self):
        import conda_context.patch as p
        p._PATCHED = False

    def test_warning_emitted_when_direct_binding_module_present(self, monkeypatch):
        """Scenario: Warning emitted when patching late."""
        import conda_context.patch as p

        # Pretend one of the direct-binding modules is already imported
        fake_module = types.ModuleType("conda.cli.main")
        monkeypatch.setitem(sys.modules, "conda.cli.main", fake_module)

        # patch_module requires conda; skip if not installed
        try:
            import conda  # noqa: F401
        except ImportError:
            pytest.skip("conda not installed")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                patch_module()
            except Exception:
                pass  # May fail for other reasons; we only care about the warning

        runtime_warnings = [w for w in caught if issubclass(w.category, RuntimeWarning)]
        assert len(runtime_warnings) > 0
        assert "conda.cli.main" in str(runtime_warnings[0].message)


# ---------------------------------------------------------------------------
# Integration: patch_module with conda installed
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _can_import_conda(),
    reason="conda not installed",
)
class TestPatchModuleIntegration:
    def setup_method(self):
        import conda_context.patch as p
        p._PATCHED = False

    def teardown_method(self):
        import conda_context.patch as p
        unpatch_module()
        p._PATCHED = False

    def test_patch_replaces_context_singleton(self):
        """Scenario: Patch replaces module-level context singleton."""
        patch_module()
        import conda.base.context as conda_ctx
        from conda_context.context import Context as CCContext
        assert isinstance(conda_ctx.context, CCContext)

    def test_patch_replaces_context_class(self):
        """Scenario: Patch replaces module-level Context class."""
        patch_module()
        import conda.base.context as conda_ctx
        from conda_context.context import Context as CCContext
        assert conda_ctx.Context is CCContext

    def test_context_management_functions_callable(self):
        """Scenario: Re-exported context management functions remain callable."""
        patch_module()
        import conda.base.context as conda_ctx
        assert callable(conda_ctx.reset_context)
        assert callable(conda_ctx.stack_context)
        assert callable(conda_ctx.fresh_context)
        assert callable(conda_ctx.replace_context)


def _can_import_conda() -> bool:
    try:
        import importlib

        importlib.import_module("conda")
        return True
    except ImportError:
        return False
