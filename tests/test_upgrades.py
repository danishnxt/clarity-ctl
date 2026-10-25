"""A newer clarity-ctl meeting an older project, and the other way round.
Run: .venv/bin/python -m pytest -q
"""

import json
from pathlib import Path

import pytest
import yaml

from clarity import ClarityError, Project, agents
from clarity.cli import main
from clarity.store import WORKLOG_VERSION


def _rewrite(root: Path, change) -> None:
    path = root / "worklog.yaml"
    raw = yaml.safe_load(path.read_text())
    change(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False))


def _raw(root: Path) -> dict:
    return yaml.safe_load((root / "worklog.yaml").read_text())


def test_a_version_1_worklog_reads_migrated_and_saves_on_the_next_write(project, repo):
    gave_up = project.add("gave up on it")
    old = project.add("old")
    waiting = project.add("waiting on it")

    def to_v1(raw):
        raw["version"] = 1
        by_id = {entry["id"]: entry for entry in raw["items"]}
        by_id[gave_up.id]["status"] = "abandoned"
        by_id[old.id]["status"] = "abandoned"
        by_id[waiting.id].update(status="blocked", blocked_reason="upstream fix",
                                 started="2026-01-01")
    _rewrite(repo, to_v1)

    # abandoned reads as dropped; blocked as active, its reason kept as a note
    worklog = Project.find(repo).worklog
    assert worklog.by_id(gave_up.id).status == "dropped"
    item = worklog.by_id(waiting.id)
    assert item.status == "active" and "blocked_reason" not in item.extra
    assert item.notes[-1].text == "was blocked: upstream fix"
    assert _raw(repo)["version"] == 1            # reading alone changes nothing on disk

    Project.find(repo).add("next")              # the next write saves it migrated
    raw = _raw(repo)
    assert raw["version"] == WORKLOG_VERSION
    assert raw["items"][0]["status"] == "dropped"

    # a worklog without a version is version 1
    _rewrite(repo, lambda raw: (raw.pop("version"),
                                raw["items"][1].update(status="abandoned")))
    assert Project.find(repo).worklog.by_id(old.id).status == "dropped"


def test_a_newer_worklog_reads_but_refuses_writes(project, repo, monkeypatch, capsys):
    project.add("from the future", status="idea")
    project.add("put away")

    # whatever the newer version added is not this version's to judge
    def future(raw):
        raw["version"] = WORKLOG_VERSION + 1
        raw["items"][1]["status"] = "some-later-status"
    _rewrite(repo, future)
    before = (repo / "worklog.yaml").read_text()

    project = Project.find(repo)
    assert project.worklog.newer == WORKLOG_VERSION + 1
    assert "from the future" in project.status_text()
    with pytest.raises(ClarityError) as err:
        project.add("anything")
    assert err.value.code == 4 and "upgrade" in str(err.value)
    assert (repo / "worklog.yaml").read_text() == before

    # the CLI warns on reads and refuses writes
    monkeypatch.chdir(repo)
    assert main(["show", "all", "--json"]) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert warnings and "newer clarity-ctl" in warnings[0]
    assert main(["idea", "add", "x"]) == 4


def test_an_unknown_status_in_a_current_worklog_is_named(project, repo):
    """Silently it would match no view, and the item would vanish from every list."""
    project.add("typo")
    _rewrite(repo, lambda raw: raw["items"][0].update(status="activ"))

    with pytest.raises(ClarityError) as err:
        Project.find(repo)
    assert err.value.code == 2 and "'activ'" in str(err.value)


def test_a_write_refreshes_a_stale_agent_block_and_leaves_a_removed_one(project, repo):
    """The first write after an upgrade brings the project's instructions along."""
    path = repo / "AGENTS.md"
    text = path.read_text()
    start, end = text.index(agents.START), text.index(agents.END) + len(agents.END)
    path.write_text(text[:start] + f"{agents.START}\nclarity-ctl q active\n{agents.END}"
                    + text[end:])

    project.add("anything")
    assert "clarity-ctl q " not in path.read_text()
    assert agents.block_for(path, project.state_digest()) in path.read_text()

    # but a block the user removed stays removed
    project.install_agents(remove=True)
    project.add("anything else")
    for path in agents.local_paths(repo):
        assert not path.exists() or agents.START not in path.read_text()


# The JSON envelope: a failure has every field a success has but `data`.


def test_a_refusal_answers_in_the_success_envelope_shape(project, repo, monkeypatch,
                                                         capsys):
    monkeypatch.chdir(repo)

    assert main(["status", "--json"]) == 0
    ok = json.loads(capsys.readouterr().out)
    assert main(["epoch", "close", "99", "x", "--json"]) == 4
    failed = json.loads(capsys.readouterr().out)

    assert set(ok) - {"data"} <= set(failed)
    assert failed["ok"] is False and failed["command"] == "epoch.close"
    assert failed["code"] == 4 and "99" in failed["error"]


def test_a_typo_with_json_gets_an_envelope_not_usage_text(project, repo, monkeypatch,
                                                          capsys):
    monkeypatch.chdir(repo)

    with pytest.raises(SystemExit) as stop:
        main(["show", "all", "--json", "--bogus"])
    assert stop.value.code == 2
    failed = json.loads(capsys.readouterr().out)
    assert failed["ok"] is False and failed["code"] == 2 and failed["command"] == "show"
    assert "--bogus" in failed["error"]


# `planned` is gone: --no-repos is a folder without a branch now.


def test_a_version_1_planned_item_reads_as_an_idea_that_keeps_its_folder(workspace,
                                                                         ws_root):
    root = ws_root
    item = workspace.add("was planned")
    folder = workspace.start(item.id, no_repos=True)[0].folder

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


def test_no_repos_starts_a_folder_and_add_repo_brings_code_in_later(workspace, ws_root):
    root = ws_root
    item, _ = workspace.start(workspace.add("plan the rewrite").id, no_repos=True)

    assert item.status == "active" and item.branch is None and item.repos == []
    assert (root / item.folder).is_dir()
    assert not (root / item.folder / "wt").exists() or not any((root / item.folder / "wt").iterdir())

    item, added, _ = Project.find(root).add_repos(item.id, ["agent"])
    assert added == ["workspace/agent"] and item.branch
    assert (root / item.folder / "wt" / "agent").is_dir()
    assert not (root / item.folder / "wt" / "harness").exists()

    # one with no repos at all closes cleanly
    analysis, _ = Project.find(root).start(Project.find(root).add("just analysis").id,
                                           no_repos=True)
    assert Project.find(root).close(analysis.id, "wrote it up").status == "done"


def test_no_repos_with_repo_or_branch_is_an_argument_mistake(workspace, ws_root,
                                                             monkeypatch):
    item = workspace.add("x")
    monkeypatch.chdir(ws_root)

    with pytest.raises(SystemExit) as stop:
        main(["epoch", "start", str(item.id), "--no-repos", "--repo", "agent"])
    assert stop.value.code == 2
    assert main(["epoch", "start", str(item.id), "--no-repos", "--branch", "b"]) == 2


# close never merges; it says when the work has not landed.


def test_close_warns_when_the_branch_is_not_merged(workspace, ws_root, commit,
                                                   monkeypatch, capsys):
    item, _ = workspace.start(workspace.add("x").id, repos=["agent"])
    commit(ws_root / item.folder / "wt" / "agent", "new.txt")
    monkeypatch.chdir(ws_root)

    assert main(["epoch", "close", str(item.id), "shipped", "--json"]) == 0
    warnings = json.loads(capsys.readouterr().out)["warnings"]
    assert len(warnings) == 1 and "1 commit not in main" in warnings[0]


def test_close_is_quiet_once_merged_and_for_a_drop(workspace, ws_root, monkeypatch, capsys):
    merged, _ = workspace.start(workspace.add("nothing new").id, repos=["agent"])
    dropped, _ = workspace.start(workspace.add("gave up").id, repos=["agent"])
    monkeypatch.chdir(ws_root)

    assert main(["epoch", "close", str(merged.id), "done", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []
    assert main(["epoch", "close", str(dropped.id), "--drop", "no", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["warnings"] == []
    assert Project.find(ws_root).worklog.by_id(dropped.id).status == "dropped"
