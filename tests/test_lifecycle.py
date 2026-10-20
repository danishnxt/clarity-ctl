"""Smoke tests for the item lifecycle. Run: .venv/bin/python -m pytest -q"""

from datetime import datetime

import pytest

from clarity import ClarityError, Project
from clarity import agents, gitops, lease, render
from clarity.model import Note
from clarity.render import EPOCH_MARK_END


def test_init_creates_layout(repo):
    project = Project.create(repo, name="proj", overall="ship it")

    assert (repo / "worklog.yaml").exists()
    assert (repo / ".clarity" / "config.yaml").exists()
    assert not (repo / "STATUS.md").exists()  # the status view is printed, never written
    for name in ("AGENTS.md", "CLAUDE.md"):  # real files now, carrying our block
        assert not (repo / name).is_symlink()
        assert agents.START in (repo / name).read_text()
    assert not (repo / ".clarity" / "RULES.md").exists()  # the block is the only copy
    assert "EPOCHS/*/wt/" in (repo / ".gitignore").read_text()
    assert project.worklog.items == []


def test_idea_to_done(project, repo, git, commit):
    item = project.add("flaky test", type_="fix")
    assert item.status == "idea" and item.folder is None

    project.start(item.id)  # straight from idea: the folder comes with the start
    started = project.worklog.by_id(item.id)
    assert started.status == "active"
    assert (repo / started.folder).is_dir()
    assert started.branch == f"epoch/{item.id:03d}-flaky-test"
    worktree = repo / started.folder / "wt" / repo.name
    assert worktree.is_dir()
    assert lease.read(repo / started.folder) is not None

    project.note(item.id, "tried a bigger timeout")

    # the end sha is the epoch's own, not the main checkout's HEAD
    commit(worktree, "new.txt", "epoch work")
    branch_tip = git(["rev-parse", "--short", started.branch], repo)
    assert branch_tip != git(["rev-parse", "--short", "HEAD"], repo)

    project.close(item.id, outcome="bumped the timeout")
    closed = project.worklog.by_id(item.id)
    assert closed.status == "done" and closed.outcome == "bumped the timeout"
    assert closed.extra["end_sha"] == branch_tip
    assert not worktree.exists()  # worktree gone
    assert lease.read(repo / closed.folder) is None  # and the lease with it
    assert closed.branch in git(["branch", "--list", closed.branch], repo)  # branch survives


def test_existing_branch_is_symlinked(project, repo):
    item = project.add("bench baseline", type_="experiment")
    project.start(item.id, branch="main")  # main is checked out at the root

    link = repo / project.worklog.by_id(item.id).folder / "wt" / repo.name
    assert link.is_symlink()
    assert link.resolve() == repo.resolve()


def test_human_notes_survive_regeneration(project, repo):
    item, _ = project.start(project.add("write docs").id)

    epoch_md = repo / item.folder / "EPOCH.md"
    epoch_md.write_text(epoch_md.read_text() + "my own scratch notes\n")

    project.note(item.id, "started drafting")
    text = epoch_md.read_text()
    assert "my own scratch notes" in text
    assert "started drafting" in text
    assert text.index("started drafting") < text.index(EPOCH_MARK_END)


def test_errors_carry_exit_codes(project, tmp_path):
    with pytest.raises(ClarityError) as err:
        project.worklog.by_id(99)
    assert err.value.code == 4

    with pytest.raises(ClarityError) as err:
        Project.find(tmp_path)
    assert err.value.code == 3


def test_plans_live_in_the_epoch_and_are_listed_not_cached(project, repo):
    """Long-form docs sit with the work, and are listed when asked for — not cached."""
    item, _ = project.start(project.add("cache warmup").id)

    folder = repo / item.folder
    assert (folder / "PLANS").is_dir()

    (folder / "PLANS" / "approach.md").write_text("# how we'll do it\n")
    project.note(item.id, "ring buffer, 2x slower — PLANS/approach.md")

    # listed at read time, not cached into EPOCH.md: PLANS/ is a directory anyone can
    # drop a file into, so no command can know when it changed
    assert project.query("item", str(item.id))["plans"] == ["approach.md"]
    assert "## Plans" not in (folder / "EPOCH.md").read_text()

    (folder / "PLANS" / "late.md").write_text("# dropped in by hand\n")
    assert project.query("item", str(item.id))["plans"] == ["approach.md", "late.md"]
    assert "late.md" not in (folder / "EPOCH.md").read_text()


def test_reopen_returns_a_closed_epoch_to_active(project, repo, commit):
    """Reopening keeps the old outcome in the trail instead of overwriting it."""
    item, _ = project.start(project.add("cache warmup").id)
    project.close(item.id, outcome="2x slower, dropped")

    with pytest.raises(ClarityError) as err:
        project.start(item.id)  # a closed epoch must not restart silently
    assert err.value.code == 4 and "reopen" in str(err.value)

    commit(repo, "later.txt", "later")  # main moves on while the epoch is closed

    _, warnings = project.start(item.id, reopen=True)
    reopened = project.worklog.by_id(item.id)
    assert reopened.status == "active"
    assert reopened.outcome is None and reopened.ended is None
    assert "previous outcome: 2x slower, dropped" in reopened.notes[-1].text
    assert (repo / reopened.folder / "wt" / repo.name).exists()  # worktree back
    assert any("behind main" in w for w in warnings), warnings


def test_refresh_catches_the_branch_up_without_losing_commits(project, repo, commit):
    item, _ = project.start(project.add("cache warmup").id)

    # the epoch commits something of its own, then main moves on underneath it
    worktree = project.folder_of(item) / "wt" / repo.name
    commit(worktree, "epoch.txt", "epoch work")
    commit(repo, "later.txt", "later")

    # uncommitted work refuses: a merge could tangle with it
    (worktree / "scratch.txt").write_text("uncommitted\n")
    with pytest.raises(ClarityError) as err:
        project.refresh(item.id)
    assert err.value.code == 4 and "commit or stash" in str(err.value)
    (worktree / "scratch.txt").unlink()

    _, report = project.refresh(item.id)
    assert report["merged"] == [{"repo": ".", "base": "main", "commits": 1}], report
    assert (worktree / "later.txt").exists()       # main's commit arrived
    assert (worktree / "epoch.txt").exists()       # the epoch's own work survived
    assert project.refresh(item.id)[1] == {"merged": [],
                                           "up_to_date": [{"repo": ".", "base": "main"}]}


def test_refresh_follows_the_base_recorded_at_start(repo, git, commit):
    """Cut from dev, the epoch keeps following dev after the checkout moves on."""
    git(["checkout", "-qb", "dev"], repo)  # the work lives on a long-running branch
    Project.create(repo, name="proj")
    project = Project.find(repo)
    item, _ = project.start(project.add("cache warmup").id)
    assert item.bases == {".": "dev"}
    worktree = project.folder_of(item) / "wt" / repo.name

    commit(repo, "later.txt", "later")
    # someone switches the checkout for unrelated work, which moves on too
    git(["checkout", "-qb", "feature-x"], repo)
    commit(repo, "unrelated.txt", "unrelated")

    notes = " ".join(project.stale_map()[item.id])
    assert "1 behind dev" in notes and "checkout is on feature-x" in notes
    _, report = project.refresh(item.id)
    assert [m["base"] for m in report["merged"]] == ["dev"], report
    assert (worktree / "later.txt").exists()
    assert not (worktree / "unrelated.txt").exists()

    # changing the base is deliberate, and recorded
    _, report = Project.find(repo).refresh(item.id, base="feature-x")
    assert report["merged"][0]["base"] == "feature-x" and (worktree / "unrelated.txt").exists()
    after = Project.find(repo).worklog.by_id(item.id)
    assert after.bases == {".": "feature-x"} and "base set to feature-x" in after.notes[-1].text
    with pytest.raises(ClarityError):
        Project.find(repo).refresh(item.id, base="no-such-branch")


def test_closed_seq_orders_closes_and_a_reclose_goes_to_the_top(project):
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
    closed = project.status_text(show_all=True).split("Closed")[1]
    assert closed.index("first") < closed.index("second"), closed

    # re-finishing the older one takes a fresh seq, past everything else
    was = project.worklog.by_id(second.id).closed_seq
    project.start(second.id, reopen=True)
    project.close(second.id, outcome="b again")
    now = project.worklog.by_id(second.id).closed_seq
    assert now > was and now > project.worklog.by_id(first.id).closed_seq


def test_a_non_conflict_git_failure_is_not_called_a_conflict(project, repo):
    item, _ = project.start(project.add("cache warmup").id)
    worktree = project.folder_of(item) / "wt" / repo.name

    with pytest.raises(ClarityError) as err:  # merging a missing ref should fail
        gitops.merge_into(worktree, "no-such-branch-xyz")
    assert "conflicts" not in str(err.value), f"git's own error was relabelled: {err.value}"


# A session once reversed its epoch's scope, tested it and had it reviewed without
# writing a note, because every turn felt mid-task. `status` said nothing. This
# keeps the signal that now says so.


def test_a_stale_note_on_an_epoch_in_flight_is_surfaced(project):
    # "today" cannot tell an hour-old session from one that ran all day
    item = project.add("a thing", status="active")
    project.note(item.id, "just now")
    at = Project.find(project.root).worklog.by_id(item.id).notes[0].at
    datetime.fromisoformat(at)          # parses as a datetime, not just a date
    assert " " in at, f"{at!r} carries no time of day"
    assert render.note_age(project.worklog.by_id(item.id)) is None  # fresh: no nag

    # (status, last note, nagged?) — an idea nobody has started has nothing to report;
    # a bare date from before timestamps parses as midnight, coarse but never wrong
    for status, at, nagged in (("active", "2020-01-01 09:00", True),
                               ("idea", "2020-01-01 09:00", False),
                               ("active", "2020-01-01", True)):
        item = project.add(f"{status} {at}", status=status)
        item.notes.append(Note(at=at, text="ancient"))
        assert bool("last note" in (render.note_age(item) or "")) == nagged, (status, at)
        if nagged:
            assert f"clarity-ctl note {item.id}" in render.status_text(
                project.worklog.objectives, [item])

    assert "`2020-01-01`" in render.epoch_md(item, None)


def test_rename_changes_the_name_and_nothing_it_points_at(project, repo):
    """Scope shifts; the title should follow. The folder and branch are paths — they stay."""
    item, _ = project.start(project.add("cache warmup").id)
    before = project.worklog.by_id(item.id)
    folder, branch = before.folder, before.branch

    project.rename(item.id, "  cache warmup,   and eviction  ")

    after = Project.find(repo).worklog.by_id(item.id)
    assert after.name == "cache warmup, and eviction"   # whitespace collapsed
    assert (after.folder, after.branch) == (folder, branch)
    assert after.notes[-1].text == "renamed from: cache warmup"
    assert "cache warmup, and eviction" in (repo / folder / "EPOCH.md").read_text()

    # an idea renames too; the same name again changes nothing and leaves no note
    idea = Project.find(repo).add("flaky test")
    Project.find(repo).rename(idea.id, "flaky test on macOS")
    assert Project.find(repo).worklog.by_id(idea.id).name == "flaky test on macOS"
    notes = len(Project.find(repo).worklog.by_id(idea.id).notes)
    Project.find(repo).rename(idea.id, "flaky test on macOS")
    assert len(Project.find(repo).worklog.by_id(idea.id).notes) == notes

    with pytest.raises(ClarityError) as err:
        Project.find(repo).rename(idea.id, "   ")
    assert err.value.code == 4


def test_an_old_worklog_with_a_now_line_still_loads(repo):
    """`current` was dropped; a worklog that has one loads and loses it on the next write."""
    Project.create(repo, name="proj", overall="ship it")
    path = repo / "worklog.yaml"
    path.write_text(path.read_text().replace("overall: ship it",
                                             "overall: ship it\n  current: this week"))
    project = Project.find(repo)
    assert "NOW" not in project.status_text()
    project.set_objective("ship it well")
    assert "current" not in path.read_text()


def test_landed_sees_plain_and_squash_merges_and_says_when_it_cannot_tell(repo, git, commit):
    git(["checkout", "-qb", "feature"], repo)
    commit(repo, "a.txt", "a")
    commit(repo, "b.txt", "b")
    tip = git(["rev-parse", "feature"], repo)
    git(["checkout", "-q", "main"], repo)
    assert gitops.landed(repo, tip, "main") is False

    # a squash merge: none of feature's commits reach main, only their changes do
    git(["merge", "-q", "--squash", "feature"], repo)
    git(["commit", "-qm", "squashed"], repo)
    assert tip not in git(["log", "--format=%H", "main"], repo)  # really not an ancestor
    assert gitops.landed(repo, tip, "main") is True
    commit(repo, "later.txt", "main moves on")  # and stays landed after it does
    assert gitops.landed(repo, tip, "main") is True

    assert gitops.landed(repo, "0" * 40, "main") is None       # a sha git doesn't have
    assert gitops.landed(repo, tip, "no-such-base") is None


def test_status_marks_what_landed_and_reverse_reads_oldest_first(project, repo, git, commit):
    shipped = project.add("shipped")
    kept_off = project.add("kept off main")
    gave_up = project.add("gave up")
    pending = project.add("still going")
    for item in (shipped, kept_off, gave_up, pending):
        project.start(item.id)
    worktree = {i.id: repo / project.worklog.by_id(i.id).folder / "wt" / repo.name
                for i in (shipped, kept_off, gave_up, pending)}

    commit(worktree[shipped.id], "s.txt")
    commit(worktree[kept_off.id], "k.txt")
    commit(worktree[gave_up.id], "g.txt")
    git(["merge", "-q", "--squash", project.worklog.by_id(shipped.id).branch], repo)
    git(["commit", "-qm", "ship it"], repo)
    project.close(shipped.id, outcome="in")
    project.close(kept_off.id, outcome="tried, not merging")
    project.close(gave_up.id, outcome="nope", dropped=True)

    landed = project.landed_map()
    assert landed[shipped.id] == {".": "merged"}
    assert landed[kept_off.id] == {".": "unmerged"}
    assert gave_up.id not in landed   # a drop is its own verdict
    assert pending.id not in landed   # nothing committed, nothing to land

    text = project.status_text(show_all=True)
    assert "[merged] outcome: in" in text and "[not merged] outcome: tried" in text
    closed = text.split("Closed")[1].split("Dropped")[0]
    assert closed.index("kept off") < closed.index("shipped")         # newest first
    closed = project.status_text(show_all=True, reverse=True).split("Closed")[1]
    assert closed.index("shipped") < closed.index("kept off")         # oldest first

    # in flight and already in its base: that is the one case worth saying
    commit(worktree[pending.id], "p.txt")
    assert "epoch close" not in project.status_text()
    git(["merge", "-q", "--squash", project.worklog.by_id(pending.id).branch], repo)
    git(["commit", "-qm", "land pending"], repo)
    assert f"clarity-ctl epoch close {pending.id}" in project.status_text()


def test_an_unknown_landing_is_data_not_a_mark():
    assert render._landed({".": "unknown"}) is None
    assert render._landed({"a": "merged", "b": "unknown"}) == "merged"
    assert render._landed({"a": "merged", "b": "unmerged"}) == "a: merged, b: not merged"
