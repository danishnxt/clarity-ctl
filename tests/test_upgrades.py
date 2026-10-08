"""A newer clarity-ctl meeting an older project, and the other way round.
Run: .venv/bin/python -m pytest -q
"""

import json
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from clarity import ClarityError, Project, agents  # noqa: E402
from clarity.cli import main  # noqa: E402
from clarity.store import WORKLOG_VERSION  # noqa: E402

from test_lifecycle import make_repo  # noqa: E402


def _project(tmp_path) -> Path:
    root = make_repo(tmp_path)
    Project.create(root, name="proj")
    return root


def _rewrite(root: Path, change) -> None:
    path = root / "worklog.yaml"
    raw = yaml.safe_load(path.read_text())
    change(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _raw(root: Path) -> dict:
    return yaml.safe_load((root / "worklog.yaml").read_text())


def test_a_version_1_worklog_reads_abandoned_as_dropped(tmp_path):
    root = _project(tmp_path)
    project = Project.find(root)
    item = project.add("gave up on it")

    def to_v1(raw):
        raw["version"] = 1
        raw["items"][0]["status"] = "abandoned"
    _rewrite(root, to_v1)

    assert Project.find(root).worklog.by_id(item.id).status == "dropped"
    assert _raw(root)["version"] == 1            # reading alone changes nothing on disk

    Project.find(root).add("next")              # the next write saves it migrated
    raw = _raw(root)
    assert raw["version"] == WORKLOG_VERSION
    assert raw["items"][0]["status"] == "dropped"


def test_a_worklog_without_a_version_is_version_1(tmp_path):
    root = _project(tmp_path)
    Project.find(root).add("old")

    def unversioned(raw):
        del raw["version"]
        raw["items"][0]["status"] = "abandoned"
    _rewrite(root, unversioned)

    assert Project.find(root).worklog.items[0].status == "dropped"


def test_a_newer_worklog_reads_but_refuses_writes(tmp_path):
    root = _project(tmp_path)
    Project.find(root).add("from the future", status="idea")
    _rewrite(root, lambda raw: raw.update(version=WORKLOG_VERSION + 1))
    before = (root / "worklog.yaml").read_text()

    project = Project.find(root)
    assert "from the future" in project.status_text()
    with pytest.raises(ClarityError) as err:
        project.add("anything")
    assert err.value.code == 4 and "upgrade" in str(err.value)
    assert (root / "worklog.yaml").read_text() == before


def test_a_newer_worklog_does_not_trip_on_statuses_it_does_not_know(tmp_path):
    """Whatever the newer version added is not this version's to judge."""
    root = _project(tmp_path)
    Project.find(root).add("put away")

    def future(raw):
        raw["version"] = WORKLOG_VERSION + 1
        raw["items"][0]["status"] = "some-later-status"
    _rewrite(root, future)

    assert Project.find(root).worklog.newer == WORKLOG_VERSION + 1


def test_the_cli_warns_on_reads_and_refuses_writes(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    _rewrite(root, lambda raw: raw.update(version=WORKLOG_VERSION + 1))
    monkeypatch.chdir(root)

    assert main(["show", "all", "--json"]) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert warnings and "newer clarity-ctl" in warnings[0]

    assert main(["idea", "add", "x"]) == 4


def test_an_unknown_status_in_a_current_worklog_is_named(tmp_path):
    """Silently it would match no view, and the item would vanish from every list."""
    root = _project(tmp_path)
    Project.find(root).add("typo")
    _rewrite(root, lambda raw: raw["items"][0].update(status="activ"))

    with pytest.raises(ClarityError) as err:
        Project.find(root)
    assert err.value.code == 2 and "'activ'" in str(err.value)


def test_a_write_refreshes_a_stale_agent_block(tmp_path):
    """The first write after an upgrade brings the project's instructions along."""
    root = _project(tmp_path)
    path = root / "AGENTS.md"
    text = path.read_text()
    start, end = text.index(agents.START), text.index(agents.END) + len(agents.END)
    path.write_text(text[:start] + f"{agents.START}\nclarity-ctl q active\n{agents.END}"
                    + text[end:])

    Project.find(root).add("anything")
    assert "clarity-ctl q " not in path.read_text()
    assert agents.BLOCK in path.read_text()


def test_a_write_leaves_a_removed_block_removed(tmp_path):
    root = _project(tmp_path)
    project = Project.find(root)
    project.install_agents(remove=True)

    project.add("anything")
    for path in agents.local_paths(root):
        assert not path.exists() or agents.START not in path.read_text()


def test_close_drop_records_dropped(tmp_path, monkeypatch):
    root = _project(tmp_path)
    project = Project.find(root)
    item = project.add("try it")
    project.start(item.id)
    monkeypatch.chdir(root)

    assert main(["epoch", "close", str(item.id), "--drop", "not worth it"]) == 0
    assert Project.find(root).worklog.by_id(item.id).status == "dropped"


# The JSON envelope: a failure has every field a success has but `data`.


def test_a_refusal_answers_in_the_success_envelope_shape(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    monkeypatch.chdir(root)

    assert main(["status", "--json"]) == 0
    ok = json.loads(capsys.readouterr().out)
    assert main(["epoch", "close", "99", "x", "--json"]) == 4
    failed = json.loads(capsys.readouterr().out)

    assert set(ok) - {"data"} <= set(failed)
    assert failed["ok"] is False and failed["command"] == "epoch.close"
    assert failed["code"] == 4 and "99" in failed["error"]


def test_a_typo_with_json_gets_an_envelope_not_usage_text(tmp_path, monkeypatch, capsys):
    root = _project(tmp_path)
    monkeypatch.chdir(root)

    with pytest.raises(SystemExit) as stop:
        main(["show", "all", "--json", "--bogus"])
    assert stop.value.code == 2
    failed = json.loads(capsys.readouterr().out)
    assert failed["ok"] is False and failed["code"] == 2 and failed["command"] == "show"
    assert "--bogus" in failed["error"]


# `planned` is gone: --no-repos is a folder without a branch now.


def test_a_version_1_planned_item_reads_as_an_idea_that_keeps_its_folder(tmp_path):
    root, project = _workspace(tmp_path)
    item = project.add("was planned")
    folder = project.start(item.id, no_repos=True)[0].folder

    def to_v1_planned(raw):
        raw["version"] = 1
        entry = raw["items"][0]
        entry["status"] = "planned"
        for key in ("started", "repos"):
            entry.pop(key, None)
    _rewrite(root, to_v1_planned)
    (root / folder / ".lease").unlink(missing_ok=True)

    project = Project.find(root)
    assert project.worklog.by_id(item.id).status == "idea"
    started, _ = project.start(item.id)
    assert started.folder == folder                # the planned folder, picked back up


def _workspace(tmp_path) -> tuple[Path, Project]:
    from test_repos import make_workspace
    root = make_workspace(tmp_path)
    project = Project.find(root)
    for name in ("agent", "harness"):
        project.repo_add(str(root / "workspace" / name))
    return root, project


def test_no_repos_starts_a_folder_and_add_repo_brings_code_in_later(tmp_path):
    root, project = _workspace(tmp_path)
    item, _ = project.start(project.add("plan the rewrite").id, no_repos=True)

    assert item.status == "active" and item.branch is None and item.repos == []
    assert (root / item.folder).is_dir()
    assert not (root / item.folder / "wt").exists() or not any((root / item.folder / "wt").iterdir())

    item, added, _ = Project.find(root).add_repos(item.id, ["agent"])
    assert added == ["workspace/agent"] and item.branch
    assert (root / item.folder / "wt" / "agent").is_dir()
    assert not (root / item.folder / "wt" / "harness").exists()


def test_no_repos_closes_cleanly(tmp_path):
    root, project = _workspace(tmp_path)
    item, _ = project.start(project.add("just analysis").id, no_repos=True)
    assert Project.find(root).close(item.id, "wrote it up").status == "done"


def test_no_repos_with_repo_or_branch_is_an_argument_mistake(tmp_path, monkeypatch):
    root, project = _workspace(tmp_path)
    item = project.add("x")
    monkeypatch.chdir(root)

    with pytest.raises(SystemExit) as stop:
        main(["epoch", "start", str(item.id), "--no-repos", "--repo", "agent"])
    assert stop.value.code == 2
    assert main(["epoch", "start", str(item.id), "--no-repos", "--branch", "b"]) == 2


def test_a_version_1_blocked_epoch_reads_as_active_with_its_reason_noted(tmp_path):
    root = _project(tmp_path)
    Project.find(root).add("waiting on it")

    def to_v1_blocked(raw):
        raw["version"] = 1
        raw["items"][0].update(status="blocked", blocked_reason="upstream fix", started="2026-01-01")
    _rewrite(root, to_v1_blocked)

    item = Project.find(root).worklog.items[0]
    assert item.status == "active" and "blocked_reason" not in item.extra
    assert item.notes[-1].text == "was blocked: upstream fix"


# close never merges; it says when the work has not landed.


def test_close_warns_when_the_branch_is_not_merged(tmp_path, monkeypatch, capsys):
    from test_lifecycle import git
    root, project = _workspace(tmp_path)
    item, _ = project.start(project.add("x").id, repos=["agent"])
    worktree = root / item.folder / "wt" / "agent"
    (worktree / "new.txt").write_text("work\n")
    git(["add", "-A"], worktree)
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "work"], worktree)
    monkeypatch.chdir(root)

    assert main(["epoch", "close", str(item.id), "shipped", "--json"]) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert len(warnings) == 1 and "1 commit not in main" in warnings[0]


def test_close_is_quiet_once_merged_and_for_a_drop(tmp_path, monkeypatch, capsys):
    root, project = _workspace(tmp_path)
    merged, _ = project.start(project.add("nothing new").id, repos=["agent"])
    dropped, _ = project.start(project.add("gave up").id, repos=["agent"])
    monkeypatch.chdir(root)

    assert main(["epoch", "close", str(merged.id), "done", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []
    assert main(["epoch", "close", str(dropped.id), "--drop", "no", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []
