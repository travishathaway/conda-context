"""Tests for the schema generator."""

from __future__ import annotations

from unittest.mock import patch

from conda_context.generator.__main__ import (
    FieldSpec,
    emit_schema,
    extract_fields,
    main,
)

# Minimal conda context.py snippet for testing
_MINIMAL_CONTEXT_SOURCE = (
    "\nclass Context:\n"
    "    add_pip_as_python_dependency = ParameterLoader(PrimitiveParameter(True))\n"
    "    _channels = ParameterLoader(\n"
    '        SequenceParameter(PrimitiveParameter("", element_type=str), default=()),\n'
    '        aliases=("channels", "channel"),\n'
    "    )\n"
    "    proxy_servers = ParameterLoader(\n"
    "        MapParameter(PrimitiveParameter(None, (str, NoneType))),\n"
    "    )\n"
    '    always_copy = ParameterLoader(PrimitiveParameter(False), aliases=("copy",))\n'
)


class TestExtractFields:
    def test_extracts_primitive_field(self):
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        names = [f.name for f in fields]
        assert "add_pip_as_python_dependency" in names

    def test_extracts_sequence_field(self):
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        channel_field = next(f for f in fields if f.name == "_channels")
        assert channel_field.param_type == "sequence"

    def test_extracts_map_field(self):
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        proxy_field = next(f for f in fields if f.name == "proxy_servers")
        assert proxy_field.param_type == "map"

    def test_aliases_extracted(self):
        """Scenario: Aliases are preserved."""
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        copy_field = next(f for f in fields if f.name == "always_copy")
        assert "copy" in copy_field.aliases

    def test_field_order_preserved(self):
        """Scenario: Field order is stable across runs."""
        fields1 = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        fields2 = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        assert [f.name for f in fields1] == [f.name for f in fields2]


class TestEmitSchema:
    def test_emit_produces_string(self):
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        code = emit_schema(fields, "26.5.3")
        assert isinstance(code, str)
        assert len(code) > 0

    def test_emitted_code_contains_field_names(self):
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        code = emit_schema(fields, "26.5.3")
        assert "add_pip_as_python_dependency" in code
        assert "proxy_servers" in code

    def test_emitted_code_has_no_conda_imports(self):
        """Scenario: Generated module imports only stdlib and pydantic."""
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        code = emit_schema(fields, "26.5.3")
        lines = code.splitlines()
        conda_imports = [
            line
            for line in lines
            if line.startswith("from conda.") or line.startswith("import conda.")
        ]
        assert len(conda_imports) == 0

    def test_emitted_code_is_deterministic(self):
        """Scenario: Field order is stable across runs."""
        fields = extract_fields(_MINIMAL_CONTEXT_SOURCE)
        code1 = emit_schema(fields, "26.5.3")
        code2 = emit_schema(fields, "26.5.3")
        assert code1 == code2


class TestCLI:
    def test_extract_dry_run(self, capsys):
        """Scenario: --dry-run prints code without writing."""
        with patch(
            "conda_context.generator.__main__.fetch_file",
            return_value=_MINIMAL_CONTEXT_SOURCE,
        ):
            result = main(["extract", "--conda-tag", "26.5.3", "--dry-run"])

        assert result == 0
        out = capsys.readouterr().out
        assert "CondaConfig" in out

    def test_extract_bad_tag_returns_nonzero(self, capsys):
        """Scenario: Unknown tag returns non-zero exit code."""
        with patch(
            "conda_context.generator.__main__.fetch_file",
            side_effect=RuntimeError("Tag not found"),
        ):
            result = main(["extract", "--conda-tag", "99.0.0"])

        assert result != 0

    def test_no_command_returns_nonzero(self):
        result = main([])
        assert result != 0


class TestFieldSpec:
    def test_public_name_strips_underscore(self):
        f = FieldSpec("_channels", "sequence", (), ["str"], [], None, "channels")
        assert f.public_name() == "channels"

    def test_public_name_no_underscore(self):
        f = FieldSpec("ssl_verify", "primitive", True, ["bool"], [], None, "ssl verify")
        assert f.public_name() == "ssl_verify"

    def test_pydantic_type_primitive_bool(self):
        f = FieldSpec("x", "primitive", True, ["bool"], [], None, "x")
        assert f.pydantic_type() == "bool"

    def test_pydantic_type_sequence(self):
        f = FieldSpec("x", "sequence", (), ["str"], [], None, "x")
        assert "tuple" in f.pydantic_type()

    def test_pydantic_type_map(self):
        f = FieldSpec("x", "map", {}, ["str"], [], None, "x")
        assert "dict" in f.pydantic_type()
