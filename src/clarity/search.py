"""Keyword search over the worklog: find the item that holds a fact.

Pure and offline. `search(items, query, limit)` reads the items it is given and nothing
else — no index is stored, so there is nothing to go stale, and the eval can call it on a
frozen worklog. Stdlib only.

The scoring is meant to be explained in a sentence, not tuned: a query term that appears
in an item scores by how well it matches (exact word, stem, typo) times how rare it is
across the worklog, with a bonus when it is in the item's name.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from .model import Item, id_key

STOPWORDS = frozenset(
    "the a an of to in on for and or is was it what which how why when does did do be "
    "with that this from by as at not".split())

# how well a query term matches a word in an item
EXACT, STEM, TYPO = 1.0, 0.7, 0.5
STEM_MIN = 4      # a stem match needs the shorter word to be at least this long
TYPO_MIN = 5      # a typo match needs both words at least this long...
TYPO_RATIO = 0.85  # ...and a SequenceMatcher ratio at least this high
NAME_BONUS = 1.5  # multiplies a term's score when it matches a word of the item's name
SNIPPET = 160     # characters of a snippet, about
LEAD = 40         # of which this many before the first matched word

_WORD = re.compile(r"[a-z0-9_]+", re.ASCII | re.IGNORECASE)


@dataclass
class Hit:
    id: int | str
    name: str
    status: str
    score: float
    field: str      # "outcome", "brief", "note 3", or "name" when only the name matched
    snippet: str    # "" when the name is the only match


def tokens(text: str) -> list[str]:
    """Lowercase runs of [a-z0-9_], without stopwords and one-character tokens."""
    return [w for w in (m.group().lower() for m in _WORD.finditer(text))
            if len(w) > 1 and w not in STOPWORDS]


def terms(query: str | list[str]) -> list[str]:
    """The distinct query terms, in the order given."""
    words = tokens(query if isinstance(query, str) else " ".join(query))
    return list(dict.fromkeys(words))


def match(term: str, word: str) -> float:
    """How well `word` matches `term`: 1.0 the same word, 0.7 one is the other's prefix
    (shorter at least 4 characters: lease/leases, merge/merged), 0.5 a typo (ratio >= 0.85
    between words of 5+ characters), else 0."""
    if term == word:
        return EXACT
    short, long_ = sorted((term, word), key=len)
    if len(short) >= STEM_MIN and long_.startswith(short):
        return STEM
    if len(term) >= TYPO_MIN and len(word) >= TYPO_MIN:
        s = SequenceMatcher(None, term, word)
        if (s.real_quick_ratio() >= TYPO_RATIO and s.quick_ratio() >= TYPO_RATIO
                and s.ratio() >= TYPO_RATIO):
            return TYPO
    return 0.0


def _fields(item: Item) -> list[tuple[str, str]]:
    """The searchable text of an item, as (label, text). The name is first."""
    out = [("name", item.name or "")]
    if item.outcome:
        out.append(("outcome", item.outcome))
    if item.brief:
        out.append(("brief", item.brief))
    out += [(f"note {n}", note.text) for n, note in enumerate(item.notes, 1)]
    return out


def _clip(text: str, matched: set[str]) -> str:
    """About SNIPPET characters of `text` around its first word in `matched`, with an
    ellipsis wherever it is cut."""
    text = " ".join(text.split())
    if len(text) <= SNIPPET:
        return text
    pos = next((m.start() for m in _WORD.finditer(text) if m.group().lower() in matched), 0)
    start = max(0, pos - LEAD)
    end = min(len(text), start + SNIPPET)
    start = max(0, end - SNIPPET)
    if start > 0:  # begin at a word, not in the middle of one
        start = text.rfind(" ", 0, start) + 1
    if end < len(text):
        cut = text.rfind(" ", pos, end)
        end = cut if cut > pos else end
    return ("…" if start > 0 else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def search(items: list[Item], query: str | list[str], limit: int = 5) -> list[Hit]:
    """The `limit` items that best match `query`, best first; 0 for all of them.

    Per distinct query term, find its best match among the words of the item's name,
    outcome, brief and notes (see `match`; on a tie the rarer word). Weight it by
    log(1 + N/df), N the number of items and df the number holding the matched word, so a
    rare word counts for more than a common one. An item's score is the sum of
    weight x match over the terms, a term also found in the name counting 1.5 times.
    Ties go to the higher id, which is the newer item.
    """
    query_terms = terms(query)
    if not query_terms or not items:
        return []

    docs = [(item, [(label, text, set(tokens(text))) for label, text in _fields(item)])
            for item in items]
    df: dict[str, int] = {}
    for _, fields in docs:
        for word in set().union(*(words for _, _, words in fields)):
            df[word] = df.get(word, 0) + 1
    n = len(docs)

    # per term, every word of the worklog it matches, with how well
    matches = {t: {w: m for w in df if (m := match(t, w)) > 0} for t in query_terms}

    def best(term: str, words: set[str]) -> float:
        """weight x match for the term's best word in `words`; 0 if none matches."""
        found = [(matches[term][w], -df[w]) for w in words & matches[term].keys()]
        if not found:
            return 0.0
        m, neg_df = max(found)
        return m * math.log(1 + n / max(1, -neg_df))

    scored: list[tuple[float, Item, list]] = []
    for item, fields in docs:
        name_words = fields[0][2]
        score = 0.0
        all_words = set().union(*(words for _, _, words in fields))
        for t in query_terms:
            part = best(t, all_words)
            if part and best(t, name_words):
                part *= NAME_BONUS
            score += part
        if score > 0:
            scored.append((score, item, fields))

    scored.sort(key=lambda s: (-s[0], tuple(-x for x in id_key(s[1].id))))
    hits = []
    for score, item, fields in (scored if limit <= 0 else scored[:limit]):
        # the snippet: the one field, other than the name, that scores highest
        label, text, top = "name", "", 0.0
        for lab, txt, words in fields[1:]:
            field_score = sum(best(t, words) for t in query_terms)
            if field_score > top:
                label, text, top = lab, txt, field_score
        snippet = ""
        if top:
            hit_words = {w for t in query_terms for w in matches[t]}
            snippet = _clip(text, hit_words)
        hits.append(Hit(id=item.id, name=item.name, status=item.status,
                        score=score, field=label, snippet=snippet))
    return hits
