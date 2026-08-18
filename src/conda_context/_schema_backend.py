"""
_schema_backend — library-agnostic validation backend abstraction.

Provides a uniform interface over Pydantic v2 and msgspec so that
``Context`` and ``CondaConfigError`` are decoupled from any specific
validation library.

Usage::

    backend = get_backend("pydantic")   # or "msgspec"
    config  = backend.build(merged_dict)
    errors  = backend.errors(exc)       # list[FieldError]
    meta    = backend.field_metadata()  # dict[str, FieldMetadata]
    name, value = backend.validate_single("ssl_verify", "true")
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Shared data types
# ---------------------------------------------------------------------------


@dataclass
class FieldError:
    """Library-agnostic representation of a single field validation error."""

    loc: tuple[str, ...]  # field path, e.g. ("ssl_verify",)
    input: Any  # the raw invalid value
    msg: str  # human-readable error message


@dataclass
class FieldMetadata:
    """Introspection metadata for a single configuration field."""

    aliases: list[str] = field(default_factory=list)
    description: str = ""
    annotation: Any = None


# ---------------------------------------------------------------------------
# Backend protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class BackendProtocol(Protocol):
    """Interface that every validation backend must implement."""

    def build(self, data: dict[str, Any]) -> Any:
        """Construct and validate a config object from a merged dict."""
        ...

    def validate_single(self, field_name: str, value: Any) -> tuple[str, Any]:
        """Coerce *value* for *field_name*.  Returns (canonical_name, coerced_value).

        On failure, returns (canonical_name, raw_value) unchanged — the
        caller is responsible for surfacing the error later.
        """
        ...

    def field_metadata(self) -> dict[str, FieldMetadata]:
        """Return a dict of canonical field name → FieldMetadata."""
        ...

    def errors(self, exc: Exception) -> list[FieldError]:
        """Translate a library-specific ValidationError to list[FieldError]."""
        ...


# ---------------------------------------------------------------------------
# Pydantic backend
# ---------------------------------------------------------------------------


class PydanticBackend:
    """Validation backend backed by Pydantic v2."""

    def build(self, data: dict[str, Any]) -> Any:
        from .schemas._26_5_3 import CondaConfig

        return CondaConfig(**data)

    def validate_single(self, field_name: str, value: Any) -> tuple[str, Any]:
        import pydantic

        from .schemas._26_5_3 import CondaConfig

        try:
            coerced = CondaConfig.model_validate({field_name: value})
            return (field_name, getattr(coerced, field_name))
        except pydantic.ValidationError:
            return (field_name, value)

    def field_metadata(self) -> dict[str, FieldMetadata]:
        from .schemas._26_5_3 import CondaConfig

        result: dict[str, FieldMetadata] = {}
        for name, info in CondaConfig.model_fields.items():
            aliases: list[str] = []
            if info.alias and info.alias != name:
                aliases.append(info.alias)
            va = info.validation_alias
            if va is not None:
                if isinstance(va, str):
                    aliases.append(va)
                elif hasattr(va, "choices"):
                    for choice in va.choices:
                        if isinstance(choice, str):
                            aliases.append(choice)
            result[name] = FieldMetadata(
                aliases=aliases,
                description=info.description or "",
                annotation=info.annotation,
            )
        return result

    def errors(self, exc: Exception) -> list[FieldError]:
        import pydantic

        if not isinstance(exc, pydantic.ValidationError):
            return [FieldError(loc=("<unknown>",), input=None, msg=str(exc))]

        out: list[FieldError] = []
        for err in exc.errors(include_url=False):
            loc_raw = err.get("loc", ())
            loc = tuple(str(x) for x in loc_raw) if loc_raw else ("<unknown>",)
            out.append(
                FieldError(
                    loc=loc,
                    input=err.get("input"),
                    msg=err.get("msg", ""),
                )
            )
        return out


# ---------------------------------------------------------------------------
# msgspec backend
# ---------------------------------------------------------------------------

# Alias keys → canonical Python attribute names.
# These are the 23 pydantic Field(alias=...) entries where alias != field name.
_ALIAS_TO_CANONICAL: dict[str, str] = {
    "self_update": "auto_update_conda",
    "auto_activate_base": "auto_activate",
    "env_spec": "environment_specifier",
    "pip_interop_enabled": "prefix_data_interoperability",
    "disallow": "disallowed_packages",
    "root_dir": "root_prefix",
    "envs_path": "envs_dirs",
    "extra_platforms": "export_platforms",
    "verify_ssl": "ssl_verify",
    "client_cert": "client_ssl_cert",
    "client_cert_key": "client_ssl_cert_key",
    "add_binstar_token": "add_anaconda_token",
    "channel": "channels",
    "whitelist_channels": "allowlist_channels",
    "softlink": "always_softlink",
    "copy": "always_copy",
    "yes": "always_yes",
    "verbose": "verbosity",
    "json": "json_output",
    "experimental_solver": "solver",
    "binstar_upload": "anaconda_upload",
    "conda-build": "conda_build",
    "virtual_packages": "override_virtual_packages",
}

# Regex to extract field path from msgspec error messages.
# Format: "Expected `X`, got `Y` - at `$.field_name`"
_MSGSPEC_AT_RE = re.compile(r" - at `\$\.([^`]+)`")


def normalize_alias_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Translate legacy alias keys to canonical Python attribute names.

    This is needed because MergeEngine passes YAML keys verbatim (a user may
    write ``verify_ssl: false`` in .condarc) while msgspec.convert only
    recognises canonical attribute names.

    Cost: ~0.45µs for a typical 10-key merged dict — negligible.
    """
    return {_ALIAS_TO_CANONICAL.get(k, k): v for k, v in data.items()}


class MsgspecBackend:
    """Validation backend backed by msgspec."""

    def build(self, data: dict[str, Any]) -> Any:
        import msgspec

        from .schemas._26_5_3_msgspec import CondaConfigMsgspec

        return msgspec.convert(normalize_alias_keys(data), CondaConfigMsgspec)

    def validate_single(self, field_name: str, value: Any) -> tuple[str, Any]:
        import msgspec

        from .schemas._26_5_3_msgspec import CondaConfigMsgspec

        try:
            coerced = msgspec.convert({field_name: value}, CondaConfigMsgspec)
            return (field_name, getattr(coerced, field_name))
        except msgspec.ValidationError:
            return (field_name, value)

    def field_metadata(self) -> dict[str, FieldMetadata]:
        import msgspec.structs

        from .schemas._26_5_3_msgspec import (
            _ALIAS_TO_CANONICAL as _A2C,
            _FIELD_DESCRIPTIONS,
            CondaConfigMsgspec,
        )

        # Build reverse map: canonical → list[alias]
        canonical_to_aliases: dict[str, list[str]] = {}
        for alias, canonical in _A2C.items():
            canonical_to_aliases.setdefault(canonical, []).append(alias)

        result: dict[str, FieldMetadata] = {}
        for f in msgspec.structs.fields(CondaConfigMsgspec):
            result[f.name] = FieldMetadata(
                aliases=canonical_to_aliases.get(f.name, []),
                description=_FIELD_DESCRIPTIONS.get(f.name, ""),
                annotation=f.type,
            )
        return result

    def errors(self, exc: Exception) -> list[FieldError]:
        import msgspec

        if not isinstance(exc, msgspec.ValidationError):
            return [FieldError(loc=("<unknown>",), input=None, msg=str(exc))]

        msg = str(exc)
        # msgspec only gives one error at a time; extract field path if present.
        m = _MSGSPEC_AT_RE.search(msg)
        if m:
            field_path = m.group(1)
            loc: tuple[str, ...] = tuple(field_path.split("."))
            message = msg[: m.start()]
        else:
            # __post_init__ raised ValueError — no path in message.
            # The message may contain multiple lines (one per cross-field error).
            loc = ("<root>",)
            message = msg

        return [FieldError(loc=loc, input=None, msg=message)]


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_BACKENDS: dict[str, type] = {
    "pydantic": PydanticBackend,
    "msgspec": MsgspecBackend,
}


def get_backend(name: str) -> PydanticBackend | MsgspecBackend:
    """Return a backend instance for *name*.

    Args:
        name: One of ``"pydantic"`` or ``"msgspec"``.

    Raises:
        ValueError: If *name* is not a known backend.
    """
    cls = _BACKENDS.get(name)
    if cls is None:
        known = ", ".join(f'"{k}"' for k in _BACKENDS)
        raise ValueError(
            f"Unknown conda_context_backend {name!r}. Valid values are: {known}."
        )
    return cls()
