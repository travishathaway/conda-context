"""
Schema generator for conda-context.

Reads conda's ``conda/base/context.py`` at a given Git tag via the GitHub
raw API and emits a versioned ``CondaConfig`` Pydantic model at
``conda_context/schemas/_XX_X_X.py``.

Usage::

    python -m conda_context.generator extract --conda-tag 26.5.3

The emitted module:
- Imports only from Python stdlib and pydantic
- Uses enum types from conda_context.constants (not from conda)
- Preserves field declaration order from conda source
- Is deterministic (same input → same output)
"""

from __future__ import annotations

import argparse
import ast
import sys
import textwrap
import urllib.request
from pathlib import Path
from typing import Any

# Map from conda constant names → (conda_context.constants attribute, default repr)
_CONSTANT_MAP: dict[str, tuple[str, str]] = {
    "DEFAULT_CHANNEL_ALIAS": ("DEFAULT_CHANNEL_ALIAS", "DEFAULT_CHANNEL_ALIAS"),
    "DEFAULT_CHANNELS": ("DEFAULT_CHANNELS", "DEFAULT_CHANNELS"),
    "DEFAULT_CUSTOM_CHANNELS": ("DEFAULT_CUSTOM_CHANNELS", "DEFAULT_CUSTOM_CHANNELS"),
    "DEFAULT_AGGRESSIVE_UPDATE_PACKAGES": (
        "DEFAULT_AGGRESSIVE_UPDATE_PACKAGES",
        "DEFAULT_AGGRESSIVE_UPDATE_PACKAGES",
    ),
    "DEFAULT_CONDA_LIST_FIELDS": ("DEFAULT_CONDA_LIST_FIELDS", "DEFAULT_CONDA_LIST_FIELDS"),
    "DEFAULT_CONSOLE_REPORTER_BACKEND": (
        "DEFAULT_CONSOLE_REPORTER_BACKEND",
        "DEFAULT_CONSOLE_REPORTER_BACKEND",
    ),
    "DEFAULT_SOLVER": ("DEFAULT_SOLVER", "DEFAULT_SOLVER"),
    "NO_PLUGINS": ("NO_PLUGINS", "NO_PLUGINS"),
    "REPODATA_FN": ("REPODATA_FN", "REPODATA_FN"),
    "ROOT_ENV_NAME": ("ROOT_ENV_NAME", "ROOT_ENV_NAME"),
}

_ENUM_TYPE_MAP: dict[str, str] = {
    "ChannelPriority": "ChannelPriority",
    "DepsModifier": "DepsModifier",
    "PathConflict": "PathConflict",
    "SafetyChecks": "SafetyChecks",
    "SatSolverChoice": "SatSolverChoice",
    "UpdateModifier": "UpdateModifier",
}

# Map Python type names used in element_type to Pydantic field type strings
_ELEMENT_TYPE_MAP: dict[str, str] = {
    "str": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "NoneType": "None",
}

_GITHUB_RAW = "https://raw.githubusercontent.com/conda/conda/{tag}/{path}"


# ---------------------------------------------------------------------------
# GitHub fetching
# ---------------------------------------------------------------------------


def fetch_file(tag: str, path: str) -> str:
    """Fetch a file from a conda GitHub tag via the raw API."""
    url = _GITHUB_RAW.format(tag=tag, path=path)
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read().decode("utf-8")
    except Exception as exc:
        raise RuntimeError(
            f"Failed to fetch {path} at tag {tag!r} from GitHub.\n"
            f"URL: {url}\n"
            f"Error: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# AST-based field extraction
# ---------------------------------------------------------------------------


class FieldSpec:
    """Represents one ParameterLoader field extracted from conda source."""

    def __init__(
        self,
        name: str,
        param_type: str,  # "primitive", "sequence", "map"
        default: Any,
        element_types: list[str],
        aliases: list[str],
        validation_fn: str | None,
        doc: str,
    ) -> None:
        self.name = name
        self.param_type = param_type
        self.default = default
        self.element_types = element_types
        self.aliases = aliases
        self.validation_fn = validation_fn
        self.doc = doc

    def public_name(self) -> str:
        """Strip leading underscore for private fields."""
        return self.name.lstrip("_")

    def pydantic_type(self) -> str:
        """Return the Pydantic-compatible Python type annotation."""
        if self.param_type == "primitive":
            types = [_ELEMENT_TYPE_MAP.get(t, t) for t in self.element_types]
            # Replace enum names with their string repr
            types = [_ENUM_TYPE_MAP.get(t, t) for t in types]
            types = list(dict.fromkeys(types))  # deduplicate
            if len(types) == 1:
                return types[0]
            return " | ".join(types)
        elif self.param_type == "sequence":
            inner_types = [_ELEMENT_TYPE_MAP.get(t, t) for t in self.element_types]
            inner_types = [_ENUM_TYPE_MAP.get(t, t) for t in inner_types]
            inner_types = list(dict.fromkeys(inner_types))
            inner = " | ".join(inner_types) if inner_types else "str"
            return f"tuple[{inner}, ...]"
        elif self.param_type == "map":
            return "dict[str, Any]"
        return "Any"


def _extract_node_value(node: ast.expr) -> Any:
    """Extract a Python value from an AST node (best-effort)."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Tuple):
        return tuple(_extract_node_value(e) for e in node.elts)
    if isinstance(node, ast.List):
        return [_extract_node_value(e) for e in node.elts]
    if isinstance(node, ast.Name):
        return node.id  # return the name as a string
    if isinstance(node, ast.Attribute):
        return f"{_extract_node_value(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        func = _extract_node_value(node.func)
        return f"<call:{func}>"
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_extract_node_value(node.operand)  # type: ignore[operator]
    return "<unknown>"


def _get_name(node: ast.expr) -> str:
    """Get the name of an AST Name or Attribute node."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def extract_fields(source: str) -> list[FieldSpec]:
    """Parse conda context.py source and extract ParameterLoader declarations."""
    tree = ast.parse(source)

    # Find the Context class
    context_class: ast.ClassDef | None = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Context":
            context_class = node
            break

    if context_class is None:
        raise ValueError("Could not find Context class in source")

    fields: list[FieldSpec] = []

    for stmt in context_class.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if len(stmt.targets) != 1:
            continue
        target = stmt.targets[0]
        if not isinstance(target, ast.Name):
            continue

        field_name = target.id
        value = stmt.value

        if not (isinstance(value, ast.Call) and _get_name(value.func) == "ParameterLoader"):
            continue

        # Parse ParameterLoader(param, aliases=..., ...)
        aliases: list[str] = []
        validation_fn: str | None = None
        param_type = "primitive"
        element_types: list[str] = ["str"]
        default: Any = None

        # First positional arg is the parameter
        if value.args:
            param_arg = value.args[0]
            if isinstance(param_arg, ast.Call):
                param_func = _get_name(param_arg.func)
                if param_func == "PrimitiveParameter":
                    param_type = "primitive"
                    if param_arg.args:
                        default = _extract_node_value(param_arg.args[0])
                    # element_type kwarg
                    for kw in param_arg.keywords:
                        if kw.arg == "element_type":
                            et = _extract_node_value(kw.value)
                            if isinstance(et, tuple):
                                element_types = [
                                    str(t).split(".")[-1] for t in et
                                ]
                            elif isinstance(et, str):
                                element_types = [et.split(".")[-1]]
                        elif kw.arg == "validation":
                            validation_fn = _extract_node_value(kw.value)
                            if isinstance(validation_fn, str):
                                validation_fn = validation_fn  # keep the function name

                    # Infer element type from default if not specified
                    if element_types == ["str"] and default is not None:
                        if isinstance(default, bool):
                            element_types = ["bool"]
                        elif isinstance(default, int):
                            element_types = ["int"]
                        elif isinstance(default, float):
                            element_types = ["float"]
                        elif isinstance(default, str) and default.startswith("<"):
                            # Enum or constant reference
                            raw_default = _extract_node_value(param_arg.args[0])
                            if isinstance(raw_default, str) and "." in str(raw_default):
                                # e.g. "ChannelPriority.FLEXIBLE"
                                enum_cls = str(raw_default).split(".")[0]
                                if enum_cls in _ENUM_TYPE_MAP:
                                    element_types = [enum_cls]

                elif param_func in ("SequenceParameter", "SequenceParam"):
                    param_type = "sequence"
                    if param_arg.args:
                        inner = param_arg.args[0]
                        if isinstance(inner, ast.Call) and _get_name(inner.func) == "PrimitiveParameter":
                            if inner.args:
                                d = _extract_node_value(inner.args[0])
                                if isinstance(d, bool):
                                    element_types = ["bool"]
                                elif isinstance(d, int):
                                    element_types = ["int"]
                                else:
                                    for kw2 in inner.keywords:
                                        if kw2.arg == "element_type":
                                            et2 = _extract_node_value(kw2.value)
                                            if isinstance(et2, str):
                                                element_types = [et2.split(".")[-1]]
                    default = ()

                elif param_func in ("MapParameter", "MapParam"):
                    param_type = "map"
                    default = {}

        # Extract aliases keyword
        for kw in value.keywords:
            if kw.arg == "aliases":
                raw = _extract_node_value(kw.value)
                if isinstance(raw, tuple):
                    aliases = [str(a) for a in raw if isinstance(a, str)]
                elif isinstance(raw, list):
                    aliases = [str(a) for a in raw if isinstance(a, str)]
                elif isinstance(raw, str):
                    aliases = [raw]

        # Build doc string from field name
        doc = field_name.lstrip("_").replace("_", " ").capitalize()

        fields.append(
            FieldSpec(
                name=field_name,
                param_type=param_type,
                default=default,
                element_types=element_types,
                aliases=aliases,
                validation_fn=str(validation_fn) if validation_fn else None,
                doc=doc,
            )
        )

    return fields


# ---------------------------------------------------------------------------
# Code emission
# ---------------------------------------------------------------------------


_HEADER = '''\
"""
CondaConfig — Pydantic v2 model for conda {version} configuration.

AUTO-GENERATED by conda_context.generator.
Source: conda/base/context.py at tag {version}
Do not edit manually; re-run `python -m conda_context.generator extract --conda-tag {version}`.
"""

from __future__ import annotations

import sys
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from conda_context.constants import (
    CONDA_LIST_FIELDS,
    DEFAULT_AGGRESSIVE_UPDATE_PACKAGES,
    DEFAULT_CHANNEL_ALIAS,
    DEFAULT_CHANNELS,
    DEFAULT_CONDA_LIST_FIELDS,
    DEFAULT_CONSOLE_REPORTER_BACKEND,
    DEFAULT_CUSTOM_CHANNELS,
    DEFAULT_SOLVER,
    NO_PLUGINS,
    REPODATA_FN,
    ROOT_ENV_NAME,
    ChannelPriority,
    DepsModifier,
    PathConflict,
    SafetyChecks,
    SatSolverChoice,
    UpdateModifier,
)


def _default_python_default() -> str:
    ver = sys.version_info
    return "%d.%d" % (ver.major, ver.minor)


class CondaConfig(BaseModel):
    """Pydantic model for all conda {version} configuration fields."""

    model_config = ConfigDict(
        populate_by_name=True,
        use_enum_values=True,
        extra="ignore",
    )

'''


def _field_default_repr(field: FieldSpec) -> str:
    """Return a Python repr string for the field's default value."""
    d = field.default
    if d is None:
        return "None"
    if isinstance(d, bool):
        return str(d)
    if isinstance(d, (int, float)):
        return str(d)
    if isinstance(d, str):
        if d.startswith("<call:") or d == "<unknown>":
            # Can't represent this; fall back to None
            return "None"
        # Check if it's a constant or enum reference
        if d in _CONSTANT_MAP:
            return _CONSTANT_MAP[d][1]
        if "." in d:
            parts = d.split(".")
            if parts[0] in _ENUM_TYPE_MAP:
                return d  # e.g. "ChannelPriority.FLEXIBLE"
        return repr(d)
    if isinstance(d, (tuple, list)):
        if len(d) == 0:
            return "()" if isinstance(d, tuple) else "[]"
        return repr(d)
    if isinstance(d, dict):
        return "{}"
    return repr(d)


def emit_schema(fields: list[FieldSpec], version: str) -> str:
    """Emit a Python source string for the CondaConfig model."""
    lines: list[str] = [_HEADER.format(version=version)]

    for field in fields:
        pub_name = field.public_name()
        py_type = field.pydantic_type()
        default_repr = _field_default_repr(field)
        doc = field.doc

        alias_part = ""
        if field.aliases:
            # Use the first non-private-prefixed alias, or the original name
            primary_alias = field.aliases[0]
            alias_part = f', alias="{primary_alias}"'

        # Field declaration
        if default_repr in ("None", "()"):
            lines.append(f"    {pub_name}: {py_type} = Field(")
            lines.append(f"        default={default_repr},{alias_part}")
            lines.append(f'        description="{doc}",')
            lines.append("    )")
        else:
            lines.append(f"    {pub_name}: {py_type} = Field(")
            lines.append(f"        default={default_repr},{alias_part}")
            lines.append(f'        description="{doc}",')
            lines.append("    )")
        lines.append("")

    # Close class (validators omitted in generated version — they must be hand-verified)
    lines.append(
        "    # NOTE: Field validators and cross-field validators are not auto-generated.\n"
        "    # Copy them from schemas/_26_5_3.py after reviewing the diff.\n"
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m conda_context.generator",
        description="Generate a versioned CondaConfig schema from conda source.",
    )
    sub = parser.add_subparsers(dest="command")

    extract_parser = sub.add_parser(
        "extract",
        help="Extract fields from a conda Git tag and emit a schema module.",
    )
    extract_parser.add_argument(
        "--conda-tag",
        required=True,
        help="conda Git tag to extract from (e.g., 26.5.3)",
    )
    extract_parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory to write the schema module (default: conda_context/schemas/)",
    )
    extract_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated code without writing to disk.",
    )

    args = parser.parse_args(argv)

    if args.command == "extract":
        return _cmd_extract(args)

    parser.print_help()
    return 1


def _cmd_extract(args: argparse.Namespace) -> int:
    tag = args.conda_tag
    print(f"Fetching conda/base/context.py at tag {tag!r}…", file=sys.stderr)

    try:
        source = fetch_file(tag, "conda/base/context.py")
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Parsing ParameterLoader declarations…", file=sys.stderr)
    fields = extract_fields(source)
    print(f"Found {len(fields)} fields.", file=sys.stderr)

    code = emit_schema(fields, tag)

    module_name = "_" + tag.replace(".", "_")
    filename = f"{module_name}.py"

    if args.dry_run:
        print(code)
        return 0

    # Determine output directory
    if args.output_dir:
        out_dir = Path(args.output_dir)
    else:
        # Default: conda_context/schemas/ relative to this file's package root
        this_file = Path(__file__).resolve()
        out_dir = this_file.parent.parent / "schemas"

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename

    out_path.write_text(code, encoding="utf-8")
    print(f"Written: {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
