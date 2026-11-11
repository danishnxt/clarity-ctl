"""The state digest: bounded however large the project, closed work listed newest
first by id and name, and cut from the oldest end when it must be.

Worklogs here are built from model.Item, no files and no git.
"""

import re

from clarity import render
from clarity.model import Item, Note, Objectives


def _text(tag: str, length: int) -> str:
    """Text of exactly `length` characters that starts with `tag`."""
    return (f"{tag} " + "lorem ipsum dolor sit amet " * 40)[:length].rstrip().ljust(length, "x")


def worklog(closed: int = 0, ideas: int = 0, decisions: int = 0, decision_length: int = 700,
            name_length: int = 80, outcome_length: int = 300) -> list[Item]:
    """`closed` finished items (ids 1..closed, closed in that order), then `ideas`
    ideas, with DECISION: notes on the first `decisions` of the finished ones."""
    items = []
    for n in range(1, closed + 1):
        item = Item(id=n, name=_text(f"epoch {n}", name_length), status="done",
                    outcome=_text(f"outcome {n}", outcome_length), created="2026-01-01",
                    ended="2026-02-01", closed_seq=n)
        if n <= decisions:
            item.notes.append(Note(at=f"2026-02-01 10:{n % 60:02d}",
                                   text=f"DECISION: {_text(f'decision {n}', decision_length)}"))
        items.append(item)
    for n in range(closed + 1, closed + ideas + 1):
        items.append(Item(id=n, name=_text(f"idea {n}", name_length), status="idea"))
    return items


def _active(n: int) -> Item:
    """An active epoch whose handoff is 600 characters, the most a line carries."""
    return Item(id=n, name=_text(f"active {n}", 80), status="active",
                notes=[Note(at="2026-03-01 09:00", text="HANDOFF: " + _text(f"handoff {n}", 600))])


def digest(items: list[Item]) -> str:
    return render.state_digest(Objectives(), items)


def closed_section(text: str) -> str:
    """The closed list's entry line."""
    head = text.index(render.CLOSED_HEADING)
    return text[head + len(render.CLOSED_HEADING):].lstrip("\n")


def test_the_budget_is_two_thousand_tokens_at_four_characters():
    assert render.DIGEST_BUDGET == 8000


def test_a_thousand_closed_items_cost_no_more_than_ten():
    # the closed list is bounded: ten entries and a pointer, however many were closed
    big, small = digest(worklog(closed=1000)), digest(worklog(closed=11))
    assert len(big) <= render.DIGEST_BUDGET
    assert len(big) - len(small) <= 40   # only the pointer's count and the ids differ


def test_sixty_long_decisions_and_three_hundred_ideas_stay_within_the_budget():
    for shape in (dict(closed=1000, ideas=300),
                  dict(closed=1000, decisions=60),
                  dict(closed=1000, ideas=300, decisions=60),
                  dict(closed=0, ideas=300, decisions=60)):
        text = digest(worklog(**shape))
        assert len(text) <= render.DIGEST_BUDGET, shape


def test_the_closed_list_never_costs_a_decision():
    # 20 decisions of 240 characters and a thousand closed items: both fit
    text = digest(worklog(closed=1000, decisions=20))
    assert text.count("\n- ") >= 20 and "decision 20 " in text
    assert "older, in the notes of the epochs they name" not in text
    assert closed_section(text).endswith("990 older: `clarity-ctl show closed --agent`")


def test_the_oldest_decisions_go_when_the_closed_list_has_no_room_at_all():
    # eight active epochs with full-length handoffs and 40 decisions: without a cut the
    # decisions alone leave the closed list less room than its heading and last line
    items = worklog(closed=40, decisions=40, decision_length=600)
    for n in range(101, 109):
        items.append(_active(n))
    text = digest(items)
    assert len(text) <= render.DIGEST_BUDGET
    older = re.search(r"- (\d+) older, in the notes of the epochs they name", text)
    assert older and 20 < int(older.group(1)) <= 40   # cut below the 20 that are usually shown
    assert "decision 40 " in text and "decision 1 " not in text   # the newest are kept
    assert render.CLOSED_HEADING in text              # a list was still possible
    assert re.search(r"\d+ older: `clarity-ctl show closed --agent`$", text)
    # the active work is never cut
    assert all(f"#{n} active {n}" in text for n in range(101, 109))


def test_active_work_alone_past_the_budget_is_not_cut_and_carries_no_closed_list():
    items = worklog(closed=10)
    for n in range(101, 121):
        items.append(_active(n))
    text = digest(items)
    assert len(text) > render.DIGEST_BUDGET
    assert render.CLOSED_HEADING not in text
    assert all(f"#{n} active {n}" in text for n in range(101, 121))


def test_the_closed_list_is_the_ten_newest_with_marks_and_says_how_many_are_older():
    items = worklog(closed=1000)
    items[995].status = "dropped"  # id 996
    text = digest(items)
    entries = closed_section(text).split(" · ")
    assert len(entries) == render.DIGEST_CLOSED + 1
    ids = [int(re.match(r"#(\d+) ", e).group(1)) for e in entries[:-1]]
    assert ids == list(range(1000, 990, -1))                       # newest first, no gaps
    assert all(re.match(r"#\d+ ✓ ", e) for e in entries[:-1] if not e.startswith("#996 "))
    assert entries[4].startswith("#996 ✗ ")
    assert all(len(e.split(" ", 2)[2]) <= render.DIGEST_CLOSED_NAME for e in entries[:-1])
    assert entries[-1] == "990 older: `clarity-ctl show closed --agent`"


def test_a_dropped_item_is_marked_with_a_cross():
    items = worklog(closed=30)
    items[24].status = "dropped"
    items[25].status = "dropped"
    text = digest(items)
    assert "#25 ✗ " in text and "#26 ✗ " in text and "#27 ✓ " in text


def test_ten_or_fewer_closed_items_are_all_listed_and_nothing_says_older():
    text = digest(worklog(closed=10))
    assert "older" not in closed_section(text)
    assert re.findall(r"#(\d+) ", closed_section(text)) == [str(n) for n in range(10, 0, -1)]


def test_closed_work_is_listed_by_id_and_name_only_not_outcome():
    text = digest(worklog(closed=5))
    assert "outcome 3" not in text and "#3 ✓ epoch 3" in text


def test_no_closed_items_means_no_list():
    assert render.CLOSED_HEADING not in digest(worklog(ideas=3))
