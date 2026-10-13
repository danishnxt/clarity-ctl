"""The marker block in other agents' instructions files.

These files belong to the user, not to clarity. Every test here is about the
same promise: we own what is between our markers and nothing else.
Run: .venv/bin/python -m pytest -q
"""

from clarity import Project, agents

MINE = "# My rules\n\nAlways rebase.\n"


def test_upsert_writes_only_between_the_markers(tmp_path):
    # an empty place gets the block
    path = tmp_path / "AGENTS.md"
    assert agents.upsert(path) == "created"
    assert agents.START in path.read_text() and agents.END in path.read_text()

    # rerunning changes nothing — idempotent to the byte
    before = path.read_text()
    assert agents.upsert(path) == "unchanged"
    assert path.read_text() == before

    # the whole point: a user's own rules keep their file
    path = tmp_path / "CLAUDE.md"
    path.write_text(MINE)
    assert agents.upsert(path) == "updated"
    text = path.read_text()
    assert text.startswith(MINE.rstrip())  # theirs first, untouched
    assert agents.START in text

    # content on both sides of the markers is preserved verbatim
    path = tmp_path / "GEMINI.md"
    path.write_text(f"BEFORE\n\n{agents.START}\nstale\n{agents.END}\n\nAFTER\n")
    assert agents.upsert(path) == "updated"
    text = path.read_text()
    assert text.startswith("BEFORE") and text.rstrip().endswith("AFTER")
    assert "stale" not in text


def test_remove_gives_back_exactly_what_was_there(tmp_path):
    # theirs plus ours: back to exactly what they had
    theirs = tmp_path / "CLAUDE.md"
    theirs.write_text(MINE)
    agents.upsert(theirs)
    assert agents.remove(theirs) == "removed"
    assert theirs.read_text().rstrip() == MINE.rstrip()

    # only ours: we created it, so we take it away
    ours = tmp_path / "AGENTS.md"
    agents.upsert(ours)
    assert agents.remove(ours) == "removed"
    assert not ours.exists()

    # never ours: left alone
    stranger = tmp_path / "GEMINI.md"
    stranger.write_text(MINE)
    assert agents.remove(stranger) == "absent"
    assert stranger.read_text() == MINE


def test_a_symlink_that_is_not_ours_is_left_alone(project, repo):
    elsewhere = repo / "house-style.md"
    elsewhere.write_text(MINE)
    link = repo / "CLAUDE.md"
    link.unlink()
    link.symlink_to(elsewhere.name)

    assert agents.upsert(link) == "skipped"  # theirs, so we keep our hands off
    assert link.is_symlink()


def test_local_targets_skip_agents_nobody_here_runs(project, repo):
    names = {p.name for p in agents.local_paths(repo)}

    assert {"AGENTS.md", "CLAUDE.md"} <= names   # always written
    assert "GEMINI.md" not in names             # no GEMINI.md here, so no litter

    (repo / "GEMINI.md").write_text(MINE)
    assert "GEMINI.md" in {p.name for p in agents.local_paths(repo)}


def test_the_block_does_not_hedge():
    """It sits next to the worklog — doubting the repo it's in would be nonsense."""
    assert "ignore" not in agents.LOCAL_BLOCK
    assert "This project's state lives in clarity" in agents.LOCAL_BLOCK


def test_refresh_rewrites_a_stale_block_and_never_adds_one(tmp_path):
    path = tmp_path / "AGENTS.md"
    path.write_text(f"{MINE}\n{agents.START}\nclarity-ctl q active\n{agents.END}\n")

    assert agents.refresh([path]) == [path]
    text = path.read_text()
    assert "clarity-ctl q " not in text and MINE.rstrip() in text
    assert agents.refresh([path]) == []          # current now: nothing to write

    # a file without one is the user's choice — removed, or never installed
    mine, missing = tmp_path / "GEMINI.md", tmp_path / "CLAUDE.md"
    mine.write_text(MINE)
    assert agents.refresh([mine, missing]) == []
    assert mine.read_text() == MINE and not missing.exists()


def test_install_refreshes_a_stale_block(project, repo):
    path = repo / "CLAUDE.md"
    path.write_text(f"{MINE}\n{agents.START}\nstale\n{agents.END}\n")

    project.install_agents()
    text = path.read_text()
    assert "stale" not in text and MINE.rstrip() in text


def test_claude_imports_agents_instead_of_copying_it(project, repo):
    """One body of text. Two copies would be two things to keep in step."""
    agents_md = (repo / "AGENTS.md").read_text()
    claude_md = (repo / "CLAUDE.md").read_text()

    assert "clarity-ctl status" in agents_md          # AGENTS.md carries the body
    assert "@AGENTS.md" in claude_md              # CLAUDE.md imports it
    assert "clarity-ctl status" not in claude_md      # and does not repeat it


def test_no_file_carries_a_copy_of_the_objective(repo):
    """The objective lives in worklog.yaml. clarity-ctl status prints it; nothing caches it."""
    Project.create(repo, name="proj", overall="ship the parser")
    project = Project.find(repo)
    project.set_objective("ship the parser, then benchmarks")

    for name in ("AGENTS.md", "CLAUDE.md"):
        text = (repo / name).read_text()
        assert "ship the parser" not in text and "benchmarks" not in text
    assert not (repo / ".clarity" / "RULES.md").exists()
    assert "ship the parser, then benchmarks" in project.status_text()
