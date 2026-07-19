"""
Patch helpers for replacing conda.base.context at runtime.

Two mechanisms:
1. ``patch_module()`` — module-attribute replacement (for plugin entry points).
   Must be called before any other conda.* module is imported.

2. ``install_import_hook()`` — sys.meta_path hook that intercepts the import
   of conda.base.context and returns our replacement module instead.
   Works regardless of import order but is more complex.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import sys
import types
import warnings
from typing import Any

# Modules that use direct name binding for `context`.
# If any of these are already imported when patch_module() is called,
# they will hold references to the original context object.
_DIRECT_BINDING_MODULES = (
    "conda._private.shards.misc",
    "conda._private.shards.shards",
    "conda._private.shards.subset",
    "conda.activate",
    "conda.api",
    "conda.cli.common",
    "conda.cli.conda_argparse",
    "conda.cli.condarc",
    "conda.cli.helpers",
    "conda.cli.install",
    "conda.cli.main",
    "conda.cli.main_clean",
    "conda.cli.main_compare",
    "conda.cli.main_config",
    "conda.cli.main_create",
    "conda.cli.main_env_create",
    "conda.cli.main_env_update",
    "conda.cli.main_env_vars",
    "conda.cli.main_export",
    "conda.cli.main_info",
    "conda.cli.main_init",
    "conda.cli.main_install",
    "conda.cli.main_list",
    "conda.cli.main_package",
    "conda.cli.main_remove",
    "conda.cli.main_rename",
    "conda.cli.main_run",
    "conda.cli.main_search",
    "conda.cli.main_update",
    "conda.common.path",
    "conda.common.path.windows",
    "conda.core.envs_manager",
    "conda.core.index",
    "conda.core.initialize",
    "conda.core.link",
    "conda.core.package_cache_data",
    "conda.core.path_actions",
    "conda.core.portability",
    "conda.core.prefix_data",
    "conda.core.solve",
    "conda.core.subdir_data",
    "conda.env.env",
    "conda.env.installers.conda",
    "conda.env.pip_util",
    "conda.env.specs",
    "conda.exception_handler",
    "conda.exceptions",
    "conda.gateways.connection.download",
    "conda.gateways.connection.session",
    "conda.gateways.disk.create",
    "conda.gateways.disk.delete",
    "conda.gateways.disk.lock",
    "conda.gateways.disk.update",
    "conda.gateways.repodata",
    "conda.gateways.streams",
    "conda.history",
    "conda.misc",
    "conda.models.channel",
    "conda.models.environment",
    "conda.models.match_spec",
    "conda.notices.core",
    "conda.plugins.config",
    "conda.plugins.manager",
    "conda.resolve",
)

_PATCHED = False


def patch_module() -> None:
    """Replace ``conda.base.context`` module attributes with conda-context equivalents.

    Replaces:
    - ``conda.base.context.Context`` → ``conda_context.context.Context``
    - ``conda.base.context.context`` → ``conda_context.context.context``
    - ``conda.base.context.reset_context`` → re-exported from conda_context
    - ``conda.base.context.stack_context`` → re-exported from conda_context
    - ``conda.base.context.fresh_context`` → re-exported from conda_context
    - ``conda.base.context.replace_context`` → re-exported from conda_context
    - ``conda.base.context.context_stack`` → re-exported from conda_context

    **Must be called before any other conda.* module is imported.**

    Idempotent — calling multiple times is safe.

    Warns:
        RuntimeWarning: If any direct-binding conda modules are already imported.
    """
    global _PATCHED
    if _PATCHED:
        return

    # Check for already-imported direct-binding modules
    already_imported = [m for m in _DIRECT_BINDING_MODULES if m in sys.modules]
    if already_imported:
        warnings.warn(
            "conda_context.patch.patch_module() called after the following conda "
            "modules were already imported. These modules hold direct references to "
            "the original context object and will NOT use the replacement:\n"
            + "\n".join(f"  - {m}" for m in already_imported),
            RuntimeWarning,
            stacklevel=2,
        )

    # Import our replacements
    import conda_context.context as cc_ctx

    # Ensure conda.base.context is imported so we can patch it
    try:
        import conda.base.context as conda_ctx_mod  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "conda is not installed. patch_module() requires conda to be installed."
        ) from exc

    # Replace module attributes
    conda_ctx_mod.Context = cc_ctx.Context  # type: ignore[attr-defined]
    conda_ctx_mod.context = cc_ctx.context  # type: ignore[attr-defined]
    conda_ctx_mod.reset_context = cc_ctx.reset_context  # type: ignore[attr-defined]
    conda_ctx_mod.stack_context = cc_ctx.stack_context  # type: ignore[attr-defined]
    conda_ctx_mod.fresh_context = cc_ctx.fresh_context  # type: ignore[attr-defined]
    conda_ctx_mod.replace_context = cc_ctx.replace_context  # type: ignore[attr-defined]
    conda_ctx_mod.context_stack = cc_ctx.context_stack  # type: ignore[attr-defined]
    conda_ctx_mod.stack_context_default = cc_ctx.stack_context_default  # type: ignore[attr-defined]
    conda_ctx_mod.replace_context_default = cc_ctx.replace_context_default  # type: ignore[attr-defined]

    _PATCHED = True


def unpatch_module() -> None:
    """Restore the original ``conda.base.context`` module attributes.

    Only works if the original module is still importable.
    Primarily useful for testing.
    """
    global _PATCHED
    if not _PATCHED:
        return

    try:
        # Force re-import of the original module from disk
        if "conda.base.context" in sys.modules:
            del sys.modules["conda.base.context"]
        import conda.base.context  # noqa: F401  # type: ignore[import]
    except ImportError:
        pass

    _PATCHED = False


class _CondaContextImportHook(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """sys.meta_path hook that redirects ``conda.base.context`` to conda_context.context."""

    _TARGET = "conda.base.context"

    def find_module(self, fullname: str, path: Any = None) -> Any:
        # Python 3.4+ compatibility shim; find_spec is preferred
        return None

    def find_spec(
        self,
        fullname: str,
        path: Any,
        target: Any = None,
    ) -> importlib.machinery.ModuleSpec | None:
        if fullname == self._TARGET:
            return importlib.machinery.ModuleSpec(
                fullname,
                self,
                origin="conda_context.context",
            )
        return None

    def create_module(self, spec: Any) -> types.ModuleType | None:
        # Return None to use the default module creation
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        """Populate the module with conda_context.context contents."""
        import conda_context.context as cc_ctx

        # Copy all public attributes from our context module
        for name in dir(cc_ctx):
            try:
                setattr(module, name, getattr(cc_ctx, name))
            except AttributeError:
                pass

        # Ensure sys.modules points to our replacement
        module.__spec__ = None  # type: ignore[assignment]

    def uninstall(self) -> None:
        """Remove this hook from sys.meta_path."""
        try:
            sys.meta_path.remove(self)
        except ValueError:
            pass
        # Also clear any cached import
        sys.modules.pop("conda.base.context", None)


def install_import_hook() -> _CondaContextImportHook:
    """Install a sys.meta_path hook that redirects conda.base.context imports.

    Must be called **before** ``import conda.base.context`` executes.

    Returns:
        The hook object. Call ``hook.uninstall()`` to remove it.
    """
    hook = _CondaContextImportHook()
    sys.meta_path.insert(0, hook)
    # Clear any cached import so the hook is consulted
    sys.modules.pop("conda.base.context", None)
    return hook
