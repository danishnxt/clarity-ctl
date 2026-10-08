"""Smoke tests for the item lifecycle. Run: .venv/bin/python -m pytest -q"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import ClarityError, Project  # noqa: E402
from clarity import agents  # noqa: E402
from clarity.render import EPOCH_MARK_END  # noqa: E402


def git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True)


def make_repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hi')\n")
    git(["init", "-q"], root)
    git(["add", "-A"], root)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init"], root)
    return root


def test_init_creates_layout(tmp_path):
    root = make_repo(tmp_path)
    project = Project.create(root, name="proj", overall="ship it")

    assert (root / "worklog.yaml").exists()
    assert (root / ".clarity" / "config.yaml").exists()
    assert not (root / "STATUS.md").exists()  # the status view is printed, never written
    for name in ("AGENTS.md", "CLAUDE.md"):  # real files now, carrying our block
        assert not (root / name).is_symlink()
        assert agents.START in (root / name).read_text()
    assert not (root / ".clarity" / "RULES.md").exists()  # the block is the only copy
    assert "EPOCHS/*/wt/" in (root / ".gitignore").read_text()
    assert project.worklog.items == []


def test_idea_to_done(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")

    project = Project.find(root)
    item = project.add("flaky test", type_="fix")
    assert item.status == "idea" and item.folder is None

    project.start(item.id)  # straight from idea: the folder comes with the start
    started = project.worklog.by_id(item.id)
    assert started.status == "active"
    assert (root / started.folder).is_dir()
    assert started.branch == f"epoch/{item.id:03d}-flaky-test"
    assert (root / started.folder / "wt" / root.name).is_dir()

    project.note(item.id, "tried a bigger timeout")
    project.block(item.id, "waiting upstream")
    assert project.worklog.by_id(item.id).blocked_reason == "waiting upstream"
    project.unblock(item.id)

    project.close(item.id, outcome="bumped the timeout")
    closed = project.worklog.by_id(item.id)
    assert closed.status == "done" and closed.outcome == "bumped the timeout"
    assert not (root / closed.folder / "wt" / root.name).exists()  # worktree gone
    branches = subprocess.run(
        ["git", "branch", "--list", closed.branch], cwd=str(root),
        capture_output=True, text=True,
    ).stdout
    assert closed.branch in branches  # branch survives


def test_only_work_in_flight_can_be_blocked(tmp_path):
    """Blocking an idea used to put it in flight with no folder or branch."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)

    idea = project.add("someday")
    with pytest.raises(ClarityError) as err:
        project.block(idea.id, "waiting")
    assert err.value.code == 4 and "epoch start" in str(err.value)
    assert project.worklog.by_id(idea.id).status == "idea"

    done = project.add("shipped")
    project.start(done.id, branch="main")
    project.close(done.id, "done")
    with pytest.raises(ClarityError):
        project.block(done.id, "waiting")
    assert project.worklog.by_id(done.id).status == "done"

    live = project.add("live")
    project.start(live.id, branch="main")
    project.block(live.id, "waiting upstream")
    project.block(live.id, "waiting on review")  # a second block just updates the reason
    assert project.worklog.by_id(live.id).blocked_reason == "waiting on review"
    assert project.unblock(live.id).status == "active"


def test_existing_branch_is_symlinked(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)

    item = project.add("bench baseline", type_="experiment")
    project.start(item.id, branch="main")  # main is checked out at the root

    link = root / project.worklog.by_id(item.id).folder / "wt" / root.name
    assert link.is_symlink()
    assert link.resolve() == root.resolve()


def test_human_notes_survive_regeneration(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("write docs").id)

    epoch_md = root / item.folder / "EPOCH.md"
    epoch_md.write_text(epoch_md.read_text() + "my own scratch notes\n")

    project.note(item.id, "started drafting")
    text = epoch_md.read_text()
    assert "my own scratch notes" in text
    assert "started drafting" in text
    assert text.index("started drafting") < text.index(EPOCH_MARK_END)


def test_errors_carry_exit_codes(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)

    try:
        project.worklog.by_id(99)
    except ClarityError as err:
        assert err.code == 4
    else:
        raise AssertionError("expected ClarityError")

    try:
        Project.find(tmp_path)
    except ClarityError as err:
        assert err.code == 3
    else:
        raise AssertionError("expected ClarityError")


def test_plans_live_in_the_epoch_and_are_listed(tmp_path):
    """Long-form docs sit with the work, and are listed when asked for — not cached."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)

    folder = root / item.folder
    assert (folder / "PLANS").is_dir()

    (folder / "PLANS" / "approach.md").write_text("# how we'll do it\n")
    project.note(item.id, "ring buffer, 2x slower — PLANS/approach.md")

    # listed at read time, not cached into EPOCH.md: PLANS/ is a directory anyone can
    # drop a file into, so no command can know when it changed
    assert project.query("item", str(item.id))["plans"] == ["approach.md"]
    assert "## Plans" not in (folder / "EPOCH.md").read_text()


def test_reopen_returns_a_closed_epoch_to_active(tmp_path):
    """Reopening keeps the old outcome in the trail instead of overwriting it."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)
    project.close(item.id, outcome="2x slower, dropped")

    try:
        project.start(item.id)
    except ClarityError as err:
        assert err.code == 4 and "reopen" in str(err)
    else:
        raise AssertionError("a closed epoch must not restart silently")

    project.start(item.id, reopen=True)
    reopened = project.worklog.by_id(item.id)
    assert reopened.status == "active"
    assert reopened.outcome is None and reopened.ended is None
    assert "previous outcome: 2x slower, dropped" in reopened.notes[-1].text
    assert (root / reopened.folder / "wt" / root.name).exists()  # worktree back


def test_reopen_warns_when_the_branch_is_behind(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)
    project.close(item.id, outcome="parked")

    # main moves on while the epoch is closed
    (root / "later.txt").write_text("more\n")
    git(["add", "-A"], root)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "later"], root)

    _, warnings = project.start(item.id, reopen=True)
    assert any("behind main" in w for w in warnings), warnings


def test_refresh_catches_the_branch_up_without_losing_commits(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)

    # the epoch commits something of its own, then main moves on underneath it
    worktree = project.folder_of(item) / "wt" / root.name
    (worktree / "epoch.txt").write_text("mine\n")
    git(["add", "-A"], worktree)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "epoch work"], worktree)
    (root / "later.txt").write_text("more\n")
    git(["add", "-A"], root)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "later"], root)

    _, report = project.refresh(item.id)
    assert report["merged"] == [{"repo": ".", "base": "main", "commits": 1}], report
    assert (worktree / "later.txt").exists()       # main's commit arrived
    assert (worktree / "epoch.txt").exists()       # the epoch's own work survived
    assert project.refresh(item.id)[1] == {"merged": [],
                                           "up_to_date": [{"repo": ".", "base": "main"}]}


def test_refresh_follows_the_base_recorded_at_start(tmp_path):
    """Cut from dev, the epoch keeps following dev after the checkout moves on."""
    root = make_repo(tmp_path)
    git(["checkout", "-qb", "dev"], root)  # the work lives on a long-running branch
    Project.create(root, name="proj")
    project = Project.find(root)
    item = project.add("cache warmup")
    item, _ = project.start(item.id)
    assert item.bases == {".": "dev"}
    worktree = project.folder_of(item) / "wt" / root.name

    commit = ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm"]
    (root / "later.txt").write_text("more\n")
    git(["add", "later.txt"], root)
    git([*commit, "later"], root)
    # someone switches the checkout for unrelated work, which moves on too
    git(["checkout", "-qb", "feature-x"], root)
    (root / "unrelated.txt").write_text("x\n")
    git(["add", "unrelated.txt"], root)
    git([*commit, "unrelated"], root)

    notes = " ".join(project.stale_map()[item.id])
    assert "1 behind dev" in notes and "checkout is on feature-x" in notes
    _, report = project.refresh(item.id)
    assert [m["base"] for m in report["merged"]] == ["dev"], report
    assert (worktree / "later.txt").exists()
    assert not (worktree / "unrelated.txt").exists()

    # changing the base is deliberate, and recorded
    _, report = Project.find(root).refresh(item.id, base="feature-x")
    assert report["merged"][0]["base"] == "feature-x" and (worktree / "unrelated.txt").exists()
    after = Project.find(root).worklog.by_id(item.id)
    assert after.bases == {".": "feature-x"} and "base set to feature-x" in after.notes[-1].text
    with pytest.raises(ClarityError):
        Project.find(root).refresh(item.id, base="no-such-branch")


def test_refresh_refuses_a_dirty_worktree(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)
    (root / "later.txt").write_text("more\n")
    git(["add", "-A"], root)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "later"], root)

    worktree = project.folder_of(item) / "wt" / root.name
    (worktree / "scratch.txt").write_text("uncommitted\n")
    try:
        project.refresh(item.id)
    except ClarityError as exc:
        assert exc.code == 4 and "commit or stash" in str(exc)
    else:
        raise AssertionError("a dirty worktree should refuse to refresh")


def test_closed_seq_orders_same_day_closes(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    first = project.add("first")
    second = project.add("second")
    project.start(first.id)
    project.start(second.id)

    # closed in the order second, first — same calendar day, so `ended` cannot tell
    project.close(second.id, outcome="b")
    project.close(first.id, outcome="a")

    by_id = {i.id: i for i in project.worklog.items}
    assert by_id[second.id].ended == by_id[first.id].ended   # the date really does tie
    assert by_id[second.id].closed_seq < by_id[first.id].closed_seq

    # the status page reads newest-finished first, so the later close leads
    body = project.status_text(show_all=True)
    closed = body.split("Closed")[1]
    assert closed.index("first") < closed.index("second"), closed


def test_reclosing_after_reopen_takes_a_fresh_seq(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    old = project.add("old")
    recent = project.add("recent")
    project.start(old.id)
    project.close(old.id, outcome="done once")
    project.start(recent.id)
    project.close(recent.id, outcome="done later")

    was = {i.id: i.closed_seq for i in project.worklog.items}[old.id]
    project.start(old.id, reopen=True)
    project.close(old.id, outcome="done again")

    now = {i.id: i.closed_seq for i in project.worklog.items}[old.id]
    assert now > was                     # re-finishing moves it to the top
    assert now > {i.id: i.closed_seq for i in project.worklog.items}[recent.id]


def test_a_non_conflict_git_failure_is_not_called_a_conflict(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)
    worktree = project.folder_of(item) / "wt" / root.name

    from clarity import gitops
    try:
        gitops.merge_into(worktree, "no-such-branch-xyz")
    except ClarityError as exc:
        assert "conflicts" not in str(exc), f"git's own error was relabelled: {exc}"
    else:
        raise AssertionError("merging a missing ref should fail")


# A session once reversed its epoch's scope, tested it and had it reviewed without
# writing a note, because every turn felt mid-task. `status` said nothing. These
# keep the signal that now says so.


def test_a_note_records_the_time_not_just_the_day(tmp_path):
    """"Today" cannot tell an hour-old session from one that ran all day."""
    from datetime import datetime

    root = make_repo(tmp_path)
    project = Project.create(root)
    item = project.add("a thing")
    project.note(item.id, "tried the obvious thing")

    at = Project.find(root).worklog.by_id(item.id).notes[0].at
    datetime.fromisoformat(at)          # parses as a datetime, not just a date
    assert " " in at, f"{at!r} carries no time of day"


def test_a_fresh_note_is_not_nagged_about(tmp_path):
    from clarity import render

    root = make_repo(tmp_path)
    project = Project.create(root)
    item = project.add("a thing", status="active")
    project.note(item.id, "just now")

    assert render.note_age(project.worklog.by_id(item.id)) is None


def test_a_stale_note_on_an_epoch_in_flight_is_surfaced(tmp_path):
    from clarity import render
    from clarity.model import Note

    root = make_repo(tmp_path)
    project = Project.create(root)
    item = project.add("a thing", status="active")
    item.notes.append(Note(at="2020-01-01 09:00", text="ancient"))

    assert "last note" in (render.note_age(item) or "")
    assert f"clarity-ctl note {item.id}" in render.status_text(
        project.worklog.objectives, [item])


def test_only_work_in_flight_is_nagged(tmp_path):
    """An idea nobody has started has nothing to report."""
    from clarity import render
    from clarity.model import Note

    root = make_repo(tmp_path)
    project = Project.create(root)
    item = project.add("someday")
    item.notes.append(Note(at="2020-01-01 09:00", text="ancient"))

    assert render.note_age(item) is None


def test_a_date_only_note_still_counts(tmp_path):
    """Worklogs written before timestamps existed keep working, at day granularity:
    a bare date parses as midnight, so the age is coarse but never wrong by a day."""
    from clarity import render
    from clarity.model import Note

    root = make_repo(tmp_path)
    project = Project.create(root)
    item = project.add("a thing", status="active")
    item.notes.append(Note(at="2020-01-01", text="written before timestamps"))

    assert "last note" in (render.note_age(item) or "")
    render.status_text(project.worklog.objectives, [item])
    assert "`2020-01-01`" in render.epoch_md(item, None)


def test_rename_changes_the_name_and_nothing_it_points_at(tmp_path):
    """Scope shifts; the title should follow. The folder and branch are paths — they stay."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    item, _ = project.start(project.add("cache warmup").id)
    before = project.worklog.by_id(item.id)
    folder, branch = before.folder, before.branch

    project.rename(item.id, "  cache warmup,   and eviction  ")

    after = Project.find(root).worklog.by_id(item.id)
    assert after.name == "cache warmup, and eviction"   # whitespace collapsed
    assert (after.folder, after.branch) == (folder, branch)
    assert after.notes[-1].text == "renamed from: cache warmup"
    assert "cache warmup, and eviction" in (root / folder / "EPOCH.md").read_text()


def test_rename_an_idea_and_the_edge_cases(tmp_path):
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    project = Project.find(root)
    idea = project.add("flaky test")

    project.rename(idea.id, "flaky test on macOS")
    assert Project.find(root).worklog.by_id(idea.id).name == "flaky test on macOS"

    # the same name again changes nothing and leaves no note
    notes = len(Project.find(root).worklog.by_id(idea.id).notes)
    Project.find(root).rename(idea.id, "flaky test on macOS")
    assert len(Project.find(root).worklog.by_id(idea.id).notes) == notes

    with pytest.raises(ClarityError) as err:
        Project.find(root).rename(idea.id, "   ")
    assert err.value.code == 4


def test_an_old_worklog_with_a_now_line_still_loads(tmp_path):
    """`current` was dropped; a worklog that has one loads and loses it on the next write."""
    root = make_repo(tmp_path)
    Project.create(root, name="proj", overall="ship it")
    path = root / "worklog.yaml"
    path.write_text(path.read_text().replace("overall: ship it",
                                             "overall: ship it\n  current: this week"))
    project = Project.find(root)
    assert "NOW" not in project.status_text()
    project.set_objective("ship it well")
    assert "current" not in path.read_text()
