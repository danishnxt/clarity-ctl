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
    item = project.add("try it", status="planned")
    project.start(item.id)
    monkeypatch.chdir(root)

    assert main(["epoch", "close", str(item.id), "--drop", "not worth it"]) == 0
    assert Project.find(root).worklog.by_id(item.id).status == "dropped"
