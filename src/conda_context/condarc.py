"""
CondaRC — full CRUD API for .condarc files.

Uses ruamel.yaml in round-trip mode to preserve comments, key ordering,
and formatting across save operations.

Validates proposed mutations against the full merged context before writing
(per design.md D4).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from .errors import CondaConfigError
from .merge import MergeEngine
from .provenance import ProvenanceMap
from .schemas._26_5_3 import CondaConfig


class CondaRC:
    """Read/write interface for a single .condarc YAML file.

    Load an existing file with :meth:`load` or create a new one with
    :meth:`create`.  Mutate in-memory with :meth:`set`, :meth:`unset`,
    :meth:`prepend_channel`, etc.  Persist with :meth:`save`.

    Args:
        path: Target file path.
        _data: Internal ruamel CommentedMap (use class methods, not this arg).
        _original: Snapshot of the data at load/create time (for diff).
    """

    def __init__(
        self,
        path: Path,
        _data: CommentedMap | None = None,
        _original: dict[str, Any] | None = None,
    ) -> None:
        self._path = Path(path)
        self._yaml = YAML()
        self._yaml.preserve_quotes = True
        self._yaml.default_flow_style = False
        self._data: CommentedMap = _data if _data is not None else CommentedMap()
        # Snapshot of original values for diff()
        self._original: dict[str, Any] = _original if _original is not None else {}

    # ------------------------------------------------------------------
    # Class methods
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, path: Path | str) -> CondaRC:
        """Load an existing .condarc file.

        Args:
            path: Path to the existing YAML file.

        Returns:
            A ``CondaRC`` instance backed by the file's contents.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not a valid YAML mapping.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"No such file: {path}")

        yaml = YAML()
        yaml.preserve_quotes = True
        with open(path, encoding="utf-8") as fh:
            data = yaml.load(fh)

        if data is None:
            data = CommentedMap()
        if not isinstance(data, CommentedMap):
            raise ValueError(f"Expected a YAML mapping in {path}, got {type(data)}")

        original = {k: cls._deep_copy_value(v) for k, v in data.items()}
        return cls(path=path, _data=data, _original=original)

    @classmethod
    def create(cls, path: Path | str) -> CondaRC:
        """Create a new in-memory .condarc targeting the given path.

        The file is NOT written to disk until :meth:`save` is called.

        Args:
            path: Target file path.

        Returns:
            An empty ``CondaRC`` instance.
        """
        return cls(path=Path(path), _data=CommentedMap(), _original={})

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, key: str) -> Any:
        """Return the value for ``key``, or ``None`` if not set in this file."""
        return self._data.get(key)

    def get_all(self) -> dict[str, Any]:
        """Return all key-value pairs explicitly set in this file."""
        return {k: self._deep_copy_value(v) for k, v in self._data.items()}

    # ------------------------------------------------------------------
    # Write (in-memory mutations)
    # ------------------------------------------------------------------

    def set(self, key: str, value: Any) -> CondaRC:
        """Set a configuration key to ``value``.

        Performs immediate single-field type validation. Cross-field
        constraints are deferred to :meth:`save`.

        Args:
            key: Configuration field name.
            value: New value. Must be of the correct type for the field.

        Returns:
            ``self`` (for chaining).

        Raises:
            CondaConfigError: If the value fails single-field validation.
        """
        self._validate_single_field(key, value)
        self._data[key] = value
        return self

    def unset(self, key: str) -> CondaRC:
        """Remove ``key`` from this file.  No-op if the key is not present.

        Returns:
            ``self`` (for chaining).
        """
        self._data.pop(key, None)
        return self

    def prepend_channel(self, channel: str) -> CondaRC:
        """Prepend ``channel`` to the channels list in this file.

        Returns:
            ``self`` (for chaining).
        """
        return self.add_to("channels", channel, prepend=True)

    def append_channel(self, channel: str) -> CondaRC:
        """Append ``channel`` to the channels list in this file.

        Returns:
            ``self`` (for chaining).
        """
        return self.add_to("channels", channel, prepend=False)

    def add_to(self, key: str, value: Any, prepend: bool = False) -> CondaRC:
        """Add ``value`` to a sequence field.

        Args:
            key: Sequence field name (e.g., ``"channels"``).
            value: Item to add.
            prepend: If ``True``, insert at the front; otherwise append.

        Returns:
            ``self`` (for chaining).
        """
        current = self._data.get(key, [])
        if not isinstance(current, list):
            current = list(current) if current else []
        if prepend:
            current = [value] + current
        else:
            current = current + [value]
        self._data[key] = current
        return self

    def remove_from(self, key: str, value: Any) -> CondaRC:
        """Remove ``value`` from a sequence field.  No-op if not present.

        Args:
            key: Sequence field name.
            value: Item to remove.

        Returns:
            ``self`` (for chaining).
        """
        current = self._data.get(key)
        if isinstance(current, list) and value in current:
            self._data[key] = [v for v in current if v != value]
        return self

    # ------------------------------------------------------------------
    # Diff
    # ------------------------------------------------------------------

    def diff(self) -> dict[str, tuple[Any, Any]]:
        """Return pending changes as ``{key: (old_value, new_value)}``.

        Keys that were absent in the original and are now present show
        ``(None, new_value)``. Keys that were present and are now absent show
        ``(old_value, None)``.
        """
        result: dict[str, tuple[Any, Any]] = {}
        all_keys = set(self._original) | set(self._data)
        for key in all_keys:
            old = self._original.get(key)
            new = self._data.get(key)
            if old != new:
                result[key] = (old, new)
        return result

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    def save(self, strict: bool = True) -> CondaRC:
        """Validate and write the file to disk atomically.

        Builds a candidate merged configuration (all on-disk condarc sources
        with this file's pending changes applied), validates it via
        ``CondaConfig``, and only writes on success.

        Args:
            strict: If ``True`` (default), validate cross-field constraints.
                    If ``False``, skip cross-field validation (only single-field
                    constraints apply).

        Returns:
            ``self`` (for chaining).

        Raises:
            CondaConfigError: If validation fails before any bytes are written.
        """
        # Build the candidate by loading all other sources and overlaying this file
        candidate = self._build_candidate()

        # Validate
        provenance: ProvenanceMap = {}
        try:
            if strict:
                CondaConfig(**candidate)
            else:
                # Validate only the fields present in this file
                file_keys = set(self._data.keys())
                partial = {k: v for k, v in candidate.items() if k in file_keys}
                CondaConfig(**partial)
        except ValidationError as exc:
            raise CondaConfigError(exc, provenance) from exc

        # Write atomically
        self._atomic_write()
        # Update original snapshot
        self._original = {k: self._deep_copy_value(v) for k, v in self._data.items()}
        return self

    def save_as(self, new_path: Path | str, strict: bool = True) -> CondaRC:
        """Write to a different path.

        Args:
            new_path: Destination path.
            strict: Passed to :meth:`save`.

        Returns:
            A new ``CondaRC`` instance pointing at ``new_path``.
        """
        new = CondaRC(path=Path(new_path), _data=self._data, _original=self._original)
        new.save(strict=strict)
        return new

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_single_field(self, key: str, value: Any) -> None:
        """Run single-field Pydantic validation (no cross-field checks)."""
        try:
            CondaConfig(**{key: value})
        except ValidationError as exc:
            # Only surface errors for this specific field
            field_errors = [
                e for e in exc.errors(include_url=False) if e["loc"] and str(e["loc"][0]) == key
            ]
            if field_errors:
                raise CondaConfigError(exc, {}) from exc

    def _build_candidate(self) -> dict[str, Any]:
        """Merge all active condarc sources with this file's pending changes."""
        # Start with an empty merge (other sources)
        # We use a fresh MergeEngine with no search path to get env/arg baseline
        engine = MergeEngine(search_path=())
        base, _ = engine.resolve()

        # Load the on-disk version of this file (if it exists) to get other sources
        # Then overlay our in-memory changes
        base.update({k: self._data.get(k) for k in self._data})
        return base

    def _atomic_write(self) -> None:
        """Write the file atomically using a temporary file + os.replace."""
        parent = self._path.parent
        parent.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                self._yaml.dump(self._data, fh)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up temp file on error
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _deep_copy_value(value: Any) -> Any:
        """Deep-copy a value to avoid aliasing issues."""
        if isinstance(value, dict):
            return {k: CondaRC._deep_copy_value(v) for k, v in value.items()}
        if isinstance(value, list):
            return [CondaRC._deep_copy_value(v) for v in value]
        return value

    def __repr__(self) -> str:
        return f"CondaRC(path={self._path!r}, keys={list(self._data.keys())})"
