"""--agent: every read as plain text in the state block's style. No box lines, no
colour, no padding; --json stays the format for scripts and the two never mix.
Run: uv run -q --with pytest pytest -q tests/test_agent_output.py"""

import json

import pytest

from clarity import cli, render

BOX = set("│─┌┐└┘├┤┬┴┼")


@pytest.fixture
def worked(workspace, ws_root, commit, monkeypatch):
    """Two closed (one dropped), one active with a handoff and a commit, one idea."""
    done, _ = workspace.start(workspace.add("ring buffer for the tokenizer").id, repos=["agent"])
    workspace.close(done.id, "1.6x faster on the 1GB input")
    gone, _ = workspace.start(workspace.add("memory-map the input").id, repos=["agent"])
    workspace.close(gone.id, "no gain, I/O is not the bottleneck", dropped=True)
    live, _ = workspace.start(workspace.add("parallel chunk parsing").id, repos=["agent"],
                              brief="cut load time")
    commit(ws_root / live.folder / "wt" / "agent", "x.txt")
    workspace.note(live.id, "first note\nover two lines")
    workspace.note(live.id, "HANDOFF: lexer done")
    idea = workspace.add("flaky test on macOS")
    monkeypatch.chdir(ws_root)
    return {"done": done.id, "dropped": gone.id, "live": live.id, "idea": idea.id}


def agent(capsys, *argv) -> str:
    assert cli.main([*argv, "--agent"]) == 0
    out = capsys.readouterr().out
    assert not BOX & set(out) and "\x1b" not in out
    assert out.endswith("\n") and not out.endswith("\n\n")   # print's newline, no blank line
    return out[:-1]


def test_status_agent_is_the_blocks_sections_as_plain_lines(worked, capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")   # --agent never paints, whatever the terminal
    out = agent(capsys, "status")
    live = worked["live"]
    assert out.startswith("Objective: ")
    assert f"Active (1)\n- #{live} parallel chunk parsing — EPOCHS/{live:03d}_" in out
    assert "✓ its work is in its base" not in out    # unmerged: nothing to say
    assert f"Up next (1)\n- #{worked['idea']} flaky test on macOS" in out
    assert out.rstrip().endswith("2 closed or dropped: `clarity-ctl show closed --agent`")
    assert "ring buffer" not in out                  # closed work is one command away


def test_status_agent_all_lists_the_closed_index_cut_by_limit(worked, capsys):
    out = agent(capsys, "status", "--all", "--limit", "1")
    assert f"Closed (2), newest first\n#{worked['dropped']} ✗ memory-map the input · " \
           "1 older: `clarity-ctl show closed --agent`" in out


def test_show_closed_agent_is_every_closed_item_newest_first_with_marks(worked, capsys):
    out = agent(capsys, "show", "closed")
    assert out == (f"Closed (2), newest first\n#{worked['dropped']} ✗ memory-map the input"
                   f" · #{worked['done']} ✓ ring buffer for the tokenizer")


def test_show_closed_agent_is_not_cut_by_count_and_cuts_names_like_the_block(
        project, capsys, monkeypatch):
    monkeypatch.chdir(project.root)
    for n in range(30):
        project.close(project.add(f"item {n} " + "long " * 30).id, "done")
    out = agent(capsys, "show", "closed").splitlines()
    entries = out[1].split(" · ")
    assert out[0] == "Closed (30), newest first" and len(entries) == 30
    assert all(len(e.split(" ", 2)[2]) <= render.DIGEST_CLOSED_NAME for e in entries)


def test_show_active_and_next_agent(worked, capsys):
    assert agent(capsys, "show", "active").startswith("Active (1)\n- #")
    assert agent(capsys, "show", "next") == (
        f"Up next (1)\n- #{worked['idea']} flaky test on macOS")


def test_show_item_agent_has_every_note_in_full_numbered(worked, capsys):
    out = agent(capsys, "show", str(worked["live"]))
    lines = out.splitlines()
    assert lines[0] == f"#{worked['live']} parallel chunk parsing"
    assert lines[1].startswith("status: active · type: feature · created ")
    assert "brief: cut load time" in lines
    assert any(line.startswith("repo: workspace/agent — base main") for line in lines)
    assert "Notes (2)" in lines
    assert "first note\nover two lines" in out       # as written, not re-wrapped
    assert any(line.startswith("2. [") and line.endswith("] HANDOFF: lexer done")
               for line in lines)


def test_show_item_agent_says_the_outcome_and_whether_it_landed(worked, capsys):
    out = agent(capsys, "show", str(worked["done"]))
    assert "status: done" in out and "outcome: 1.6x faster on the 1GB input" in out


def test_search_agent_is_plain_even_when_colour_is_forced(worked, capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    out = agent(capsys, "search", "tokenizer", "bottleneck")
    assert f"#{worked['dropped']} dropped memory-map the input" in out
    assert "  outcome: " in out


def test_agent_and_json_together_are_a_validation_error(worked, capsys):
    for argv in (["status"], ["show", "closed"], ["show", "1"], ["search", "x"]):
        with pytest.raises(SystemExit) as stop:   # as a typo under --json does
            cli.main([*argv, "--agent", "--json"])
        assert stop.value.code == 2
        err = json.loads(capsys.readouterr().out)
        assert err["ok"] is False and err["code"] == 2
        assert "--agent and --json" in err["error"]


def test_human_text_is_unchanged_by_the_flag_existing(worked, capsys):
    assert cli.main(["status"]) == 0
    out = capsys.readouterr().out
    assert BOX & set(out) and "closed or dropped — clarity-ctl status --all" in out


def test_the_rules_send_agents_to_agent_for_reads():
    from clarity import agents
    for needed in ("`--agent`", "show closed --agent", "search <words> --agent", "--json` is for scripts"):
        assert needed in agents.LOCAL_BLOCK


def test_show_closed_agent_includes_archived_items_so_the_blocks_pointer_is_true(
        worked, workspace, capsys):
    workspace.archive()                      # both closed items leave the live worklog
    assert not [i for i in workspace.worklog.items if i.status in ("done", "dropped")]
    assert "Closed (2), newest first" in agent(capsys, "show", "closed")
    assert "2 closed or dropped: `clarity-ctl show closed --agent`" in agent(capsys, "status")
