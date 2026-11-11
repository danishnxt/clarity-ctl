"""Where stdout is not a terminal, every read prints plain text in the state block's style:
no box lines, no colour, no padding. --json stays the format for scripts.
Run: uv run -q --with pytest pytest -q tests/test_agent_output.py"""

import io
import sys

import pytest

from clarity import Project, cli, render

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
    """What an agent sees: stdout is captured, so not a terminal."""
    assert cli.main([*argv]) == 0
    out = capsys.readouterr().out
    assert not BOX & set(out) and "\x1b" not in out
    assert out.endswith("\n") and not out.endswith("\n\n")   # print's newline, no blank line
    return out[:-1]


def test_status_piped_is_the_blocks_sections_as_plain_lines(worked, capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")   # piped output never paints, whatever FORCE_COLOR says
    out = agent(capsys, "status")
    live = worked["live"]
    assert out.startswith("Objective: ")
    assert f"Active (1)\n- #{live} parallel chunk parsing — EPOCHS/{live:03d}_" in out
    assert "✓ its work is in its base" not in out    # unmerged: nothing to say
    assert f"Up next (1)\n- #{worked['idea']} flaky test on macOS" in out
    assert out.rstrip().endswith("2 closed or dropped: `clarity-ctl show closed`")
    assert "ring buffer" not in out                  # closed work is one command away


def test_status_piped_all_lists_the_closed_index_cut_by_limit(worked, capsys):
    out = agent(capsys, "status", "--all", "--limit", "1")
    assert f"Closed (2), newest first\n#{worked['dropped']} ✗ memory-map the input · " \
           "1 older: `clarity-ctl show closed`" in out


def test_show_closed_piped_is_every_closed_item_newest_first_with_marks(worked, capsys):
    out = agent(capsys, "show", "closed")
    assert out == (f"Closed (2), newest first\n#{worked['dropped']} ✗ memory-map the input"
                   f" · #{worked['done']} ✓ ring buffer for the tokenizer")


def test_show_closed_piped_is_not_cut_by_count_and_cuts_names_like_the_block(
        project, capsys, monkeypatch):
    monkeypatch.chdir(project.root)
    for n in range(30):
        project.close(project.add(f"item {n} " + "long " * 30).id, "done")
    out = agent(capsys, "show", "closed").splitlines()
    entries = out[1].split(" · ")
    assert out[0] == "Closed (30), newest first" and len(entries) == 30
    assert all(len(e.split(" ", 2)[2]) <= render.DIGEST_CLOSED_NAME for e in entries)


def test_show_active_and_next_piped(worked, capsys):
    assert agent(capsys, "show", "active").startswith("Active (1)\n- #")
    assert agent(capsys, "show", "next") == (
        f"Up next (1)\n- #{worked['idea']} flaky test on macOS")


def test_show_item_piped_has_every_note_in_full_numbered(worked, capsys):
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


def test_show_item_piped_says_the_outcome_and_whether_it_landed(worked, capsys):
    out = agent(capsys, "show", str(worked["done"]))
    assert "status: done" in out and "outcome: 1.6x faster on the 1GB input" in out


def test_search_piped_is_plain_even_when_colour_is_forced(worked, capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    out = agent(capsys, "search", "tokenizer", "bottleneck")
    assert f"#{worked['dropped']} dropped memory-map the input" in out
    assert "  outcome: " in out


def test_a_terminal_gets_the_tables_and_a_pipe_gets_the_plain_text(worked, capsys,
                                                                    monkeypatch):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    assert cli._plain()          # captured stdout is no terminal
    assert cli.main(["status"]) == 0
    piped = capsys.readouterr().out
    project = Project.find()
    assert piped == project.agent_status_text(landed=project.landed_map()) + "\n"
    assert not BOX & set(piped)

    with monkeypatch.context() as m:
        m.setattr(sys, "stdout", Terminal())
        assert not cli._plain()  # the check reads the real stdout
    monkeypatch.setattr(cli, "_plain", lambda: False)  # what the tty fixture does
    assert cli.main(["status"]) == 0
    table = capsys.readouterr().out
    assert BOX & set(table) and "closed or dropped — clarity-ctl status --all" in table


def test_the_rules_do_not_mention_a_flag_for_reads():
    from clarity import agents
    assert "--agent" not in agents.LOCAL_BLOCK and "`--json` is for scripts" in agents.LOCAL_BLOCK


def test_show_closed_piped_includes_archived_items_so_the_blocks_pointer_is_true(
        worked, workspace, capsys):
    workspace.archive()                      # both closed items leave the live worklog
    assert not [i for i in workspace.worklog.items if i.status in ("done", "dropped")]
    assert "Closed (2), newest first" in agent(capsys, "show", "closed")
    assert "2 closed or dropped (2 archived): `clarity-ctl show closed`" in agent(capsys, "status")


def test_show_piped_leads_with_the_handoff_and_status_says_who_holds_the_lease(worked, capsys):
    lines = agent(capsys, "show", str(worked["live"])).splitlines()
    at = lines.index("brief: cut load time")
    assert lines[at + 1] == "handoff: lexer done"
    assert any(line.startswith("lease: ") for line in lines)
    assert any(line.startswith("  lease: ") for line in agent(capsys, "status").splitlines())


def test_the_blocks_pointers_need_no_flag(project):
    for n in range(14):
        project.add(f"idea {n}")
    done = project.add("finished")
    project.close(done.id, "done")

    assert "--agent" not in project.state_digest()
