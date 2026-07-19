"""
conda-context — Pydantic-backed drop-in replacement for conda.base.context.Context.

Targets conda 26.5.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pydantic import BaseModel

__version__ = "26.5.3"

# Supported schema versions mapped to their module paths
_SCHEMA_VERSIONS: dict[str, str] = {
    "26.5.3": "conda_context.schemas._26_5_3",
}


def get_schema_for_version(version: str) -> type[BaseModel]:
    """Return the CondaConfig Pydantic model for the given conda version string.

    Args:
        version: A conda version string, e.g. ``"26.5.3"``.

    Returns:
        The ``CondaConfig`` class for that version.

    Raises:
        ValueError: If the version is not supported.
    """
    module_path = _SCHEMA_VERSIONS.get(version)
    if module_path is None:
        available = ", ".join(sorted(_SCHEMA_VERSIONS))
        raise ValueError(
            f"conda-context does not support conda version {version!r}. "
            f"Available versions: {available}"
        )
    import importlib

    mod = importlib.import_module(module_path)
    return mod.CondaConfig  # type: ignore[attr-defined]
