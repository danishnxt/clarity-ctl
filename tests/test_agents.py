"""The marker block in other agents' instructions files.

These files belong to the user, not to clarity. Every test here is about the
same promise: we own what is between our markers and nothing else.
Run: .venv/bin/python -m pytest -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import Project, agents  # noqa: E402

from test_lifecycle import make_repo  # noqa: E402

MINE = "# My rules\n\nAlways rebase.\n"


def test_block_lands_in_an_empty_place(tmp_path):
    path = tmp_path / "AGENTS.md"
    assert agents.upsert(path) == "created"
    assert agents.START in path.read_text() and agents.END in path.read_text()


def test_existing_content_survives(tmp_path):
    """The whole point: a user's own rules keep their file."""
    path = tmp_path / "CLAUDE.md"
    path.write_text(MINE)

    assert agents.upsert(path) == "updated"
    text = path.read_text()
    assert text.startswith(MINE.rstrip())  # theirs first, untouched
    assert agents.START in text


def test_rerunning_changes_nothing(tmp_path):
    path = tmp_path / "AGENTS.md"
    agents.upsert(path)
    before = path.read_text()

    assert agents.upsert(path) == "unchanged"
    assert path.read_text() == before  # idempotent to the byte


def test_only_our_block_is_replaced(tmp_path):
    """Content on both sides of the markers is preserved verbatim."""
    path = tmp_path / "AGENTS.md"
    path.write_text(f"BEFORE\n\n{agents.START}\nstale\n{agents.END}\n\nAFTER\n")

    assert agents.upsert(path) == "updated"
    text = path.read_text()
    assert text.startswith("BEFORE") and text.rstrip().endswith("AFTER")
    assert "stale" not in text


def test_remove_gives_the_file_back(tmp_path):
    path = tmp_path / "CLAUDE.md"
    path.write_text(MINE)
    agents.upsert(path)

    assert agents.remove(path) == "removed"
    assert path.read_text().rstrip() == MINE.rstrip()  # exactly what they had


def test_remove_deletes_a_file_that_was_only_ours(tmp_path):
    path = tmp_path / "AGENTS.md"
    agents.upsert(path)

    assert agents.remove(path) == "removed"
    assert not path.exists()  # we created it, so we take it away


def test_remove_leaves_a_stranger_alone(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(MINE)

    assert agents.remove(path) == "absent"
    assert path.read_text() == MINE


def test_a_symlink_that_is_not_ours_is_left_alone(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    elsewhere = root / "house-style.md"
    elsewhere.write_text(MINE)
    link = root / "CLAUDE.md"
    link.unlink()
    link.symlink_to(elsewhere.name)

    assert agents.upsert(link) == "skipped"  # theirs, so we keep our hands off
    assert link.is_symlink()


def test_local_targets_skip_agents_nobody_here_runs(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    names = {p.name for p in agents.local_paths(root)}

    assert {"AGENTS.md", "CLAUDE.md"} <= names   # always written
    assert "GEMINI.md" not in names             # no GEMINI.md here, so no litter

    (root / "GEMINI.md").write_text(MINE)
    assert "GEMINI.md" in {p.name for p in agents.local_paths(root)}


def test_the_block_does_not_hedge(tmp_path):
    """It sits next to the worklog — doubting the repo it's in would be nonsense."""
    assert "ignore" not in agents.LOCAL_BLOCK
    assert "This project's state lives in clarity" in agents.LOCAL_BLOCK


def test_refresh_rewrites_a_stale_block_and_keeps_the_rest(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"{MINE}\n{agents.START}\nclarity-ctl q active\n{agents.END}\n")

    assert agents.refresh([path]) == [path]
    text = path.read_text()
    assert "clarity-ctl q " not in text and MINE.rstrip() in text
    assert agents.refresh([path]) == []          # current now: nothing to write


def test_refresh_never_adds_a_block(tmp_path):
    """A file without one is the user's choice — removed, or never installed."""
    mine, missing = tmp_path / "AGENTS.md", tmp_path / "CLAUDE.md"
    mine.write_text(MINE)

    assert agents.refresh([mine, missing]) == []
    assert mine.read_text() == MINE and not missing.exists()


def test_install_refreshes_a_stale_block(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    path = root / "CLAUDE.md"
    path.write_text(f"{MINE}\n{agents.START}\nstale\n{agents.END}\n")

    Project.find(root).install_agents()
    text = path.read_text()
    assert "stale" not in text and MINE.rstrip() in text


def test_claude_imports_agents_instead_of_copying_it(tmp_path):
    """One body of text. Two copies would be two things to keep in step."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")

    agents_md = (root / "AGENTS.md").read_text()
    claude_md = (root / "CLAUDE.md").read_text()

    assert "clarity-ctl status" in agents_md          # AGENTS.md carries the body
    assert "@AGENTS.md" in claude_md              # CLAUDE.md imports it
    assert "clarity-ctl status" not in claude_md      # and does not repeat it


def test_no_file_carries_a_copy_of_the_objective(tmp_path):
    """The objective lives in worklog.yaml. clarity-ctl status prints it; nothing caches it."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj", overall="ship the parser")
    project = Project.find(root)
    project.set_objective("ship the parser, then benchmarks")

    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (root / name).read_text()
        assert "ship the parser" not in text and "benchmarks" not in text
    assert not (root / ".clarity" / "RULES.md").exists()
    assert "ship the parser, then benchmarks" in project.status_text()
