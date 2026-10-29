"""The help is what an agent reads when the rules send it there, so it has to run and
has to agree with the rules."""

import shlex

import pytest

from clarity import cli


def _examples(text: str) -> list[str]:
    return [line.split("$ ", 1)[1] for line in text.splitlines()
            if line.lstrip().startswith("$ clarity-ctl ")]


def test_every_example_in_the_help_parses():
    """An example that no longer parses is how `epoch start 3` outlived start by name."""
    examples = _examples(cli.reference_text())
    assert len(examples) >= 10
    for example in examples:
        argv = shlex.split(example)[1:]
        try:
            cli.build_parser().parse_args(argv)
        except SystemExit:
            pytest.fail(f"help example does not parse: {example}")


def test_the_top_help_leads_with_how_work_goes_and_states_the_contract():
    text = cli.build_parser().format_help()
    assert text.index("How work goes") < text.index("All commands") < text.index("Contract")
    for needed in ("DECISION:", "HANDOFF:", "--json", "Exit codes", "help reference"):
        assert needed in text
    assert "─" not in text  # plain text: no box lines for an agent to read past


def test_the_listing_names_every_command():
    text = cli.build_parser().format_help()
    for name in ("init", "adopt", "status", "show", "note", "archive", "claim", "release"):
        assert f" {name}" in text
    assert "epoch start|spawn|reopen" in text


def test_help_reference_holds_every_command_and_works_outside_a_project(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["help", "reference"]) == 0
    out = capsys.readouterr().out
    for heading in ("## clarity-ctl epoch start", "## clarity-ctl epoch close",
                    "## clarity-ctl note", "## clarity-ctl repo add", "## clarity-ctl help"):
        assert heading in out


def test_note_and_close_help_say_what_the_rules_say():
    reference = cli.reference_text()
    assert "what you tried" not in reference  # the rules: a note is a decision changing
    assert "asks for the outcome" not in reference
    assert "Close only when the whole task is done and merged" in reference
