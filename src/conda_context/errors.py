"""
CondaConfigError — enriched validation error for conda configuration.

Wraps one or more Pydantic ValidationError instances and enriches each
field error with ProvenanceInfo so users see exactly where in their
configuration files (or environment variables) the bad value came from.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from .provenance import ProvenanceInfo, ProvenanceMap

# ---------------------------------------------------------------------------
# Hint generation helpers
# ---------------------------------------------------------------------------

# Fields that are boolean (common source of "yess" / "no" / "1" mistakes)
_BOOL_FIELDS = {
    "add_pip_as_python_dependency",
    "allow_conda_downgrades",
    "allow_cycles",
    "allow_softlinks",
    "auto_update_conda",
    "auto_activate",
    "always_copy",
    "always_softlink",
    "clobber",
    "changeps1",
    "dev",
    "download_only",
    "dry_run",
    "enable_private_envs",
    "envvars_force_uppercase",
    "extra_safety_checks",
    "force",
    "force_32bit",
    "force_remove",
    "force_reinstall",
    "ignore_pinned",
    "json",
    "no_lock",
    "non_admin_enabled",
    "notify_outdated_conda",
    "offline",
    "override_channels_enabled",
    "prefix_data_interoperability",
    "protect_frozen_envs",
    "quiet",
    "register_envs",
    "repodata_use_shards",
    "repodata_use_zst",
    "rollback_enabled",
    "separate_format_cache",
    "shortcuts",
    "solver_ignore_timestamps",
    "unsatisfiable_hints",
    "use_index_cache",
    "use_local",
}

# Mutually exclusive field pairs
_MUTUAL_EXCLUSIONS: list[tuple[str, str]] = [
    ("always_copy", "always_softlink"),
]

# Fields requiring another field
_REQUIRES: list[tuple[str, str]] = [
    ("client_ssl_cert_key", "client_ssl_cert"),
]

# Enum fields and their valid choices
_ENUM_FIELDS: dict[str, list[str]] = {
    "channel_priority": ["flexible", "strict", "disabled"],
    "safety_checks": ["disabled", "warn", "enabled"],
    "path_conflict": ["clobber", "warn", "prevent"],
    "deps_modifier": ["not_set", "no_deps", "only_deps"],
    "update_modifier": [
        "specs_satisfied_skip_solve",
        "freeze_installed",
        "update_deps",
        "update_specs",
        "update_all",
    ],
    "sat_solver": ["pycosat", "pycryptosat", "pysat"],
}


def _generate_hint(field_name: str, raw_value: Any) -> str | None:
    """Return an actionable hint string for known misconfiguration patterns."""
    # Boolean field given a string value
    if field_name in _BOOL_FIELDS and isinstance(raw_value, str):
        v = raw_value.strip().lower()
        if v in ("yes", "yess", "y", "true", "1", "on"):
            return f"Did you mean `{field_name}: true`?"
        elif v in ("no", "n", "false", "0", "off"):
            return f"Did you mean `{field_name}: false`?"
        return f"Expected a boolean. Use `{field_name}: true` or `{field_name}: false`."

    # Enum field with invalid value
    if field_name in _ENUM_FIELDS:
        choices = _ENUM_FIELDS[field_name]
        choices_str = ", ".join(f'"{c}"' for c in choices)
        return f"Valid values are: {choices_str}."

    return None


def _hint_for_cross_field(field_names: list[str]) -> str | None:
    """Return a hint for cross-field constraint violations."""
    field_set = set(field_names)
    for a, b in _MUTUAL_EXCLUSIONS:
        if a in field_set and b in field_set:
            return (
                f"`{a}` and `{b}` are mutually exclusive. "
                f"Set one to false or remove it from your configuration."
            )
    for required_by, requires in _REQUIRES:
        if required_by in field_set:
            return f"`{required_by}` requires `{requires}` to also be set."
    return None


# ---------------------------------------------------------------------------
# CondaConfigError
# ---------------------------------------------------------------------------


class CondaConfigError(Exception):
    """Validation error for conda configuration with source provenance.

    Wraps a Pydantic ``ValidationError`` and enriches each field error with
    a ``ProvenanceInfo`` so that error messages reference the exact file,
    line number, or environment variable that produced the invalid value.

    Human-readable output via ``str(err)`` and machine-readable output via
    ``err.as_dict()``.
    """

    def __init__(
        self,
        pydantic_error: ValidationError,
        provenance: ProvenanceMap,
    ) -> None:
        self._pydantic_error = pydantic_error
        self._provenance = provenance
        super().__init__(str(self))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _field_errors(self) -> list[dict[str, Any]]:
        """Return a list of enriched error dicts, one per field error."""
        errors = []
        for err in self._pydantic_error.errors(include_url=False):
            loc = err.get("loc", ())
            field_name = loc[0] if loc else "<unknown>"
            raw_value = err.get("input")
            prov: ProvenanceInfo | None = self._provenance.get(str(field_name))

            hint = _generate_hint(str(field_name), raw_value)
            if hint is None:
                # Try cross-field hint using all field names in this error batch
                hint = _hint_for_cross_field([str(loc_item) for loc_item in loc])

            source: dict[str, Any] = {}
            if prov is not None:
                source["type"] = prov.source_type
                if prov.path is not None:
                    source["path"] = str(prov.path)
                if prov.line is not None:
                    source["line"] = prov.line
                if prov.env_var is not None:
                    source["env_var"] = prov.env_var

            errors.append(
                {
                    "field": str(field_name),
                    "value": raw_value,
                    "message": err.get("msg", ""),
                    "hint": hint,
                    "source": source,
                }
            )
        return errors

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def as_dict(self) -> list[dict[str, Any]]:
        """Return a JSON-serialisable list of field error dicts.

        Each dict has keys: ``field``, ``value``, ``message``, ``hint``,
        and ``source`` (with sub-keys ``type``, and optionally ``path``,
        ``line``, ``env_var``).
        """
        return self._field_errors()

    def __str__(self) -> str:
        lines: list[str] = ["Configuration validation failed:\n"]
        for entry in self._field_errors():
            field = entry["field"]
            value = entry["value"]
            message = entry["message"]
            hint = entry["hint"]
            source = entry["source"]

            lines.append(f"  Field:   {field}")
            lines.append(f"  Value:   {value!r}")
            lines.append(f"  Error:   {message}")

            if source:
                src_type = source.get("type", "")
                if src_type == "yaml_file":
                    loc = source.get("path", "")
                    if "line" in source:
                        loc = f"{loc}, line {source['line']}"
                    lines.append(f"  Source:  {loc}")
                elif src_type == "env_var":
                    lines.append(f"  Source:  environment variable {source['env_var']}")
                elif src_type == "argparse":
                    lines.append("  Source:  command-line argument")

            if hint:
                lines.append(f"  Hint:    {hint}")

            lines.append("")  # blank separator between errors

        return "\n".join(lines).rstrip()

    def __repr__(self) -> str:
        return f"CondaConfigError({len(self._field_errors())} field error(s))"
