"""The help is what an agent reads when the rules send it there, so it has to run and
has to agree with the rules."""

import argparse
import re
import shlex
from pathlib import Path

import pytest

from clarity import cli

COMMANDS = {
    "status", "show", "search", "help",
    "start", "close", "note", "spawn", "refresh", "claim", "rename", "add-repo", "drop-repo",
    "idea", "archive", "init", "adopt", "objective", "repo add", "repo remove",
}


def _leaves(parser, path=()):
    """Every command a person can type, as {name: its parser}: one word, or two for repo."""
    out = {}
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                nested = _leaves(child, (*path, name))
                out.update(nested or {" ".join((*path, name)): child})
    return out


def _examples(text: str) -> list[str]:
    return [line.split("$ ", 1)[1] for line in text.splitlines()
            if line.lstrip().startswith("$ clarity-ctl ")]


def test_every_example_in_the_help_parses():
    """An example that no longer parses is how a renamed command stays in the examples."""
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


def test_the_commands_are_exactly_these_and_only_the_reads_take_json():
    leaves = _leaves(cli.build_parser())
    assert set(leaves) == COMMANDS
    has_json = {name for name, node in leaves.items()
                if any("--json" in a.option_strings for a in node._actions)}
    assert has_json == {"status", "show", "search"}
    assert not [n for n, node in leaves.items()
                if any("--agent" in o.option_strings for o in node._actions)]


def test_the_listing_names_every_command_and_the_help_reference_has_a_page_each(
        tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    listing = cli.build_parser().format_help()
    assert "repo add|remove" in listing
    for name in COMMANDS - {"repo add", "repo remove"}:
        assert f" {name}" in listing
    assert cli.main(["help", "reference"]) == 0  # works outside a project
    out = capsys.readouterr().out
    for name in COMMANDS:
        assert f"## clarity-ctl {name}\n" in out


def test_note_and_close_help_say_what_the_rules_say():
    reference = cli.reference_text()
    assert "what you tried" not in reference  # the rules: a note is a decision changing
    assert "asks for the outcome" not in reference
    assert "Close only when the whole task is done and merged" in reference


PROSE = {"than", "would", "still", "reference"}  # "a newer clarity-ctl than this one"; a heading


def _invocations(text: str):
    """Every `clarity-ctl ...` in a text, as the words after it, placeholders filled in."""
    for found in re.finditer(r"clarity-ctl ([^\n`]*)", text):
        line = re.split(r" — |  #|; |\\n", found.group(1))[0]
        line = re.sub(r"<[^>|]*\|[^>]*>", "all", re.sub(r"<[^>]*>", "1", line))
        line = re.sub(r"\{[^}]*\}", "1", line).replace('"..."', "x")
        words = [w.strip("\"'.,:;)(") for w in line.split()]
        words = [w for w in words if w]
        if words and words[0] not in PROSE and not words[0].startswith(("1", "-")):
            yield words


def test_every_command_and_flag_the_product_names_exists():
    """The rules, the help, the hints and nags in src and adopt.md all tell an agent what to
    type. One that names a command or flag the parser lacks is how a rename leaves dead
    instructions behind."""
    leaves = _leaves(cli.build_parser())
    reference = re.sub(r"^(#|usage:).*$", "", cli.reference_text(), flags=re.M)  # headings and usage lines are not uses
    texts = [reference] + [p.read_text() for p in Path(cli.__file__).parent.glob("*.py")]
    seen = 0
    for text in texts:
        assert "--agent" not in text  # plain text is chosen by the terminal, not a flag
        for words in _invocations(text):
            name = " ".join(words[:2]) if words[0] == "repo" else words[0]
            assert name in leaves, f"clarity-ctl {' '.join(words)}: no command {name!r}"
            allowed = {o for a in leaves[name]._actions for o in a.option_strings}
            for word in words:
                if word.startswith("--"):
                    assert word.split("=")[0] in allowed, \
                        f"clarity-ctl {' '.join(words)}: {name} has no {word}"
            seen += 1
    assert seen > 80
