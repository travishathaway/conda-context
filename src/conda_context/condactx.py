"""
condactx — conda wrapper that substitutes conda_context for conda.base.context.

This module is the entry point for the ``condactx`` command.  It:

1. Pre-imports ``conda_context.context`` and the real ``conda.base.context``
   *before* installing the import hook, avoiding a circular-import that would
   occur if either module tried to import the other while being initialized.
2. Back-fills any names that conda imports from ``conda.base.context`` but
   that ``conda_context.context`` does not yet define (constants, internal
   helpers, legacy types).  These are sourced from the real module — we own
   the *Context* object, not every helper in that namespace.
3. Installs the sys.meta_path hook so that any *subsequent*
   ``from conda.base.context import …`` in conda's own code resolves to the
   already-populated replacement module.
4. Delegates to ``conda.cli.main.main()`` so the full conda CLI works
   unchanged.

Usage
-----
condactx <conda-subcommand> [args...]

Examples
--------
condactx info
condactx install numpy
condactx config --show ssl_verify
"""

from __future__ import annotations

import importlib
import sys


def _backfill_module(cc_mod, conda_mod) -> None:
    """Copy names present in *conda_mod* but absent from *cc_mod*.

    Any name that conda imports from ``conda.base.context`` but that
    ``conda_context.context`` does not yet export is pulled in from the real
    module.  Our own definitions always take precedence — we never overwrite
    something we own.
    """
    cc_names = set(dir(cc_mod))
    for name in dir(conda_mod):
        if name not in cc_names:
            try:
                setattr(cc_mod, name, getattr(conda_mod, name))
            except AttributeError:
                pass


def main() -> None:
    """Entry point for the ``condactx`` CLI wrapper."""

    # Step 1 — pre-import our replacement module so its module-level code
    # (including the ``from conda.base.context import …`` re-export block)
    # runs exactly once, before the hook is active.
    try:
        import conda_context.context as _cc_ctx
    except ImportError as exc:
        print(
            "condactx: conda_context package is not installed correctly.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    # Step 2 — load the *real* conda.base.context before the hook, so we
    # can use it for the gap-fill without any circular-import risk.
    try:
        _original = importlib.import_module("conda.base.context")
    except ImportError as exc:
        print(
            "condactx: conda is not installed in this environment.\n"
            "Install conda 26.5.3 to use condactx.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    # Step 3 — back-fill missing names into our replacement module.
    _backfill_module(_cc_ctx, _original)

    # Step 4 — install the import hook.  From this point on, any
    # ``import conda.base.context`` by conda's own code will return the
    # already-populated replacement module from sys.modules instead of the
    # real one.
    from conda_context.patch import install_import_hook

    hook = install_import_hook()  # noqa: F841

    # Point sys.modules["conda.base.context"] at the replacement module so
    # the hook and any cached imports resolve consistently.
    sys.modules["conda.base.context"] = _cc_ctx  # type: ignore[assignment]

    # Also back-fill the replacement module object that the hook registered
    # (it may be a thin wrapper; make sure it has all the gap-fill names too).
    _backfill_module(sys.modules["conda.base.context"], _original)

    # Step 5 — hand off to conda's CLI.
    try:
        from conda.cli.main import main as conda_main  # type: ignore[import]
    except ImportError as exc:
        print(
            "condactx: conda is not installed in this environment.\n"
            "Install conda 26.5.3 to use condactx.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    rc = conda_main()
    raise SystemExit(rc if isinstance(rc, int) else 0)


if __name__ == "__main__":
    main()
