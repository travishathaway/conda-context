"""
MergeEngine — resolves conda's layered configuration sources into a single
merged dict and a ProvenanceMap.

Priority order (lowest → highest):
  1. System condarc files (from search path)
  2. User condarc (~/.condarc)
  3. Environment-level condarc ($CONDA_PREFIX/.condarc)
  4. CONDA_* environment variables
  5. argparse CLI arguments

Merge semantics:
  - Primitive: last (highest-priority) source wins.
  - Sequence: higher-priority source prepended before lower-priority items
              (unless a ``ParameterFlag.append`` marker is present).
  - Map: deep merge; higher-priority keys win on collision.
"""

from __future__ import annotations

import logging
import os
import stat
from argparse import Namespace
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .constants import APP_NAME, CONDARC_FILENAMES, YAML_EXTENSIONS
from .provenance import ProvenanceInfo, ProvenanceMap

log = logging.getLogger(__name__)

# Sentinel used by conda for append/prepend flags in YAML sequences.
# e.g.  channels:
#         - defaults      # noqa: yaml-sequence-flag
# We detect the special strings conda uses in its raw parameter system.
_PREPEND_MARKER = "prepend"
_APPEND_MARKER = "append"

# Map CONDA_* env var names → config field names.
# Built from the known mapping in conda 26.5.3.
_ENV_VAR_MAP: dict[str, str] = {
    "CONDA_ADD_PIP_AS_PYTHON_DEPENDENCY": "add_pip_as_python_dependency",
    "CONDA_ALLOW_CONDA_DOWNGRADES": "allow_conda_downgrades",
    "CONDA_ALLOW_CYCLES": "allow_cycles",
    "CONDA_ALLOW_SOFTLINKS": "allow_softlinks",
    "CONDA_ALLOW_NON_CHANNEL_URLS": "allow_non_channel_urls",
    "CONDA_ALWAYS_COPY": "always_copy",
    "CONDA_ALWAYS_SOFTLINK": "always_softlink",
    "CONDA_ALWAYS_YES": "always_yes",
    "CONDA_ANACONDA_UPLOAD": "anaconda_upload",
    "CONDA_AUTO_ACTIVATE": "auto_activate",
    "CONDA_AUTO_ACTIVATE_BASE": "auto_activate",
    "CONDA_AUTO_STACK": "auto_stack",
    "CONDA_AUTO_UPDATE_CONDA": "auto_update_conda",
    "CONDA_BLD_PATH": "bld_path",
    "CONDA_CHANNEL_ALIAS": "channel_alias",
    "CONDA_CHANNEL_PRIORITY": "channel_priority",
    "CONDA_CHANNELS": "channels",
    "CONDA_CHANGEPS1": "changeps1",
    "CONDA_CLIENT_SSL_CERT": "client_ssl_cert",
    "CONDA_CLIENT_SSL_CERT_KEY": "client_ssl_cert_key",
    "CONDA_CLOBBER": "clobber",
    "CONDA_DEFAULT_CHANNELS": "default_channels",
    "CONDA_DEFAULT_PYTHON": "default_python",
    "CONDA_DEFAULT_THREADS": "default_threads",
    "CONDA_DEPS_MODIFIER": "deps_modifier",
    "CONDA_DEV": "dev",
    "CONDA_DISALLOWED_PACKAGES": "disallowed_packages",
    "CONDA_DOWNLOAD_ONLY": "download_only",
    "CONDA_DRY_RUN": "dry_run",
    "CONDA_ENABLE_PRIVATE_ENVS": "enable_private_envs",
    "CONDA_ENVS_DIRS": "envs_dirs",
    "CONDA_ENVS_PATH": "envs_dirs",
    "CONDA_ENV_PROMPT": "env_prompt",
    "CONDA_ENVVARS_FORCE_UPPERCASE": "envvars_force_uppercase",
    "CONDA_EXECUTE_THREADS": "execute_threads",
    "CONDA_EXPERIMENTAL": "experimental",
    "CONDA_EXTRA_SAFETY_CHECKS": "extra_safety_checks",
    "CONDA_FETCH_THREADS": "fetch_threads",
    "CONDA_FORCE": "force",
    "CONDA_FORCE_32BIT": "force_32bit",
    "CONDA_FORCE_REMOVE": "force_remove",
    "CONDA_FORCE_REINSTALL": "force_reinstall",
    "CONDA_IGNORE_PINNED": "ignore_pinned",
    "CONDA_JSON": "json",
    "CONDA_LOCAL_REPODATA_TTL": "local_repodata_ttl",
    "CONDA_NON_ADMIN_ENABLED": "non_admin_enabled",
    "CONDA_NOTIFY_OUTDATED_CONDA": "notify_outdated_conda",
    "CONDA_NO_LOCK": "no_lock",
    "CONDA_NO_PLUGINS": "no_plugins",
    "CONDA_OFFLINE": "offline",
    "CONDA_OVERRIDE_CHANNELS_ENABLED": "override_channels_enabled",
    "CONDA_PATH_CONFLICT": "path_conflict",
    "CONDA_PINNED_PACKAGES": "pinned_packages",
    "CONDA_PKGS_DIRS": "pkgs_dirs",
    "CONDA_PREFIX_DATA_INTEROPERABILITY": "prefix_data_interoperability",
    "CONDA_PREVIEW": "preview",
    "CONDA_PROTECT_FROZEN_ENVS": "protect_frozen_envs",
    "CONDA_QUIET": "quiet",
    "CONDA_REGISTER_ENVS": "register_envs",
    "CONDA_REMOTE_BACKOFF_FACTOR": "remote_backoff_factor",
    "CONDA_REMOTE_CONNECT_TIMEOUT_SECS": "remote_connect_timeout_secs",
    "CONDA_REMOTE_MAX_RETRIES": "remote_max_retries",
    "CONDA_REMOTE_READ_TIMEOUT_SECS": "remote_read_timeout_secs",
    "CONDA_REPODATA_FNS": "repodata_fns",
    "CONDA_REPODATA_THREADS": "repodata_threads",
    "CONDA_REPODATA_USE_ZST": "repodata_use_zst",
    "CONDA_REPODATA_USE_SHARDS": "repodata_use_shards",
    "CONDA_REPORT_ERRORS": "report_errors",
    "CONDA_ROLLBACK_ENABLED": "rollback_enabled",
    "CONDA_ROOT_PREFIX": "root_prefix",
    "CONDA_SAFETY_CHECKS": "safety_checks",
    "CONDA_SAT_SOLVER": "sat_solver",
    "CONDA_SELF_UPDATE": "auto_update_conda",
    "CONDA_SEPARATE_FORMAT_CACHE": "separate_format_cache",
    "CONDA_SHOW_CHANNEL_URLS": "show_channel_urls",
    "CONDA_SHORTCUTS": "shortcuts",
    "CONDA_SIGNING_METADATA_URL_BASE": "signing_metadata_url_base",
    "CONDA_SOLVER": "solver",
    "CONDA_SOLVER_IGNORE_TIMESTAMPS": "solver_ignore_timestamps",
    "CONDA_SSL_VERIFY": "ssl_verify",
    "CONDA_SUBDIR": "subdir",
    "CONDA_SUBDIRS": "subdirs",
    "CONDA_TARGET_PREFIX_OVERRIDE": "target_prefix_override",
    "CONDA_TRACK_FEATURES": "track_features",
    "CONDA_UNSATISFIABLE_HINTS": "unsatisfiable_hints",
    "CONDA_UNSATISFIABLE_HINTS_CHECK_DEPTH": "unsatisfiable_hints_check_depth",
    "CONDA_UPDATE_MODIFIER": "update_modifier",
    "CONDA_USE_INDEX_CACHE": "use_index_cache",
    "CONDA_USE_LOCAL": "use_local",
    "CONDA_USE_ONLY_TAR_BZ2": "use_only_tar_bz2",
    "CONDA_VERBOSITY": "verbosity",
    "CONDA_VERIFY_SSL": "ssl_verify",
    "CONDA_VERIFY_THREADS": "verify_threads",
}

# Fields that are sequences (for env var splitting)
_SEQUENCE_FIELDS = {
    "aggressive_update_packages",
    "allowlist_channels",
    "channels",
    "create_default_packages",
    "default_channels",
    "denylist_channels",
    "disallowed_packages",
    "envs_dirs",
    "experimental",
    "export_platforms",
    "list_fields",
    "migrated_channel_aliases",
    "pinned_packages",
    "pkgs_dirs",
    "preview",
    "repodata_fns",
    "shortcuts_only",
    "subdirs",
    "track_features",
}

# Boolean-like env var coercion
_TRUE_VALUES = frozenset(("1", "true", "yes", "on"))
_FALSE_VALUES = frozenset(("0", "false", "no", "off"))

# Fields that are known booleans (to coerce env var strings)
_BOOL_FIELDS_SET = {
    "add_pip_as_python_dependency",
    "allow_conda_downgrades",
    "allow_cycles",
    "allow_softlinks",
    "allow_non_channel_urls",
    "always_copy",
    "always_softlink",
    "auto_activate",
    "auto_update_conda",
    "changeps1",
    "clobber",
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
    "no_plugins",
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

# Fields that are optional booleans (None | bool)
_OPT_BOOL_FIELDS = {
    "always_yes",
    "anaconda_upload",
    "report_errors",
    "show_channel_urls",
    "use_only_tar_bz2",
}


def _coerce_env_var(field_name: str, raw: str) -> Any:
    """Coerce a raw env-var string to the appropriate Python type."""
    lower = raw.strip().lower()
    if field_name in _BOOL_FIELDS_SET:
        if lower in _TRUE_VALUES:
            return True
        if lower in _FALSE_VALUES:
            return False
        return raw  # let Pydantic validate and produce a nice error
    if field_name in _OPT_BOOL_FIELDS:
        if lower in _TRUE_VALUES:
            return True
        if lower in _FALSE_VALUES:
            return False
        return None if lower in ("none", "null", "") else raw
    if field_name in _SEQUENCE_FIELDS:
        # Sequences are colon-separated or comma-separated
        sep = os.pathsep if field_name in ("envs_dirs", "pkgs_dirs") else ","
        return [v.strip() for v in raw.split(sep) if v.strip()]
    # Numbers
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


class MergeEngine:
    """Resolves conda's layered configuration into a merged dict + ProvenanceMap.

    Usage::

        engine = MergeEngine(search_path=[...], argparse_args=args)
        merged, provenance = engine.resolve()
    """

    def __init__(
        self,
        search_path: tuple[str | Path, ...] | None = None,
        argparse_args: Namespace | None = None,
        environ: dict[str, str] | None = None,
        app_name: str = APP_NAME,
    ) -> None:
        self._search_path = search_path or ()
        self._argparse_args = argparse_args
        self._environ = environ if environ is not None else dict(os.environ)
        self._app_name = app_name
        self._yaml = YAML()
        self._yaml.preserve_quotes = True

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def resolve(self) -> tuple[dict[str, Any], ProvenanceMap]:
        """Return ``(merged_dict, provenance_map)``."""
        merged: dict[str, Any] = {}
        provenance: ProvenanceMap = {}

        # Layer 1–3: YAML files in search path (ascending priority)
        for path in self._expand_search_path(self._search_path):
            file_data, file_prov = self._load_yaml_file(path)
            self._merge_layer(merged, provenance, file_data, file_prov)

        # Layer 4: CONDA_* environment variables
        env_data, env_prov = self._load_env_vars()
        self._merge_layer(merged, provenance, env_data, env_prov)

        # Layer 5: argparse args
        if self._argparse_args is not None:
            arg_data, arg_prov = self._load_argparse(self._argparse_args)
            self._merge_layer(merged, provenance, arg_data, arg_prov)

        return merged, provenance

    # ------------------------------------------------------------------
    # Search path expansion
    # ------------------------------------------------------------------

    def _expand_search_path(
        self, search_path: tuple[str | Path, ...]
    ) -> list[Path]:
        """Expand search path entries, yielding concrete YAML file paths."""
        result: list[Path] = []
        seen: set[Path] = set()

        for entry in search_path:
            path = Path(entry).expanduser()
            try:
                mode = path.stat().st_mode
            except OSError:
                continue

            if stat.S_ISREG(mode):
                # Accept: exact condarc filenames, .yml/.yaml extensions, or .condarc extension
                _condarc_exts = (*YAML_EXTENSIONS, ".condarc")
                if (
                    path.name in CONDARC_FILENAMES
                    or path.suffix in _condarc_exts
                ):
                    if path not in seen:
                        seen.add(path)
                        result.append(path)
            elif stat.S_ISDIR(mode):
                try:
                    entries = sorted(path.iterdir(), key=lambda e: e.name)
                except OSError:
                    continue
                for child in entries:
                    if child.is_file() and (
                        child.name in CONDARC_FILENAMES or child.suffix in (*YAML_EXTENSIONS, ".condarc")
                    ):
                        if child not in seen:
                            seen.add(child)
                            result.append(child)

        return result

    # ------------------------------------------------------------------
    # YAML file loading
    # ------------------------------------------------------------------

    def _load_yaml_file(
        self, path: Path
    ) -> tuple[dict[str, Any], dict[str, ProvenanceInfo]]:
        """Load a YAML file, returning (data_dict, provenance_dict)."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = self._yaml.load(fh)
        except Exception as exc:
            log.warning("Ignoring configuration file (%s) due to error: %s", path, exc)
            return {}, {}

        if not isinstance(raw, (dict, CommentedMap)):
            return {}, {}

        data: dict[str, Any] = {}
        prov: dict[str, ProvenanceInfo] = {}

        for key, value in raw.items():
            field_name = str(key)
            # ruamel.yaml stores line numbers in CommentedMap column_attribs
            line: int | None = None
            if hasattr(raw, "lc"):
                try:
                    line = raw.lc.data[key][0] + 1  # 0-based → 1-based
                except (KeyError, TypeError):
                    pass

            data[field_name] = self._convert_ruamel(value)
            prov[field_name] = ProvenanceInfo(
                source_type="yaml_file", path=path, line=line
            )

        return data, prov

    def _convert_ruamel(self, value: Any) -> Any:
        """Convert ruamel.yaml types to plain Python types."""
        if isinstance(value, CommentedMap):
            return {k: self._convert_ruamel(v) for k, v in value.items()}
        if isinstance(value, (CommentedSeq, list)):
            return [self._convert_ruamel(v) for v in value]
        return value

    # ------------------------------------------------------------------
    # Environment variable loading
    # ------------------------------------------------------------------

    def _load_env_vars(
        self,
    ) -> tuple[dict[str, Any], dict[str, ProvenanceInfo]]:
        """Read CONDA_* env vars and map them to field names."""
        data: dict[str, Any] = {}
        prov: dict[str, ProvenanceInfo] = {}

        for env_name, raw_value in self._environ.items():
            field_name = _ENV_VAR_MAP.get(env_name)
            if field_name is None:
                continue
            coerced = _coerce_env_var(field_name, raw_value)
            data[field_name] = coerced
            prov[field_name] = ProvenanceInfo(
                source_type="env_var", env_var=env_name
            )

        return data, prov

    # ------------------------------------------------------------------
    # Argparse loading
    # ------------------------------------------------------------------

    def _load_argparse(
        self, args: Namespace
    ) -> tuple[dict[str, Any], dict[str, ProvenanceInfo]]:
        """Extract non-None values from argparse Namespace."""
        data: dict[str, Any] = {}
        prov: dict[str, ProvenanceInfo] = {}

        for key, value in vars(args).items():
            if value is None:
                continue
            data[key] = value
            prov[key] = ProvenanceInfo(source_type="argparse")

        return data, prov

    # ------------------------------------------------------------------
    # Layer merging
    # ------------------------------------------------------------------

    def _merge_layer(
        self,
        merged: dict[str, Any],
        provenance: ProvenanceMap,
        layer_data: dict[str, Any],
        layer_prov: dict[str, ProvenanceInfo],
    ) -> None:
        """Merge one layer into the accumulated merged dict (in-place)."""
        for field_name, new_value in layer_data.items():
            existing = merged.get(field_name)

            if isinstance(new_value, list) and isinstance(existing, list):
                # Sequence merge: new (higher-priority) items prepended
                # Check if the new list has a trailing append marker
                if new_value and new_value[-1] == _APPEND_MARKER:
                    merged[field_name] = existing + new_value[:-1]
                else:
                    # Default: prepend
                    merged[field_name] = new_value + existing
            elif isinstance(new_value, dict) and isinstance(existing, dict):
                # Map merge: deep merge, higher-priority wins on collision
                merged_map = dict(existing)
                merged_map.update(new_value)
                merged[field_name] = merged_map
            else:
                # Primitive: higher-priority source wins
                merged[field_name] = new_value

            provenance[field_name] = layer_prov[field_name]
