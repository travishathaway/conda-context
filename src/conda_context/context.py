"""
Context — drop-in replacement for conda.base.context.Context.

Structurally mirrors conda 26.5.3's Context class, exposing the same public
and private API surface required for plugin use and module-attribute
monkey-patching.

Architecture (from design.md D1):
  - ``CondaConfig`` (Pydantic) or ``CondaConfigMsgspec`` (msgspec) handles
    type coercion and validation. The backend is selected at runtime via the
    ``conda_context_backend`` configuration field.
  - ``MergeEngine`` resolves layered sources + builds ProvenanceMap.
  - ``Context`` wraps both, exposing conda's mutation protocol and all
    computed properties.
"""

from __future__ import annotations

import logging
import os
import platform
import struct
import sys
from argparse import Namespace
from collections.abc import Iterator
from contextlib import contextmanager
from functools import cached_property
from os.path import abspath, expanduser, isdir, isfile, join
from pathlib import Path
from typing import Any, ClassVar

import pydantic
import msgspec as _msgspec

from ._schema_backend import get_backend
from .constants import (
    APP_NAME,
    DEFAULT_CHANNELS_UNIX,
    DEFAULT_CHANNELS_WIN,
    ROOT_ENV_NAME,
)
from .constants import (
    SEARCH_PATH as _FALLBACK_SEARCH_PATH,
)
from .errors import CondaConfigError
from .merge import MergeEngine
from .provenance import ProvenanceMap

log = logging.getLogger(__name__)

# Try to get the actual search path from conda if available
try:
    from conda.base.constants import (
        SEARCH_PATH as _DEFAULT_SEARCH_PATH,  # type: ignore[import]
    )
except ImportError:
    _DEFAULT_SEARCH_PATH = _FALLBACK_SEARCH_PATH
_non_x86_machines = frozenset(
    (
        "armv6l",
        "armv7l",
        "aarch64",
        "arm64",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390x",
    )
)

_platform_map = {
    "linux2": "linux",
    "linux": "linux",
    "darwin": "osx",
    "win32": "win",
    "zos": "zos",
}

_arch_names = {32: "x86", 64: "x86_64"}

# Prefix magic file used to test root_writable
PREFIX_MAGIC_FILE = join("conda-meta", "history")

# KNOWN_SUBDIRS is large; we use a minimal set here
KNOWN_SUBDIRS = frozenset(
    (
        "noarch",
        "linux-32",
        "linux-64",
        "linux-aarch64",
        "linux-ppc64",
        "linux-ppc64le",
        "linux-s390x",
        "osx-64",
        "osx-arm64",
        "win-32",
        "win-64",
        "win-arm64",
        "zos-z",
    )
)

# Try to get the actual search path from conda if available
try:
    from conda.base.constants import (
        SEARCH_PATH as _DEFAULT_SEARCH_PATH,  # type: ignore[import]
    )
except ImportError:
    _DEFAULT_SEARCH_PATH = _FALLBACK_SEARCH_PATH

# ---------------------------------------------------------------------------
# Module-level re-exports expected by conda modules that do
#   ``from conda.base.context import <name>``
# When the import hook redirects conda.base.context → this module these names
# must be present at module scope.
# ---------------------------------------------------------------------------

# Public aliases for the private arch / platform sets
non_x86_machines = _non_x86_machines  # re-export

# sys_rc_path / user_rc_path: string paths to the system and user condarc.
# Prefer conda's own values (which honour CONDA_ROOT) when available.
try:
    from conda.base.context import (  # type: ignore[import]
        sys_rc_path as sys_rc_path,
    )
    from conda.base.context import (
        user_rc_path as user_rc_path,
    )
except ImportError:
    # Fallback: derive them from the search-path constants ourselves.
    sys_rc_path = str(Path(sys.prefix) / ".condarc")
    user_rc_path = str(Path.home() / ".condarc")

# Utility functions that conda imports from conda.base.context.
# Re-export from conda when available; provide minimal stubs otherwise.
try:
    from conda.base.context import (  # type: ignore[import]
        determine_target_prefix as determine_target_prefix,
    )
    from conda.base.context import (
        env_name as env_name,
    )
    from conda.base.context import (
        locate_prefix_by_name as locate_prefix_by_name,
    )
    from conda.base.context import (
        validate_channels as validate_channels,
    )
except ImportError:
    # Stubs used when conda is not installed (keeps the module importable).
    def determine_target_prefix(ctx: Any, args: Any = None) -> str:  # type: ignore[misc]
        """Stub: return the default prefix."""
        return sys.prefix

    def env_name(prefix: Any) -> str | None:  # type: ignore[misc]
        """Stub: derive an env name from a prefix path."""
        if not prefix:
            return None
        prefix_path = Path(str(prefix))
        if prefix_path == Path(sys.prefix):
            return ROOT_ENV_NAME
        return prefix_path.name

    def locate_prefix_by_name(name: str, envs_dirs: Any = None) -> str:  # type: ignore[misc]
        """Stub: locate a named environment."""
        if not name:
            raise ValueError("'name' cannot be empty.")
        search_dirs = list(envs_dirs or [Path(sys.prefix).parent])
        for d in search_dirs:
            candidate = Path(str(d)) / name
            if candidate.is_dir():
                return str(candidate)
        raise OSError(f"No environment named {name!r} found.")

    def validate_channels(channels: Any) -> Any:  # type: ignore[misc]
        """Stub: pass channels through unchanged."""
        return channels


def _unique(iterable):
    """Yield unique items preserving order."""
    seen = set()
    for item in iterable:
        if item not in seen:
            seen.add(item)
            yield item


def _expand(path: str) -> str:
    """Expand user and environment variables in a path string."""
    return abspath(expanduser(os.path.expandvars(path)))


class Context:
    """Pydantic-backed replacement for ``conda.base.context.Context``.

    Supports the same public and private API as conda 26.5.3's Context,
    including the mutation protocol (``_set_search_path``, ``_reset_cache``,
    ``_set_argparse_args``, ``_set_env_vars``) and all computed properties.

    Args:
        search_path: Sequence of file/directory paths to search for condarc
            files, in ascending priority order.
        argparse_args: Parsed CLI arguments (``argparse.Namespace``).
        **kwargs: Additional keyword arguments (ignored, for API compatibility).
    """

    # ------------------------------------------------------------------
    # Class-level metadata — mirrors conda.base.context.Context
    # ------------------------------------------------------------------

    category_map: ClassVar[dict[str, tuple[str, ...]]] = {
        "Channel Configuration": (
            "channels",
            "channel_alias",
            "channel_settings",
            "default_channels",
            "override_channels_enabled",
            "allowlist_channels",
            "denylist_channels",
            "custom_channels",
            "custom_multichannels",
            "migrated_channel_aliases",
            "migrated_custom_channels",
            "add_anaconda_token",
            "allow_non_channel_urls",
            "repodata_fns",
            "use_only_tar_bz2",
            "repodata_threads",
            "fetch_threads",
            "experimental",
            "no_lock",
            "repodata_use_zst",
            "repodata_use_shards",
        ),
        "Basic Conda Configuration": (
            "envs_dirs",
            "pkgs_dirs",
            "default_threads",
            "preview",
        ),
        "Network Configuration": (
            "client_ssl_cert",
            "client_ssl_cert_key",
            "local_repodata_ttl",
            "offline",
            "proxy_servers",
            "remote_connect_timeout_secs",
            "remote_max_retries",
            "remote_backoff_factor",
            "remote_read_timeout_secs",
            "ssl_verify",
        ),
        "Solver Configuration": (
            "aggressive_update_packages",
            "auto_update_conda",
            "channel_priority",
            "create_default_packages",
            "disallowed_packages",
            "force_reinstall",
            "pinned_packages",
            "prefix_data_interoperability",
            "track_features",
            "solver",
        ),
        "Package Linking and Install-time Configuration": (
            "allow_softlinks",
            "always_copy",
            "always_softlink",
            "path_conflict",
            "rollback_enabled",
            "safety_checks",
            "extra_safety_checks",
            "signing_metadata_url_base",
            "shortcuts",
            "shortcuts_only",
            "non_admin_enabled",
            "separate_format_cache",
            "verify_threads",
            "execute_threads",
        ),
        "Conda-build Configuration": (
            "bld_path",
            "croot",
            "anaconda_upload",
            "conda_build",
        ),
        "Output, Prompt, and Flow Control Configuration": (
            "always_yes",
            "auto_activate",
            "default_activation_env",
            "auto_stack",
            "changeps1",
            "env_prompt",
            "json",
            "console",
            "notify_outdated_conda",
            "quiet",
            "report_errors",
            "show_channel_urls",
            "list_fields",
            "verbosity",
            "unsatisfiable_hints",
            "unsatisfiable_hints_check_depth",
            "number_channel_notices",
            "envvars_force_uppercase",
            "export_platforms",
            "override_virtual_packages",
        ),
        "CLI-only": (
            "deps_modifier",
            "update_modifier",
            "force",
            "force_remove",
            "clobber",
            "dry_run",
            "download_only",
            "ignore_pinned",
            "use_index_cache",
            "use_local",
        ),
        "Hidden and Undocumented": (
            "allow_cycles",
            "allow_conda_downgrades",
            "add_pip_as_python_dependency",
            "debug",
            "trace",
            "dev",
            "default_python",
            "enable_private_envs",
            "error_upload_url",
            "force_32bit",
            "root_prefix",
            "sat_solver",
            "solver_ignore_timestamps",
            "subdir",
            "subdirs",
            "target_prefix_override",
            "register_envs",
            "protect_frozen_envs",
        ),
        "Plugin Configuration": ("no_plugins",),
        "Experimental": ("environment_specifier",),
    }

    def __init__(
        self,
        search_path: tuple[str | Path, ...] | None = None,
        argparse_args: Namespace | None = None,
        **kwargs: Any,
    ) -> None:
        self._cache_: dict[str, Any] = {}
        self._reset_callbacks: dict[Any, None] = {}
        self._validation_errors: list[Any] = []

        self._set_search_path(_DEFAULT_SEARCH_PATH if search_path is None else search_path)
        self._set_env_vars(APP_NAME)
        self._set_argparse_args(argparse_args)

    # ------------------------------------------------------------------
    # Mutation protocol (mirrors conda's Configuration base class)
    # ------------------------------------------------------------------

    def _set_search_path(
        self,
        search_path: tuple[str | Path, ...],
        **kwargs: Any,
    ) -> Context:
        self._search_path = tuple(search_path)
        self._rebuild()
        return self

    def _set_env_vars(self, app_name: str | None = None) -> Context:
        self._app_name = app_name
        self._rebuild()
        return self

    def _set_argparse_args(self, argparse_args: Namespace | None) -> Context:
        if hasattr(argparse_args, "__dict__"):
            items = vars(argparse_args).items()
        elif not argparse_args:
            items = ()
        else:
            items = argparse_args.items() if hasattr(argparse_args, "items") else ()

        # Filter out None values and conda's auxlib _Null sentinel (which is
        # falsy but not None — it appears in argparse Namespaces when a flag
        # was not supplied on the command line).
        def _is_set(v: Any) -> bool:
            if v is None:
                return False
            # Detect conda.auxlib._Null by type name without importing auxlib
            if type(v).__name__ == "_Null":
                return False
            return True

        self._argparse_args = {k: v for k, v in items if _is_set(v)}
        self._rebuild()
        return self

    def _reset_cache(self) -> None:
        self._cache_ = {}
        # Invalidate cached_property values
        for key in list(self.__dict__.keys()):
            if key.startswith("_") and not key.startswith("__"):
                continue
            # Remove cached_property cache entries
            if key in type(self).__dict__ and isinstance(type(self).__dict__[key], cached_property):
                self.__dict__.pop(key, None)
        # Fire registered reset callbacks (matches conda's behaviour)
        for cb in list(self._reset_callbacks):
            try:
                cb()
            except Exception:
                pass

    def register_reset_callaback(self, callback: Any) -> None:  # noqa: N802  (typo matches conda's API)
        """Register a callable to be invoked on every cache reset.

        Note: The misspelling "callaback" matches conda 26.5.3's public API
        exactly — changing it would break callers such as
        ``conda.models.channel``.
        """
        self._reset_callbacks.setdefault(callback, None)

    def validate_configuration(self) -> None:
        """Validate the current configuration, raising CondaConfigError on failure.

        Replaces conda's ``Context.validate_configuration()`` with a
        provenance-aware version: any ValidationError is enriched
        with the exact file/line or env-var origin of each bad value before
        being re-raised as ``CondaConfigError``.

        Called by ``conda install``, ``conda config``, and friends.
        """
        try:
            self._backend.build(self.raw_data)
        except (pydantic.ValidationError, _msgspec.ValidationError) as exc:
            raise CondaConfigError(self._backend.errors(exc), self._provenance) from exc

    def validate_all(self) -> None:
        """Validate all configuration sources, raising CondaConfigError on failure.

        Mirrors conda's ``Context.validate_all()``.  In conda's original
        implementation this iterates over each raw_data source separately; here
        we delegate to ``validate_configuration()`` which covers the full merged
        view.
        """
        self.validate_configuration()

    # ------------------------------------------------------------------
    # Parameter introspection — mirrors conda's ParameterLoader-based API
    # ------------------------------------------------------------------
    # conda's Context derives these from a metaclass that builds a
    # ``_parameter_loaders`` dict from ``ParameterLoader`` descriptors.
    # We derive equivalent information from ``CondaConfig.model_fields``
    # so that calls like ``context.list_parameters()`` and
    # ``context.parameter_names`` continue to work.

    @property
    def parameter_names(self) -> tuple[str, ...]:
        """All canonical parameter names (including private ``_`` prefixed ones).

        Returns the names that ``list_parameters()`` is derived from.
        Non-aliased fields use the canonical field name; aliased fields use
        ``_<field_name>`` to signal they are "private" in conda's convention.
        """
        meta = self._backend.field_metadata()
        names: list[str] = []
        for field_name, field_meta in meta.items():
            if field_meta.aliases:
                names.append(f"_{field_name}")
            else:
                names.append(field_name)
        return tuple(names)

    @property
    def parameter_names_and_aliases(self) -> tuple[str, ...]:
        """All parameter names including all registered aliases."""
        meta = self._backend.field_metadata()
        seen: dict[str, None] = {}
        for field_name, field_meta in meta.items():
            seen[field_name] = None
            for alias in field_meta.aliases:
                seen[alias] = None
        return tuple(seen)

    def list_parameters(self, aliases: bool = False) -> tuple[str, ...]:
        """Return all parameter names that are valid ``getattr`` targets on ``Context``.

        Mirrors ``conda.base.context.Context.list_parameters()``.

        The returned names are the actual ``@property`` names on the ``Context``
        class — the same names used by ``conda config --show`` with ``getattr``.
        This is derived from ``category_map``, which is the authoritative source
        of Context property names.

        Args:
            aliases: If ``True``, include all aliases in insertion order.
                     If ``False`` (default), return sorted property names.
        """
        if aliases:
            return self.parameter_names_and_aliases
        # category_map values are the actual Context property names
        all_names: dict[str, None] = {}
        for names in self.category_map.values():
            for name in names:
                all_names[name] = None
        return tuple(sorted(all_names))

    def name_for_alias(self, alias: str, ignore_private: bool = True) -> str | None:
        """Return the canonical parameter name for *alias*, or ``None``.

        Mirrors ``conda.base.context.Context.name_for_alias()``.
        """
        meta = self._backend.field_metadata()
        for field_name, field_meta in meta.items():
            candidates = [field_name, *field_meta.aliases]
            if alias in candidates:
                if ignore_private and field_name.startswith("_"):
                    return None
                return field_name
        return None

    def describe_parameter(self, parameter_name: str) -> dict[str, Any]:
        """Return a description dict for *parameter_name*.

        Mirrors the shape returned by conda's ``Context.describe_parameter()``:
        ``{"name": ..., "aliases": [...], "description": ..., "parameter_type": ...}``.

        Raises ``KeyError`` if the parameter is unknown.
        """
        lookup = parameter_name.lstrip("_")
        meta = self._backend.field_metadata()
        if lookup not in meta:
            raise KeyError(parameter_name)
        field_meta = meta[lookup]
        return {
            "name": lookup,
            "aliases": field_meta.aliases,
            "description": field_meta.description,
            "parameter_type": str(field_meta.annotation),
        }

    def typify_parameter(self, parameter_name: str, value: Any, source: Any) -> tuple[str, Any]:
        """Coerce *value* to the correct type for *parameter_name*.

        Mirrors ``conda.base.context.Context.typify_parameter()``.
        Returns a ``(canonical_name, typed_value)`` tuple.

        Raises ``KeyError`` if the parameter is unknown.
        """
        lookup = parameter_name.lstrip("_")
        meta = self._backend.field_metadata()
        if lookup not in meta:
            raise KeyError(parameter_name)
        return self._backend.validate_single(lookup, value)

    def _rebuild(self) -> None:
        """Re-run merge and validation after any source change."""
        self._reset_cache()
        engine = MergeEngine(
            search_path=self._search_path,
            argparse_args=Namespace(**self._argparse_args)
            if hasattr(self, "_argparse_args") and self._argparse_args
            else None,
        )
        merged, provenance = engine.resolve()
        self.raw_data = merged
        self._provenance: ProvenanceMap = provenance

        backend_name = merged.get("conda_context_backend", "pydantic")
        self._backend = get_backend(backend_name)

        try:
            self._config = self._backend.build(merged)
        except (pydantic.ValidationError, _msgspec.ValidationError) as exc:
            raise CondaConfigError(self._backend.errors(exc), provenance) from exc

    # ------------------------------------------------------------------
    # Raw config field properties — delegate to CondaConfig
    # ------------------------------------------------------------------

    @property
    def add_pip_as_python_dependency(self) -> bool:
        return self._config.add_pip_as_python_dependency

    @property
    def allow_conda_downgrades(self) -> bool:
        return self._config.allow_conda_downgrades

    @property
    def allow_cycles(self) -> bool:
        return self._config.allow_cycles

    @property
    def allow_softlinks(self) -> bool:
        return self._config.allow_softlinks

    @property
    def auto_update_conda(self) -> bool:
        return self._config.auto_update_conda

    @property
    def auto_activate(self) -> bool:
        return self._config.auto_activate

    @property
    def _default_activation_env(self) -> str:
        return self._config.default_activation_env

    @property
    def auto_stack(self) -> int:
        return self._config.auto_stack

    @property
    def notify_outdated_conda(self) -> bool:
        return self._config.notify_outdated_conda

    @property
    def clobber(self) -> bool:
        return self._config.clobber

    @property
    def changeps1(self) -> bool:
        return self._config.changeps1

    @property
    def env_prompt(self) -> str:
        return self._config.env_prompt

    @property
    def environment_specifier(self) -> str | None:
        return self._config.environment_specifier

    @property
    def _create_default_packages(self) -> tuple[str, ...]:
        return self._config.create_default_packages

    @property
    def register_envs(self) -> bool:
        return self._config.register_envs

    @property
    def protect_frozen_envs(self) -> bool:
        return self._config.protect_frozen_envs

    @property
    def default_python(self) -> str | None:
        return self._config.default_python

    @property
    def download_only(self) -> bool:
        return self._config.download_only

    @property
    def enable_private_envs(self) -> bool:
        return self._config.enable_private_envs

    @property
    def force_32bit(self) -> bool:
        return self._config.force_32bit

    @property
    def non_admin_enabled(self) -> bool:
        return self._config.non_admin_enabled

    @property
    def prefix_data_interoperability(self) -> bool:
        return self._config.prefix_data_interoperability

    @property
    def _default_threads(self) -> int:
        return self._config.default_threads

    @property
    def _repodata_threads(self) -> int:
        return self._config.repodata_threads

    @property
    def _fetch_threads(self) -> int:
        return self._config.fetch_threads

    @property
    def _verify_threads(self) -> int:
        return self._config.verify_threads

    @property
    def _execute_threads(self) -> int:
        return self._config.execute_threads

    @property
    def _aggressive_update_packages(self) -> tuple[str, ...]:
        return self._config.aggressive_update_packages

    @property
    def safety_checks(self) -> str:
        return str(self._config.safety_checks)

    @property
    def extra_safety_checks(self) -> bool:
        return self._config.extra_safety_checks

    @property
    def _signing_metadata_url_base(self) -> str | None:
        return self._config.signing_metadata_url_base

    @property
    def path_conflict(self) -> str:
        return str(self._config.path_conflict)

    @property
    def pinned_packages(self) -> tuple[str, ...]:
        return self._config.pinned_packages

    @property
    def disallowed_packages(self) -> tuple[str, ...]:
        return self._config.disallowed_packages

    @property
    def rollback_enabled(self) -> bool:
        return self._config.rollback_enabled

    @property
    def track_features(self) -> tuple[str, ...]:
        return self._config.track_features

    @property
    def use_index_cache(self) -> bool:
        return self._config.use_index_cache

    @property
    def separate_format_cache(self) -> bool:
        return self._config.separate_format_cache

    @property
    def _root_prefix(self) -> str:
        return self._config.root_prefix

    @property
    def _envs_dirs(self) -> tuple[str, ...]:
        return self._config.envs_dirs

    @property
    def _pkgs_dirs(self) -> tuple[str, ...]:
        return self._config.pkgs_dirs

    @property
    def _subdir(self) -> str:
        return self._config.subdir

    @property
    def _subdirs(self) -> tuple[str, ...]:
        return self._config.subdirs

    @property
    def _export_platforms(self) -> tuple[str, ...]:
        return self._config.export_platforms

    @property
    def local_repodata_ttl(self) -> bool | int:
        return self._config.local_repodata_ttl

    @property
    def ssl_verify(self) -> bool | str:
        return self._config.ssl_verify

    @property
    def client_ssl_cert(self) -> str | None:
        return self._config.client_ssl_cert

    @property
    def client_ssl_cert_key(self) -> str | None:
        return self._config.client_ssl_cert_key

    @property
    def proxy_servers(self) -> dict[str, str | None]:
        return self._config.proxy_servers

    @property
    def remote_connect_timeout_secs(self) -> float:
        return self._config.remote_connect_timeout_secs

    @property
    def remote_read_timeout_secs(self) -> float:
        return self._config.remote_read_timeout_secs

    @property
    def remote_max_retries(self) -> int:
        return self._config.remote_max_retries

    @property
    def remote_backoff_factor(self) -> int:
        return self._config.remote_backoff_factor

    @property
    def add_anaconda_token(self) -> bool:
        return self._config.add_anaconda_token

    @property
    def allow_non_channel_urls(self) -> bool:
        return self._config.allow_non_channel_urls

    @property
    def _channel_alias(self) -> str:
        return self._config.channel_alias

    @property
    def channel_priority(self) -> str:
        return str(self._config.channel_priority)

    @property
    def _channels(self) -> tuple[str, ...]:
        return self._config.channels

    @property
    def channel_settings(self) -> tuple[dict[str, str], ...]:
        return self._config.channel_settings

    @property
    def _custom_channels(self) -> dict[str, str]:
        return self._config.custom_channels

    @property
    def _custom_multichannels(self) -> dict[str, list[str]]:
        return self._config.custom_multichannels

    @property
    def _default_channels(self) -> tuple[str, ...]:
        return self._config.default_channels

    @property
    def _migrated_channel_aliases(self) -> tuple[str, ...]:
        return self._config.migrated_channel_aliases

    @property
    def migrated_custom_channels(self) -> dict[str, str]:
        return self._config.migrated_custom_channels

    @property
    def override_channels_enabled(self) -> bool:
        return self._config.override_channels_enabled

    @property
    def show_channel_urls(self) -> bool | None:
        return self._config.show_channel_urls

    @property
    def use_local(self) -> bool:
        return self._config.use_local

    @property
    def allowlist_channels(self) -> tuple[str, ...]:
        return self._config.allowlist_channels

    @property
    def denylist_channels(self) -> tuple[str, ...]:
        return self._config.denylist_channels

    @property
    def repodata_fns(self) -> tuple[str, ...]:
        return self._config.repodata_fns

    @property
    def _use_only_tar_bz2(self) -> bool | None:
        return self._config.use_only_tar_bz2

    @property
    def always_softlink(self) -> bool:
        return self._config.always_softlink

    @property
    def always_copy(self) -> bool:
        return self._config.always_copy

    @property
    def always_yes(self) -> bool | None:
        return self._config.always_yes

    @property
    def _debug(self) -> bool:
        return self._config.debug

    @property
    def _trace(self) -> bool:
        return self._config.trace

    @property
    def dev(self) -> bool:
        return self._config.dev

    @property
    def dry_run(self) -> bool:
        return self._config.dry_run

    @property
    def _error_upload_url(self) -> str:
        return self._config.error_upload_url

    @property
    def force(self) -> bool:
        return self._config.force

    @property
    def json(self) -> bool:
        return self._config.json_output

    @property
    def _console(self) -> str:
        return self._config.console

    @property
    def list_fields(self) -> tuple[str, ...]:
        return self._config.list_fields

    @property
    def offline(self) -> bool:
        return self._config.offline

    @property
    def quiet(self) -> bool:
        return self._config.quiet

    @property
    def ignore_pinned(self) -> bool:
        return self._config.ignore_pinned

    @property
    def _report_errors(self) -> bool | None:
        return self._config.report_errors

    @property
    def shortcuts(self) -> bool:
        return self._config.shortcuts

    @property
    def number_channel_notices(self) -> int:
        return self._config.number_channel_notices

    @property
    def shortcuts_only(self) -> tuple[str, ...]:
        return self._config.shortcuts_only

    @property
    def _verbosity(self) -> int:
        return self._config.verbosity

    @property
    def experimental(self) -> tuple[str, ...]:
        return self._config.experimental

    @property
    def preview(self) -> tuple[str, ...]:
        return self._config.preview

    @property
    def no_lock(self) -> bool:
        return self._config.no_lock

    @property
    def repodata_use_zst(self) -> bool:
        return self._config.repodata_use_zst

    @property
    def repodata_use_shards(self) -> bool:
        return self._config.repodata_use_shards

    @property
    def envvars_force_uppercase(self) -> bool:
        return self._config.envvars_force_uppercase

    @property
    def deps_modifier(self) -> str:
        return str(self._config.deps_modifier)

    @property
    def update_modifier(self) -> str:
        return str(self._config.update_modifier)

    @property
    def sat_solver(self) -> str:
        return str(self._config.sat_solver)

    @property
    def solver_ignore_timestamps(self) -> bool:
        return self._config.solver_ignore_timestamps

    @property
    def solver(self) -> str:
        return self._config.solver

    @property
    def force_remove(self) -> bool:
        return self._config.force_remove

    @property
    def force_reinstall(self) -> bool:
        return self._config.force_reinstall

    @property
    def target_prefix_override(self) -> str:
        return self._config.target_prefix_override

    @property
    def unsatisfiable_hints(self) -> bool:
        return self._config.unsatisfiable_hints

    @property
    def unsatisfiable_hints_check_depth(self) -> int:
        return self._config.unsatisfiable_hints_check_depth

    @property
    def bld_path(self) -> str:
        return self._config.bld_path

    @property
    def anaconda_upload(self) -> bool | None:
        return self._config.anaconda_upload

    @property
    def _croot(self) -> str:
        return self._config.croot

    @property
    def _conda_build(self) -> dict[str, str]:
        return self._config.conda_build

    @property
    def _override_virtual_packages(self) -> dict[str, str | None]:
        return self._config.override_virtual_packages

    @property
    def no_plugins(self) -> bool:
        return self._config.no_plugins

    @property
    def conda_context_backend(self) -> str:
        return self._config.conda_context_backend

    # ------------------------------------------------------------------
    # Tier 1: Pure computed properties
    # ------------------------------------------------------------------

    @property
    def platform(self) -> str:
        return _platform_map.get(sys.platform, "unknown")

    @property
    def arch_name(self) -> str:
        m = platform.machine().lower()
        if m in _non_x86_machines:
            return m
        return _arch_names[self.bits]

    @property
    def bits(self) -> int:
        if self.force_32bit:
            return 32
        return 8 * struct.calcsize("P")

    @property
    def subdir(self) -> str:
        if self._subdir:
            return self._subdir
        return self._native_subdir()

    def _native_subdir(self) -> str:
        m = platform.machine().lower()
        if m in _non_x86_machines:
            return f"{self.platform}-{m}"
        elif self.platform == "zos":
            return "zos-z"
        return f"{self.platform}-{self.bits}"

    @property
    def subdirs(self) -> tuple[str, str]:
        return self._subdirs or (self.subdir, "noarch")

    @cached_property
    def known_subdirs(self) -> frozenset[str]:
        return frozenset((*KNOWN_SUBDIRS, *self.subdirs))

    @property
    def export_platforms(self) -> tuple[str, ...]:
        argparse_args = self._argparse_args or {}
        if argparse_args.get("override_platforms"):
            platforms = argparse_args.get("export_platforms") or ()
        else:
            platforms = self._export_platforms
        return tuple(_unique(platforms)) or (self.subdir,)

    @property
    def default_threads(self) -> int | None:
        return self._default_threads or None

    @property
    def repodata_threads(self) -> int | None:
        return self._repodata_threads or self.default_threads

    @property
    def fetch_threads(self) -> int | None:
        if self._fetch_threads == 0 and self._default_threads == 0:
            return 5
        return self._fetch_threads or self.default_threads

    @property
    def verify_threads(self) -> int | None:
        return self._verify_threads or self.default_threads

    @property
    def execute_threads(self) -> int | None:
        return self._execute_threads or 1

    @property
    def verbosity(self) -> int:
        return self._verbosity

    @property
    def trace(self) -> bool:
        return self._trace

    @property
    def debug(self) -> bool:
        return self._debug

    @property
    def info(self) -> bool:
        return self.verbosity >= 1

    @property
    def verbose(self) -> bool:
        return self.verbosity >= 1

    @property
    def log_level(self) -> int:
        import logging as _logging

        if self.trace:
            return 5  # TRACE
        elif self.debug:
            return _logging.DEBUG
        elif self.info:
            return _logging.INFO
        return _logging.WARNING

    @property
    def console(self) -> str:
        return self._console

    @property
    def default_activation_env(self) -> str:
        return self._default_activation_env

    @property
    def create_default_packages(self) -> tuple[str, ...]:
        return tuple(
            pkg for pkg in self._create_default_packages if pkg not in self.pinned_packages
        )

    @property
    def signing_metadata_url_base(self) -> str | None:
        return self._signing_metadata_url_base or None

    @property
    def binstar_upload(self) -> bool | None:
        return self._config.anaconda_upload

    @property
    def conda_build(self) -> dict[str, Any]:
        return dict(self._conda_build)

    @property
    def override_virtual_packages(self) -> dict[str, str | None]:
        return dict(self._override_virtual_packages)

    @property
    def default_activation_prefix(self) -> Path:
        """Path to the default activation environment."""
        env_name = self.default_activation_env
        if not env_name or env_name == ROOT_ENV_NAME:
            return Path(self.root_prefix)
        for envs_dir in self.envs_dirs:
            candidate = Path(envs_dir) / env_name
            if candidate.is_dir():
                return candidate
        return Path(self.root_prefix)

    # Channel-related computed properties
    # NOTE: These require conda for full resolution (Channel model objects).
    # They raise ImportError with a clear message when conda is not installed.

    @property
    def channels(self) -> tuple[str, ...]:
        """Resolved channel list.

        Requires conda for full alias resolution and validation.
        Falls back to raw _channels when conda is unavailable.
        """
        try:
            from conda.base.context import validate_channels  # type: ignore[import]

            local_channels: tuple[str, ...] = ("local",) if self.use_local else ()
            return validate_channels((*local_channels, *self._channels))
        except ImportError:
            return self._channels

    @property
    def channel_alias(self):  # type: ignore[return]
        """Resolved channel alias (Channel object).

        Requires conda. Returns raw string when conda unavailable.
        """
        try:
            from conda.common.url import split_scheme_auth_token  # type: ignore[import]
            from conda.models.channel import Channel  # type: ignore[import]

            location, scheme, auth, token = split_scheme_auth_token(self._channel_alias)
            return Channel(scheme=scheme, auth=auth, location=location, token=token)
        except ImportError:
            return self._channel_alias

    @property
    def migrated_channel_aliases(self) -> tuple:
        """Requires conda for Channel objects. Returns raw strings otherwise."""
        try:
            from conda.common.url import split_scheme_auth_token  # type: ignore[import]
            from conda.models.channel import Channel  # type: ignore[import]

            return tuple(
                Channel(scheme=scheme, auth=auth, location=location, token=token)
                for location, scheme, auth, token in (
                    split_scheme_auth_token(c) for c in self._migrated_channel_aliases
                )
            )
        except ImportError:
            return self._migrated_channel_aliases

    @property
    def default_channels(self):  # type: ignore[return]
        """Requires conda for Channel model objects."""
        try:
            return self.custom_multichannels.get("defaults", ())
        except Exception:
            return self._default_channels

    @property
    def custom_multichannels(self) -> dict:
        """Requires conda for Channel model objects."""
        try:
            from conda.models.channel import Channel  # type: ignore[import]

            on_win = sys.platform == "win32"
            if (
                not on_win
                and self.subdir.startswith("win-")
                and set(self._default_channels) == set(DEFAULT_CHANNELS_UNIX)
            ):
                default_channels = list(DEFAULT_CHANNELS_WIN)
            else:
                default_channels = list(self._default_channels)

            channel_alias = self.channel_alias

            def _make_channel(url: str) -> Channel:
                return Channel.make_simple_channel(channel_alias, url)

            result = {}
            for name, urls in self._custom_multichannels.items():
                result[name] = tuple(_make_channel(u) for u in urls)
            if "defaults" not in self._custom_multichannels:
                result["defaults"] = tuple(_make_channel(u) for u in default_channels)
            result["local"] = self.conda_build_local_urls
            return result
        except ImportError:
            return {**self._custom_multichannels, "defaults": self._default_channels}

    @property
    def custom_channels(self) -> dict:
        """Requires conda for Channel model objects."""
        try:
            from itertools import chain

            from conda.models.channel import Channel  # type: ignore[import]

            channel_alias = self.channel_alias
            return {
                ch.name: ch
                for ch in (
                    *chain.from_iterable(self.custom_multichannels.values()),
                    *(
                        Channel.make_simple_channel(channel_alias, url, name)
                        for name, url in self._custom_channels.items()
                    ),
                )
                if hasattr(ch, "name")
            }
        except ImportError:
            return self._custom_channels

    @property
    def aggressive_update_packages(self) -> tuple:
        """Requires conda for MatchSpec objects. Returns raw strings otherwise."""
        try:
            from conda.models.match_spec import MatchSpec  # type: ignore[import]

            return tuple(MatchSpec(s) for s in self._aggressive_update_packages)
        except ImportError:
            return self._aggressive_update_packages

    @property
    def use_only_tar_bz2(self) -> bool:
        if self._use_only_tar_bz2 is not None:
            return self._use_only_tar_bz2
        try:
            import conda_package_handling.api  # type: ignore[import]

            return not conda_package_handling.api.libarchive_enabled
        except ImportError:
            return False

    @cached_property
    def user_agent(self) -> str:
        """Construct the conda user-agent string."""
        try:
            import conda  # type: ignore[import]

            conda_version = conda.__version__
        except ImportError:
            conda_version = "unknown"
        builder = [f"conda/{conda_version} requests/{self.requests_version}"]
        builder.append("{}/{}".format(*self.python_implementation_name_version))
        builder.append("{}/{}".format(*self.platform_system_release))
        builder.append("{}/{}".format(*self.os_distribution_name_version))
        libc_family, libc_version = self.libc_family_version
        if libc_family:
            builder.append(f"{libc_family}/{libc_version}")
        return " ".join(builder)

    @property
    def conda_build_local_paths(self) -> tuple[str, ...]:
        candidates = [
            self._croot,
            self.bld_path,
            self._conda_build.get("root-dir", ""),
            join(self.root_prefix, "conda-bld"),
            "~/conda-bld",
        ]
        return tuple(_unique(_expand(d) for d in candidates if d and isdir(_expand(d))))

    @property
    def conda_build_local_urls(self) -> tuple[str, ...]:
        try:
            from conda.common.url import path_to_url  # type: ignore[import]

            return tuple(path_to_url(p) for p in self.conda_build_local_paths)
        except ImportError:
            return tuple(f"file://{p}" for p in self.conda_build_local_paths)

    # ------------------------------------------------------------------
    # Tier 2: Filesystem-interrogating computed properties
    # ------------------------------------------------------------------

    @cached_property
    def root_prefix(self) -> str:
        if self._root_prefix:
            return abspath(expanduser(self._root_prefix))
        return self.conda_prefix

    @property
    def conda_prefix(self) -> str:
        return abspath(sys.prefix)

    @property
    def av_data_dir(self) -> str:
        return join(self.conda_prefix, "etc", "conda")

    @property
    def root_writable(self) -> bool:
        path = join(self.root_prefix, PREFIX_MAGIC_FILE)
        if isfile(path):
            try:
                with open(path, "a+"):
                    pass
                return True
            except OSError as e:
                log.debug(e)
                return False
        return False

    @property
    def envs_dirs(self) -> tuple[str, ...]:
        on_win = sys.platform == "win32"
        if self.root_writable:
            fixed_dirs = [
                join(self.root_prefix, "envs"),
                join("~", ".conda", "envs"),
            ]
        else:
            fixed_dirs = [
                join("~", ".conda", "envs"),
                join(self.root_prefix, "envs"),
            ]
        if on_win:
            try:
                from platformdirs import user_data_dir  # type: ignore[import]

                fixed_dirs.append(join(user_data_dir(APP_NAME, APP_NAME), "envs"))
            except ImportError:
                pass
        return tuple(dict.fromkeys(_expand(p) for p in (*self._envs_dirs, *fixed_dirs)))

    @property
    def pkgs_dirs(self) -> tuple[str, ...]:
        on_win = sys.platform == "win32"
        if self._pkgs_dirs:
            return tuple(dict.fromkeys(_expand(p) for p in self._pkgs_dirs))
        cache_dir_name = "pkgs32" if self.force_32bit else "pkgs"
        fixed: list[str] = [self.root_prefix, join("~", ".conda")]
        if on_win:
            try:
                from platformdirs import user_data_dir  # type: ignore[import]

                fixed.append(user_data_dir(APP_NAME, APP_NAME))
            except ImportError:
                pass
        return tuple(dict.fromkeys(_expand(join(p, cache_dir_name)) for p in fixed))

    @property
    def trash_dir(self) -> str:
        """Best-effort: uses first pkgs_dir."""
        pkgs = self.pkgs_dirs
        if pkgs:
            trash = join(pkgs[0], ".trash")
            os.makedirs(trash, exist_ok=True)
            return trash
        trash = join(self.root_prefix, ".trash")
        os.makedirs(trash, exist_ok=True)
        return trash

    @property
    def active_prefix(self) -> str | None:
        return os.getenv("CONDA_PREFIX")

    @property
    def shlvl(self) -> int:
        return int(os.getenv("CONDA_SHLVL", -1))

    @property
    def default_prefix(self) -> str:
        if self.active_prefix:
            return self.active_prefix
        _default_env = os.getenv("CONDA_DEFAULT_ENV")
        if _default_env is None or _default_env == ROOT_ENV_NAME:
            return self.root_prefix
        elif os.sep in _default_env:
            return abspath(_default_env)
        for envs_dir in self.envs_dirs:
            candidate = join(envs_dir, _default_env)
            if isdir(candidate):
                return candidate
        return join(self.envs_dirs[0], _default_env) if self.envs_dirs else self.root_prefix

    @property
    def target_prefix(self) -> str:
        return self.default_prefix

    @property
    def config_files(self) -> tuple[str, ...]:
        """Paths to all condarc files that were successfully loaded."""
        engine = MergeEngine(search_path=self._search_path)
        return tuple(str(p) for p in engine._expand_search_path(self._search_path))

    @property
    def croot(self) -> str:
        if self._croot:
            return abspath(expanduser(self._croot))
        elif self.bld_path:
            return abspath(expanduser(self.bld_path))
        elif "root-dir" in self._conda_build:
            return abspath(expanduser(self._conda_build["root-dir"]))
        elif self.root_writable:
            return join(self.root_prefix, "conda-bld")
        return _expand("~/conda-bld")

    @property
    def local_build_root(self) -> str:
        return self.croot

    # ------------------------------------------------------------------
    # Plugin infrastructure
    # ------------------------------------------------------------------

    @property
    def plugin_manager(self):
        """The conda plugin manager singleton.

        Requires conda to be installed. Raises ImportError otherwise.
        This is the preferred way of accessing the PluginManager object for
        this application and is located here to avoid problems with cyclical
        imports elsewhere in the code.
        """
        try:
            from conda.plugins.manager import get_plugin_manager  # type: ignore[import]

            return get_plugin_manager()
        except ImportError as exc:
            raise ImportError("plugin_manager requires conda to be installed") from exc

    @cached_property
    def plugins(self):
        """Settings introduced by the settings plugin hook.

        Requires conda to be installed. Raises ImportError otherwise.
        Preferred way of accessing plugin-defined settings via the context.
        """
        self.plugin_manager.load_settings()
        # PluginConfig expects raw_data in conda's {source: {key: RawParam}} format.
        # Our flat merged dict is not compatible with that shape.  Pass an empty
        # dict so PluginConfig starts clean; plugin settings from .condarc files
        # are not yet parsed by our MergeEngine.
        return self.plugin_manager.get_config({})

    # ------------------------------------------------------------------
    # Description map and category map helpers
    # ------------------------------------------------------------------

    def get_descriptions(self) -> dict[str, str]:
        """Return the mapping of setting names to their canonical descriptions."""
        return self.description_map

    @cached_property
    def description_map(self) -> dict[str, str]:
        """Canonical human-readable descriptions for all documented settings.

        Descriptions match conda 26.5.3's Context.description_map verbatim,
        and are the authoritative source used by ``get_descriptions()`` and
        any tooling that calls ``conda config --describe``.
        """
        return {
            "add_anaconda_token": (
                "In conjunction with the anaconda command-line client (installed with\n"
                "`conda install anaconda-client`), and following logging into an Anaconda\n"
                "Server API site using `anaconda login`, automatically apply a matching\n"
                "private token to enable access to private packages and channels.\n"
            ),
            "aggressive_update_packages": (
                "A list of packages that, if installed, are always updated to the latest possible\n"
                "version.\n"
            ),
            "allow_non_channel_urls": (
                "Warn, but do not fail, when conda detects a channel url is not a valid channel.\n"
            ),
            "allow_softlinks": (
                "When allow_softlinks is True, conda uses hard-links when possible, and soft-links\n"  # noqa: E501
                "(symlinks) when hard-links are not possible, such as when installing on a\n"
                "different filesystem than the one that the package cache is on. When\n"
                "allow_softlinks is False, conda still uses hard-links when possible, but when it\n"
                "is not possible, conda copies files. Individual packages can override\n"
                "this setting, specifying that certain files should never be soft-linked (see the\n"
                "no_link option in the build recipe documentation).\n"
            ),
            "allowlist_channels": (
                "The exclusive list of channels allowed to be used on the system. Use of any\n"
                "other channels will result in an error. If conda-build channels are to be\n"
                "allowed, along with the --use-local command line flag, be sure to include the\n"
                "'local' channel in the list. If the list is empty or left undefined, no\n"
                "channel exclusions will be enforced.\n"
            ),
            "always_copy": (
                "Register a preference that files be copied into a prefix during install rather\n"
                "than hard-linked.\n"
            ),
            "always_softlink": (
                "Register a preference that files be soft-linked (symlinked) into a prefix during\n"
                "install rather than hard-linked. The link source is the 'pkgs_dir' package cache\n"
                "from where the package is being linked. WARNING: Using this option can result in\n"
                "corruption of long-lived conda environments. Package caches are *caches*, which\n"
                "means there is some churn and invalidation. With this option, the contents of\n"
                "environments can be switched out (or erased) via operations on other environments.\n"  # noqa: E501
            ),
            "always_yes": (
                "Automatically choose the 'yes' option whenever asked to proceed with a conda\n"
                "operation, such as when running `conda install`.\n"
            ),
            "anaconda_upload": (
                "Automatically upload packages built with conda build to anaconda.org.\n"
            ),
            "auto_activate": (
                "Automatically activate the environment given at 'default_activation_env'\n"
                "during shell initialization.\n"
            ),
            "auto_stack": (
                "Implicitly use --stack when using activate if current level of nesting\n"
                "(as indicated by CONDA_SHLVL environment variable) is less than or equal to\n"
                "specified value. 0 or false disables automatic stacking, 1 or true enables\n"
                "it for one level.\n"
            ),
            "auto_update_conda": (
                "Automatically update conda when a newer or higher priority version is detected.\n"
            ),
            "bld_path": (
                "The location where conda-build will put built packages. Same as 'croot', but\n"
                "'croot' takes precedence when both are defined. Also used in construction of the\n"
                "'local' multichannel.\n"
            ),
            "changeps1": (
                "When using activate, change the command prompt ($PS1) to include the\n"
                "activated environment.\n"
            ),
            "channel_alias": ("The prepended url location to associate with channel names.\n"),
            "channel_priority": (
                "Accepts values of 'strict', 'flexible', and 'disabled'. The default value\n"
                "is 'flexible'. With strict channel priority, packages in lower priority channels\n"
                "are not considered if a package with the same name appears in a higher\n"
                "priority channel. With flexible channel priority, the solver may reach into\n"
                "lower priority channels to fulfill dependencies, rather than raising an\n"
                "unsatisfiable error. With channel priority disabled, package version takes\n"
                "precedence, and the configured priority of channels is used only to break ties.\n"
                "In previous versions of conda, this parameter was configured as either True or\n"
                "False. True is now an alias to 'flexible'.\n"
            ),
            "channel_settings": (
                "A list of mappings that allows overriding certain settings for a single channel.\n"
                'Each list item should include at least the "channel" key and the setting you would\n'  # noqa: E501
                "like to override.\n"
            ),
            "channels": ("The list of conda channels to include for relevant operations.\n"),
            "client_ssl_cert": (
                "A path to a single file containing a private key and certificate (e.g. .pem\n"
                "file). Alternately, use client_ssl_cert_key in conjunction with client_ssl_cert\n"
                "for individual files.\n"
            ),
            "client_ssl_cert_key": (
                "Used in conjunction with client_ssl_cert for a matching key file.\n"
            ),
            "conda_build": ("General configuration parameters for conda-build.\n"),
            "console": (
                "Configure different backends to be used while rendering normal console output.\n"
                'Defaults to "classic".\n'
            ),
            "create_default_packages": (
                "Packages that are by default added to a newly created environments.\n"
            ),
            "croot": (
                "The location where conda-build will put built packages. Same as 'bld_path', but\n"
                "'croot' takes precedence when both are defined. Also used in construction of the\n"
                "'local' multichannel.\n"
            ),
            "custom_channels": (
                "A map of key-value pairs where the key is a channel name and the value is\n"
                "a channel location. Channels defined here override the default\n"
                "'channel_alias' value. The channel name (key) is not included in the channel\n"
                "location (value).  For example, to override the location of the 'conda-forge'\n"
                "channel where the url to repodata is\n"
                "https://anaconda-repo.dev/packages/conda-forge/linux-64/repodata.json, add an\n"
                "entry 'conda-forge: https://anaconda-repo.dev/packages'.\n"
            ),
            "custom_multichannels": (
                "A multichannel is a metachannel composed of multiple channels. The only reserved\n"
                "multichannel is 'local', which is a list of file:// channel locations where\n"
                "conda-build stashes successfully-built packages and cannot be overridden.\n"
                "Other multichannels, including 'defaults', can be defined or customized with\n"
                "custom_multichannels, where the key is the multichannel name and the value is\n"
                "a list of channel names and/or channel urls. The 'defaults' multichannel can\n"
                "also be customized using the 'default_channels' parameter (a historical setting\n"
                "from when 'defaults' was reserved). If both are defined,\n"
                "'custom_multichannels.defaults' takes precedence.\n"
            ),
            "default_activation_env": (
                "The environment to be automatically activated on startup if 'auto_activate'\n"
                "is True. Also sets the default environment to activate when 'conda activate'\n"
                "receives no arguments.\n"
            ),
            "default_channels": (
                "The list of channel names and/or urls used for the 'defaults' multichannel.\n"
                "Can be overridden by 'custom_multichannels.defaults'.\n"
            ),
            "default_threads": (
                "Threads to use by default for parallel operations.  Default is None,\n"
                "which allows operations to choose themselves.  For more specific\n"
                "control, see the other *_threads parameters:\n"
                "    * repodata_threads - for fetching/loading repodata\n"
                "    * verify_threads - for verifying package contents in transactions\n"
                "    * execute_threads - for carrying out the unlinking and linking steps\n"
            ),
            "denylist_channels": (
                "The list of channels that are denied to be used on the system. Use of any\n"
                "of these channels will result in an error. If conda-build channels are to be\n"
                "allowed, along with the --use-local command line flag, be sure to not include\n"
                "the 'local' channel in the list. If the list is empty or left undefined, no\n"
                "channel exclusions will be enforced.\n"
            ),
            "disallowed_packages": (
                "Package specifications to disallow installing. The default is to allow\n"
                "all packages.\n"
            ),
            "download_only": (
                "Solve an environment and ensure package caches are populated, but exit\n"
                "prior to unlinking and linking packages into the prefix\n"
            ),
            "env_prompt": (
                "Template for prompt modification based on the active environment. Currently\n"
                "supported template variables are '{prefix}', '{name}', and '{default_env}'.\n"
                "'{prefix}' is the absolute path to the active environment. '{name}' is the\n"
                "basename of the active environment prefix. '{default_env}' holds the value\n"
                "of '{name}' if the active environment is a conda named environment ('-n'\n"
                "flag), or otherwise holds the value of '{prefix}'. Templating uses python's\n"
                "str.format() method.\n"
            ),
            "environment_specifier": (
                "**EXPERIMENTAL** While experimental, expect both major and minor changes across minor releases.\n"  # noqa: E501
                "\n"
                "The name of the environment specifier plugin that should be used for this context.\n"  # noqa: E501
                "If not specified, the plugin manager will try to detect the plugin to use.\n"
            ),
            "envs_dirs": (
                "The list of directories to search for named environments. When creating a new\n"
                "named environment, the environment will be placed in the first writable\n"
                "location.\n"
            ),
            "envvars_force_uppercase": (
                "Force uppercase for new environment variable names. Defaults to True.\n"
            ),
            "execute_threads": (
                "Threads to use when performing the unlink/link transaction.  When not set,\n"
                "defaults to 1.  This step is pretty strongly I/O limited, and you may not\n"
                "see much benefit here.\n"
            ),
            "experimental": ("List of experimental features to enable.\n"),
            "export_platforms": (
                "Additional platform(s)/subdir(s) for export (e.g., linux-64, osx-64, win-64), current\n"  # noqa: E501
                "platform is always included.\n"
            ),
            "extra_safety_checks": (
                "Spend extra time validating package contents.  Currently, runs sha256 verification\n"  # noqa: E501
                "on every file within each package during installation.\n"
            ),
            "fetch_threads": (
                "Threads to use when downloading packages.  When not set,\n"
                "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
            ),
            "force_reinstall": (
                "Ensure that any user-requested package for the current operation is uninstalled\n"
                "and reinstalled, even if that package already exists in the environment.\n"
            ),
            "json": ("Ensure all output written to stdout is structured json.\n"),
            "list_fields": ("Default fields to report as columns in the output of `conda list`.\n"),
            "local_repodata_ttl": (
                "For a value of False or 0, always fetch remote repodata (HTTP 304 responses\n"
                "respected). For a value of True or 1, respect the HTTP Cache-Control max-age\n"
                "header. Any other positive integer values is the number of seconds to locally\n"
                "cache repodata before checking the remote server for an update.\n"
            ),
            "migrated_channel_aliases": (
                "A list of previously-used channel_alias values. Useful when switching between\n"
                "different Anaconda Repository instances.\n"
            ),
            "migrated_custom_channels": (
                "A map of key-value pairs where the key is a channel name and the value is\n"
                "the previous location of the channel.\n"
            ),
            "no_lock": ("Disable index cache lock (defaults to enabled).\n"),
            "no_plugins": (
                "Disable all currently-registered plugins, except built-in conda plugins.\n"
            ),
            "non_admin_enabled": (
                "Allows completion of conda's create, install, update, and remove operations, for\n"
                "non-privileged (non-root or non-administrator) users.\n"
            ),
            "notify_outdated_conda": (
                "Notify if a newer version of conda is detected during a create, install, update,\n"
                "or remove operation.\n"
            ),
            "number_channel_notices": (
                "Sets the number of channel notices to be displayed when running commands\n"
                'the "install", "create", "update", "env create", and "env update" . Defaults\n'
                "to 5. In order to completely suppress channel notices, set this to 0.\n"
            ),
            "offline": ("Restrict conda to cached download content and file:// based urls.\n"),
            "override_channels_enabled": (
                "Permit use of the --override-channels command-line flag.\n"
            ),
            "override_virtual_packages": ("Set override values for virtual packages.\n"),
            "path_conflict": (
                "The method by which conda handle's conflicting/overlapping paths during a\n"
                "create, install, or update operation. The value must be one of 'clobber',\n"
                "'warn', or 'prevent'. The '--clobber' command-line flag or clobber\n"
                "configuration parameter overrides path_conflict set to 'prevent'.\n"
            ),
            "pinned_packages": (
                "A list of package specs to pin for every environment resolution.\n"
                "This parameter is in BETA, and its behavior may change in a future release.\n"
            ),
            "pkgs_dirs": (
                "The list of directories where locally-available packages are linked from at\n"
                "install time. Packages not locally available are downloaded and extracted\n"
                "into the first writable directory.\n"
            ),
            "prefix_data_interoperability": (
                "Enable plugins to allow conda to interact with non-conda-installed packages.\n"
            ),
            "preview": ("List of preview features to opt into.\n"),
            "proxy_servers": (
                "A mapping to enable proxy settings. Keys can be either (1) a scheme://hostname\n"
                "form, which will match any request to the given scheme and exact hostname, or\n"
                "(2) just a scheme, which will match requests to that scheme. Values are are\n"
                "the actual proxy server, and are of the form\n"
                "'scheme://[user:password@]host[:port]'. The optional 'user:password' inclusion\n"
                "enables HTTP Basic Auth with your proxy.\n"
            ),
            "quiet": ("Disable progress bar display and other output.\n"),
            "remote_backoff_factor": (
                "The factor determines the time HTTP connection should wait for attempt.\n"
            ),
            "remote_connect_timeout_secs": (
                "The number seconds conda will wait for your client to establish a connection\n"
                "to a remote url resource.\n"
            ),
            "remote_max_retries": (
                "The maximum number of retries each HTTP connection should attempt.\n"
            ),
            "remote_read_timeout_secs": (
                "Once conda has connected to a remote resource and sent an HTTP request, the\n"
                "read timeout is the number of seconds conda will wait for the server to send\n"
                "a response.\n"
            ),
            "repodata_fns": (
                "Specify filenames for repodata fetching. The default is ('current_repodata.json',\n"  # noqa: E501
                "'repodata.json'), which tries a subset of the full index containing only the\n"
                "latest version for each package, then falls back to repodata.json.  You may\n"
                "want to specify something else to use an alternate index that has been reduced\n"
                "somehow.\n"
            ),
            "repodata_threads": (
                "Threads to use when downloading and reading repodata.  When not set,\n"
                "defaults to None, which uses the default ThreadPoolExecutor behavior.\n"
            ),
            "repodata_use_shards": ("Use sharded repodata if available.\n"),
            "repodata_use_zst": ("Use `repodata.json.zst` if available.\n"),
            "report_errors": (
                "Opt in, or opt out, of automatic error reporting to core maintainers. Error\n"
                "reports are anonymous, with only the error stack trace and information given\n"
                "by `conda info` being sent.\n"
            ),
            "rollback_enabled": (
                "Should any error occur during an unlink/link transaction, revert any disk\n"
                "mutations made to that point in the transaction.\n"
            ),
            "safety_checks": (
                "Enforce available safety guarantees during package installation.\n"
                "The value must be one of 'enabled', 'warn', or 'disabled'.\n"
            ),
            "separate_format_cache": (
                "Treat .tar.bz2 files as different from .conda packages when\n"
                "filenames are otherwise similar. This defaults to False, so\n"
                "that your package cache doesn't churn when rolling out the new\n"
                "package format. If you'd rather not assume that a .tar.bz2 and\n"
                ".conda from the same place represent the same content, set this\n"
                "to True.\n"
            ),
            "shortcuts": (
                "Allow packages to create OS-specific shortcuts (e.g. in the Windows Start\n"
                "Menu) at install time.\n"
            ),
            "shortcuts_only": ("Create shortcuts only for the specified package names.\n"),
            "show_channel_urls": (
                "Show channel URLs when displaying what is going to be downloaded.\n"
            ),
            "signing_metadata_url_base": (
                "Base URL for obtaining trust metadata updates (i.e., the `*.root.json` and\n"
                "`key_mgr.json` files) used to verify metadata and (eventually) package signatures.\n"  # noqa: E501
            ),
            "solver": (
                "A string to choose between the different solver logics implemented in\n"
                "conda. A solver logic takes care of turning your requested packages into a\n"
                "list of specs to add and/or remove from a given environment, based on their\n"
                "dependencies and specified constraints.\n"
            ),
            "ssl_verify": (
                "Conda verifies SSL certificates for HTTPS requests, just like a web\n"
                "browser. By default, SSL verification is enabled, and conda operations will\n"
                "fail if a required url's certificate cannot be verified. Setting ssl_verify to\n"
                "False disables certification verification. The value for ssl_verify can also\n"
                "be (1) a path to a CA bundle file, (2) a path to a directory containing\n"
                "certificates of trusted CA, or (3) 'truststore' to use the\n"
                "operating system certificate store.\n"
            ),
            "track_features": (
                "A list of features that are tracked by default. An entry here is similar to\n"
                "adding an entry to the create_default_packages list.\n"
            ),
            "unsatisfiable_hints": (
                "A boolean to determine if conda should find conflicting packages in the case\n"
                "of a failed install.\n"
            ),
            "unsatisfiable_hints_check_depth": (
                "An integer that specifies how many levels deep to search for unsatisfiable\n"
                "dependencies. If this number is 1 it will complete the unsatisfiable hints\n"
                "fastest (but perhaps not the most complete). The higher this number, the\n"
                "longer the generation of the unsat hint will take. Defaults to 3.\n"
            ),
            "use_index_cache": ("Use cache of channel index files, even if it has expired.\n"),
            "use_only_tar_bz2": (
                "A boolean indicating that only .tar.bz2 conda packages should be downloaded.\n"
                "This is forced to True if conda-build is installed and older than 3.18.3,\n"
                "because older versions of conda break when conda feeds it the new file format.\n"
            ),
            "verbosity": ("Sets output log level. 0 is warn. 1 is info. 2 is debug. 3 is trace.\n"),
            "verify_threads": (
                "Threads to use when performing the transaction verification step.  When not set,\n"
                "defaults to 1.\n"
            ),
        }

    # ------------------------------------------------------------------
    # Memoized system information properties (used by user_agent and
    # available externally, matching conda's Context API)
    # ------------------------------------------------------------------

    @cached_property
    def python_implementation_name_version(self) -> tuple[str, str]:
        """Return (python_implementation, python_version), e.g. ('CPython', '3.12.0')."""
        return platform.python_implementation(), platform.python_version()

    @cached_property
    def platform_system_release(self) -> tuple[str, str]:
        """Return (system_name, release_version), e.g. ('Linux', '5.15.0')."""
        return platform.system(), platform.release()

    @cached_property
    def os_distribution_name_version(self) -> tuple[str, str]:
        """Return (distro_name, version), e.g. ('debian', '11') or ('OSX', '13.0')."""
        system = self.platform_system_release[0]
        if system == "Linux":
            try:
                import distro  # type: ignore[import]

                return distro.id(), distro.version()
            except ImportError:
                pass
            return "Linux", self.platform_system_release[1]
        elif system == "Darwin":
            return "OSX", platform.mac_ver()[0]
        elif system == "Windows":
            return "Windows", platform.version()
        return system, self.platform_system_release[1]

    @cached_property
    def libc_family_version(self) -> tuple[str | None, str | None]:
        """Return (libc_family, libc_version) on Linux, or (None, None) on other OSes."""
        if self.platform_system_release[0] == "Linux":
            try:
                from conda.common._os.linux import linux_get_libc_version  # type: ignore[import]

                return linux_get_libc_version()
            except ImportError:
                pass
            # Fallback: try to detect glibc via ctypes
            try:
                import ctypes

                libc = ctypes.CDLL("libc.so.6")
                gnu_get_libc_version = libc.gnu_get_libc_version
                gnu_get_libc_version.restype = ctypes.c_char_p
                version = gnu_get_libc_version().decode()
                return "glibc", version
            except Exception:
                pass
        return None, None

    @cached_property
    def requests_version(self) -> str:
        """Return the installed requests library version string, or 'unknown'."""
        try:
            from requests import __version__ as _requests_version  # type: ignore[import]

            return _requests_version
        except ImportError:
            return "unknown"

    # ------------------------------------------------------------------
    # Environment and prefix helpers
    # ------------------------------------------------------------------

    @property
    def prefix_specified(self) -> bool:
        """Return True if --prefix or --name was given on the command line."""
        argparse_args = self._argparse_args or {}
        return argparse_args.get("prefix") is not None or argparse_args.get("name") is not None

    def preview_enabled(self, value: str) -> bool:
        """Return True if the given preview feature label is enabled by the user."""
        return value in self.preview

    @property
    def environment_context_keys(self) -> list[str]:
        """List of setting names that are environment-specific."""
        return [
            "aggressive_update_packages",
            "channel_priority",
            "channels",
            "channel_settings",
            "custom_channels",
            "custom_multichannels",
            "deps_modifier",
            "disallowed_packages",
            "pinned_packages",
            "repodata_fns",
            "sat_solver",
            "solver",
            "track_features",
            "update_modifier",
            "use_only_tar_bz2",
        ]

    @property
    def environment_settings(self) -> dict[str, Any]:
        """Return a dict of environment-related settings."""
        return {key: getattr(self, key) for key in self.environment_context_keys}

    @property
    def error_upload_url(self) -> str:
        """URL for uploading unexpected error reports.

        .. deprecated:: 26.9
            This property is deprecated and will be removed in conda 27.3.
            Use ``_error_upload_url`` directly if needed.
        """
        return self._error_upload_url

    @property
    def report_errors(self) -> bool | None:
        """Whether to automatically report errors.

        .. deprecated:: 26.9
            This property is deprecated and will be removed in conda 27.3.
            Use ``_report_errors`` directly if needed.
        """
        return self._report_errors

    # ------------------------------------------------------------------
    # Solver user-agent helper
    # ------------------------------------------------------------------

    def solver_user_agent(self) -> str:
        """Build the solver fragment of the User-Agent header string."""
        user_agent = f"solver/{self.solver}"
        try:
            solver_backend = self.plugin_manager.get_cached_solver_backend()
            user_agent += f" {solver_backend.user_agent()}"
        except Exception as exc:
            log.debug(
                "User agent could not be fetched from solver class '%s'.",
                self.solver,
                exc_info=exc,
            )
        return user_agent

    # ------------------------------------------------------------------
    # conda executable environment variables
    # ------------------------------------------------------------------

    @property
    def conda_exe_vars_dict(self) -> dict[str, str | None]:
        """Dict of env vars used to delegate to the conda executable.

        Requires conda to be installed. Falls back to a minimal dict otherwise.
        """
        try:
            from conda.base.constants import BIN_DIRECTORY  # type: ignore[import]
            from conda.common.path import on_win  # type: ignore[import]
        except ImportError:
            import os as _os

            bin_dir = "Scripts" if sys.platform == "win32" else "bin"
            exe_name = "conda.exe" if sys.platform == "win32" else "conda"
            exe = _os.path.join(self.conda_prefix, bin_dir, exe_name)
            return {
                "CONDA_EXE": exe,
                "_CONDA_EXE": exe,
                "_CE_M": None,
                "_CE_CONDA": None,
                "CONDA_PYTHON_EXE": sys.executable,
                "_CONDA_ROOT": self.conda_prefix,
            }

        if self.dev:
            try:
                from conda.base.constants import CONDA_SOURCE_ROOT  # type: ignore[import]
            except ImportError:
                CONDA_SOURCE_ROOT = self.conda_prefix
            if pythonpath := os.environ.get("PYTHONPATH", ""):
                pythonpath = os.pathsep.join((CONDA_SOURCE_ROOT, pythonpath))
            else:
                pythonpath = CONDA_SOURCE_ROOT
            return {
                "CONDA_EXE": sys.executable,
                "_CONDA_EXE": sys.executable,
                "PYTHONPATH": pythonpath,
                "_CE_M": "-m",
                "_CE_CONDA": "conda",
                "CONDA_PYTHON_EXE": sys.executable,
                "_CONDA_ROOT": self.conda_prefix,
            }
        else:
            exe = os.path.join(
                self.conda_prefix,
                BIN_DIRECTORY,
                "conda.exe" if on_win else "conda",
            )
            return {
                "CONDA_EXE": exe,
                "_CONDA_EXE": exe,
                "_CE_M": None,
                "_CE_CONDA": None,
                "CONDA_PYTHON_EXE": sys.executable,
                "_CONDA_ROOT": self.conda_prefix,
            }

    # ------------------------------------------------------------------
    # post_build_validation (API compat)
    # ------------------------------------------------------------------

    def post_build_validation(self) -> list[Any]:
        """Return validation errors list (API compatibility with conda's Configuration)."""
        errors = []
        if self.client_ssl_cert_key and not self.client_ssl_cert:
            errors.append({"field": "client_ssl_cert", "message": "'client_ssl_cert' is required"})
        if self.always_copy and self.always_softlink:
            errors.append(
                {
                    "field": "always_copy",
                    "message": "'always_copy' and 'always_softlink' are mutually exclusive.",
                }
            )
        return errors

    def __repr__(self) -> str:
        return f"Context(search_path={self._search_path!r})"


# ---------------------------------------------------------------------------
# Module-level singleton and mutation protocol
# ---------------------------------------------------------------------------


class _ContextStack:
    """Manages a stack of (search_path, argparse_args) for test isolation."""

    def __init__(self) -> None:
        self._stack: list[tuple[tuple, Namespace | None]] = []

    def push(
        self,
        search_path: tuple,
        argparse_args: Namespace | None,
    ) -> None:
        self._stack.append((context._search_path, Namespace(**context._argparse_args)))
        context._set_search_path(search_path)
        context._set_argparse_args(argparse_args)

    def pop(self) -> None:
        if self._stack:
            saved_path, saved_args = self._stack.pop()
            context._set_search_path(saved_path)
            context._set_argparse_args(saved_args)

    def replace(
        self,
        search_path: tuple,
        argparse_args: Namespace | None,
    ) -> None:
        context._set_search_path(search_path)
        context._set_argparse_args(argparse_args)

    def apply(self) -> None:
        pass


context_stack = _ContextStack()

try:
    context = Context((), None)
except CondaConfigError as e:
    import sys as _sys

    print(str(e), file=_sys.stderr)
    _sys.exit(1)


def reset_context(
    search_path: tuple | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    """Reset the global context singleton."""
    context._set_search_path(_DEFAULT_SEARCH_PATH if search_path is None else search_path)
    context._set_argparse_args(argparse_args)


@contextmanager
def stack_context(
    search_path: tuple,
    argparse_args: Namespace | None = None,
) -> Iterator[None]:
    """Temporarily push a new context onto the stack."""
    context_stack.push(search_path, argparse_args)
    try:
        yield
    finally:
        context_stack.pop()


@contextmanager
def fresh_context(argparse_args: Namespace | None = None) -> Iterator[None]:
    """Temporarily replace context with empty search path (all defaults)."""
    context_stack.push((), argparse_args)
    try:
        yield
    finally:
        context_stack.pop()


def replace_context(
    pushing: bool | None = None,
    search_path: tuple | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.replace(
        search_path=search_path or (),
        argparse_args=argparse_args,
    )


def stack_context_default(
    pushing: bool | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.push(_DEFAULT_SEARCH_PATH, argparse_args)


def replace_context_default(
    pushing: bool | None = None,
    argparse_args: Namespace | None = None,
) -> None:
    context_stack.replace(search_path=(), argparse_args=argparse_args)


# Alias for conda's test policy
conda_tests_ctxt_mgmt_def_pol = replace_context_default
