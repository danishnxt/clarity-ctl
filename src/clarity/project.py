"""The Project API. The CLI is a thin shell over this, so there is one implementation."""

from __future__ import annotations

import difflib
import os
from contextlib import contextmanager
from pathlib import Path

from . import adopt, agents, gitops, lease, render
from .model import (
    CLOSED,
    DEFAULT_CONFIG,
    FUTURE,
    IN_FLIGHT,
    NEEDS_FOLDER,
    STATUSES,
    TYPES,
    Item,
    Note,
    id_key,
    now as model_now,
    parse_id,
    today,
)
from .store import (
    ARCHIVE,
    CONFIG_DIR,
    WORKLOG,
    ClarityError,
    Worklog,
    file_lock,
    load_config,
    save_config,
    write_archive,
    write_atomic,
    write_if_changed,
)

EPOCHS = "EPOCHS"
# An epoch's subepochs, kept together: EPOCHS/subepochs/<parent folder>/<child>.
SUBEPOCHS = "subepochs"
# A child sits two folders deeper than a top-level epoch, so its worktrees and lease
# need their own lines — EPOCHS/*/wt/ and EPOCHS/*/.lease do not reach it.
SUBEPOCH_IGNORES = ["EPOCHS/subepochs/*/*/wt/", "EPOCHS/subepochs/*/*/.lease"]
LEARNINGS = "LEARNINGS"
EPOCH_SUBDIRS = ("PLANS", "LOGS", "VIZ", "ANALYSIS")
LOCK_FILE = "worklog.lock"

GITIGNORE_LINES = [
    "# clarity",
    "EPOCHS/*/wt/",
    *SUBEPOCH_IGNORES,
    "EPOCHS/*/.lease",
    ".clarity/cache/",
    ".clarity/worklog.lock",
]

def _state_repo_ignores() -> list[str]:
    """Added only when clarity makes the root a repo for its own files.

    Everything at the root is ignored unless it is clarity's: a folder adopted
    with a .env or a build tree still in it must not hand them to `git add .`,
    and neither must anything dropped there later. That also keeps out the
    nested repos in workspace/ and 3rd_party/, which have histories of their
    own. A baseline epoch's LOGS/ can run to gigabytes, so it stays out too.
    """
    own = [".gitignore", f"{CONFIG_DIR}/", f"{EPOCHS}/", f"{LEARNINGS}/", WORKLOG]
    lines = ["# clarity's own files only — the rest of the root stays out", "/*"]
    lines += [f"!/{name}" for name in own]
    for name, _ in agents.LOCAL_TARGETS:
        parent, _, leaf = name.rpartition("/")
        if parent:  # .github/ holds more than ours: let in the one file
            lines += [f"!/{parent}/", f"/{parent}/*", f"!/{name}"]
        else:
            lines.append(f"!/{leaf}")
    return lines + ["EPOCHS/*/LOGS/"]


WORKSPACE = "workspace"


def _refuse_existing(root: Path) -> None:
    if (root / CONFIG_DIR).is_dir() and (root / WORKLOG).exists():
        raise ClarityError(f"{root} is already a clarity project", code=4)


def _move_repo_aside(root: Path) -> str:
    """Everything in `root`, .git included, into workspace/<root's name>/.

    Through a staging folder, so a repo that already has a workspace/ of its own
    moves like anything else. A failure part-way puts back what already moved:
    half a checkout at the root and half under workspace/ is worse than either.
    """
    if not (root / ".git").is_dir():
        raise ClarityError(
            f"{root} is a linked worktree or a submodule — adopt the main checkout",
            code=4)
    rel = f"{WORKSPACE}/{root.name}"
    staging = root / f".clarity-adopt-{os.getpid()}"
    staging.mkdir()
    done: list[str] = []
    try:
        for entry in sorted(os.listdir(root)):
            if entry != staging.name:
                os.rename(root / entry, staging / entry)
                done.append(entry)
        (root / WORKSPACE).mkdir()
        os.rename(staging, root / rel)
    except OSError as exc:
        if (root / WORKSPACE).is_dir() and not os.listdir(root / WORKSPACE):
            (root / WORKSPACE).rmdir()
        for entry in reversed(done):
            os.rename(staging / entry, root / entry)
        staging.rmdir()
        raise ClarityError(f"could not move the repo to {rel}: {exc}", code=1)
    gitops.repair_worktrees(root / rel)  # linked worktrees point at the old .git
    return rel


def _inside_worktree(path: Path) -> bool:
    """True for a path under EPOCHS/<epoch>/wt/.

    Once the worklog is committed, every epoch worktree contains a checked-out copy of
    the project's state. Walking up from inside one must reach the real project, not
    the copy — otherwise notes and status changes land in a checkout and vanish on close.
    """
    parts = path.parts
    for index, part in enumerate(parts):
        if part == "wt" and index >= 2 and parts[index - 2] == EPOCHS and index < len(parts) - 1:
            return True
    return False


class Project:
    def __init__(self, root: Path):
        self.root = root
        self.worklog = Worklog.load(root / WORKLOG)
        self.config = load_config(root)

    # ---------- locating and creating ----------

    @staticmethod
    def find(start: Path | None = None) -> "Project":
        here = (start or Path.cwd()).resolve()
        for candidate in [here, *here.parents]:
            if not ((candidate / CONFIG_DIR).is_dir() and (candidate / WORKLOG).exists()):
                continue
            if _inside_worktree(candidate):
                continue  # a checked-out copy of the state, not the project itself
            return Project(candidate)
        raise ClarityError(
            "not a clarity project — no .clarity/ here or above\n"
            "  set one up with: clarity-ctl init",
            code=3,
        )

    @staticmethod
    def init(root: Path, name: str | None = None, overall: str | None = None) -> "Project":
        """A new project in `root`, which must not be a repo of code.

        Clarity's files in the same repo as the code means pushing the code pushes
        the worklog and every epoch with it. adopt moves the code aside first.
        """
        root = root.resolve()
        _refuse_existing(root)
        if gitops.is_repo(root):
            raise ClarityError(
                f"{root} is a git repo — clarity keeps its files out of your code\n"
                f"  did you mean: clarity-ctl adopt\n"
                f"  it moves this repo to {WORKSPACE}/{root.name}/ and sets up beside it",
                code=4,
            )
        return Project.create(root, name=name, overall=overall)

    @staticmethod
    def create(root: Path, name: str | None = None, overall: str | None = None) -> "Project":
        """The layout, wherever `root` is. init and adopt decide whether it should be there.

        A root that is not a repo becomes one, for clarity's own files only — else
        the worklog and every epoch's notes live in no repo at all. Nothing is
        committed: the worklog only grows, so when to snapshot or share it is the
        human's call. A root that already is one is a project set up in place,
        before init refused that; it keeps being branched.
        """
        root = root.resolve()
        _refuse_existing(root)
        state_repo = not gitops.is_repo(root)
        if state_repo:
            gitops.init(root)

        (root / CONFIG_DIR).mkdir(parents=True, exist_ok=True)
        (root / EPOCHS).mkdir(exist_ok=True)
        (root / LEARNINGS).mkdir(exist_ok=True)

        config = {**DEFAULT_CONFIG, "project": {"name": name or root.name}}
        save_config(root, config)

        worklog = Worklog.empty(root / WORKLOG)
        worklog.objectives.overall = overall
        worklog.state_repo = state_repo
        worklog.save()

        project = Project(root)
        project.install_agents()
        project.render_views()
        project.ensure_gitignore()
        if state_repo:
            project.ensure_gitignore(_state_repo_ignores())
        return project

    @staticmethod
    def adopt(root: Path) -> tuple["Project", Path, str | None]:
        """init, plus the procedure for accounting for work that predates it.

        Refuses an existing clarity project for the same reason `init` does: the
        worklog already describes this repo, and a second pass over it would
        propose items for work that is already tracked.

        A root that is itself a repo of code moves whole into workspace/<name>/ —
        the same as `mv` into a parent folder, done in place — and is listed, so
        epochs branch it. Whole, not just what git tracks: an ignored .env or build
        tree left at the root would break the checkout it came from.

        Either way the root then becomes a repo for clarity's own files, as at init.
        Returns (project, the procedure's path, where the repo moved or None).
        """
        root = root.resolve()
        _refuse_existing(root)
        moved = _move_repo_aside(root) if gitops.is_repo(root) else None
        project = Project.create(root)
        if moved:
            project.repo_add(str(root / moved))
        return project, adopt.write_doc(project.root), moved

    # ---------- paths ----------

    @property
    def epochs_dir(self) -> Path:
        return self.root / EPOCHS

    @property
    def lock_path(self) -> Path:
        return self.root / CONFIG_DIR / LOCK_FILE

    def folder_of(self, item: Item) -> Path | None:
        return self.root / item.folder if item.folder else None

    # ---------- writing ----------

    def _snapshot(self) -> dict:
        """What every generated view is a function of, as plain data.

        Built from the same dicts that get saved, so it cannot disagree with what lands
        on disk — unlike a dirty flag every future mutation would have to remember to set.
        """
        return {
            "objectives": self.worklog.objectives.to_dict(),
            "items": {i.id: i.to_dict() for i in self.worklog.items},
        }

    @contextmanager
    def _write(self):
        """Every mutation runs in here: lock, re-read, change, save, re-render.

        Re-reading under the lock is what makes concurrent writers safe — whatever
        another process committed since this one started is picked up first.

        The agent block is refreshed here too, so the first write after an upgrade
        brings the project's instructions up to what this binary does, and every write
        rewrites the state digest at the block's end.
        """
        with file_lock(self.lock_path):
            self.worklog = Worklog.load(self.root / WORKLOG)
            if self.worklog.newer:
                raise ClarityError(self.worklog.newer_warning(), code=4)
            before = self._snapshot()
            yield
            self.worklog.save()
            self.render_views(since=before)
            agents.refresh(agents.local_paths(self.root), self.state_digest())

    # ---------- which epoch does a command mean ----------

    @staticmethod
    def as_id(value: int | str) -> int | str:
        """An id, or a refusal. Never a ValueError escaping to the user as a traceback."""
        parsed = parse_id(value)
        if parsed is None:
            raise ClarityError(f"{value!r} is not an id — ids are numbers, like 7, or 7.1 "
                               f"for a subepoch", code=4)
        return parsed

    def resolve_id(self, explicit: int | str | None = None) -> int | str:
        """The id the command was given. There is no fallback, on purpose.

        Inferring it — from the cwd, an env var, or "the only active epoch" —
        works right up until a second epoch is active, and then the same command
        means something different with nothing on screen to say so. An agent that
        gets a fresh shell per command cannot see any of that state. So the id is
        always in the command, where a transcript shows which epoch was meant.
        """
        if explicit is not None:
            return self.as_id(explicit)

        targetable = [i for i in self.worklog.items if i.status in IN_FLIGHT]
        if not targetable:
            raise ClarityError(
                "this command needs an epoch id, and no epoch is active — "
                "start one with `clarity-ctl epoch start <id>`",
                code=4,
            )
        listed = "\n".join(f"  {i.id:>3}  {i.name}" for i in targetable)
        raise ClarityError(
            "this command needs an epoch id — pass one:\n" + listed,
            code=4,
        )

    # ---------- generated output ----------

    def render_views(self, since: dict | None = None) -> None:
        """Rewrite the views the worklog owns — only the ones whose inputs moved.

        `since` is a snapshot taken before the mutation, so only the items whose
        serialized form actually changed get re-rendered. That makes a write O(1)
        rather than O(number of epochs). Passing nothing rebuilds everything.
        """
        now = self._snapshot()

        for item in self.worklog.items:
            if since is not None and since["items"].get(item.id) == now["items"].get(item.id):
                continue
            folder = self.folder_of(item)
            if folder and folder.is_dir():
                path = folder / "EPOCH.md"
                existing = path.read_text(encoding="utf-8") if path.exists() else None
                write_if_changed(path, render.epoch_md(item, existing))

    def install_agents(self, remove: bool = False) -> list[tuple[Path, str]]:
        """Put the clarity block in this project's agent files, or take it out."""
        return agents.install(agents.local_paths(self.root), remove_instead=remove,
                              state=self.state_digest())

    def state_digest(self) -> str:
        """Where things stand, for the agent block: worklog facts only, so never stale."""
        return render.state_digest(self.worklog.objectives, self.worklog.all_items())

    @staticmethod
    def _plans(folder: Path) -> list[str]:
        """Long-form docs living with the work. Listed, never parsed."""
        plans = folder / "PLANS"
        if not plans.is_dir():
            return []
        return sorted(f.name for f in plans.iterdir() if f.is_file() and not f.name.startswith("."))

    def path_of(self, item_id: int | None = None) -> Path:
        """Where the work is. `cd $(clarity-ctl path 7)`."""
        item = self.worklog.by_id(self.resolve_id(item_id))
        folder = self.folder_of(item)
        if not folder or not folder.is_dir():
            raise ClarityError(f"item {item.id} has no folder on disk", code=4)
        return folder

    def ensure_gitignore(self, wanted: list[str] = GITIGNORE_LINES) -> bool:
        """Called at init. Matches whole lines, so `!.clarity/cache/` is not a match."""
        path = self.root / ".gitignore"
        existing = path.read_text(encoding="utf-8") if path.exists() else ""
        lines = existing.splitlines()
        missing = [l for l in wanted if l not in lines]
        if not missing:
            return False
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        write_atomic(path, existing + prefix + "\n".join(missing) + "\n")
        return True

    # ---------- leases ----------

    def leases(self) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for item in self.worklog.items:
            folder = self.folder_of(item)
            if folder and folder.is_dir():
                held = lease.read(folder)
                if held:  # never auto-expires — a lease stands until someone clears it
                    out[item.id] = {**held, "age": lease.age(held)}
        return out

    def claim(self, item_id: int | None = None, steal: bool = False,
              as_name: str | None = None) -> tuple[Item, dict]:
        item = self.worklog.by_id(self.resolve_id(item_id))
        folder = self.folder_of(item)
        if not folder:
            raise ClarityError(f"item {item.id} has no folder to lease", code=4)
        held = lease.claim(folder, steal=steal, label=item.name, name=as_name)
        return item, held

    def release(self, item_id: int | None = None, force: bool = False,
                as_name: str | None = None) -> Item:
        item = self.worklog.by_id(self.resolve_id(item_id))
        folder = self.folder_of(item)
        if folder:
            lease.release(folder, force=force, name=as_name)
        return item

    # ---------- objectives ----------

    def set_objective(self, text: str) -> None:
        # Nothing to regenerate: the objective lives in worklog.yaml and is printed by
        # `clarity-ctl status`. No file carries a copy of it.
        with self._write():
            self.worklog.objectives.overall = text

    # ---------- the repos a workspace changes ----------

    def _repo_rel(self, path: str) -> str:
        """A path to a repo, relative to the root. A relative one is read from the
        root when it names something there, so `workspace/web` means the same from
        any directory, and from the shell's directory otherwise."""
        target = Path(path).expanduser()
        if not target.is_absolute():
            from_root = self.root / target
            target = from_root if from_root.exists() else Path.cwd() / target
        target = target.resolve()
        root = self.root.resolve()
        if target == root and self.worklog.state_repo:
            raise ClarityError(
                "that's the project root — it holds clarity's own files, not code to branch",
                code=4)
        if target == root:
            raise ClarityError(
                "that's the project root — with no repos listed, epochs branch it already",
                code=4)
        if root not in target.parents:
            raise ClarityError(f"{path} is outside this project", code=4)
        return target.relative_to(root).as_posix()

    def repo_add(self, path: str) -> list[str]:
        rel = self._repo_rel(path)
        if not gitops.is_repo(self.root / rel):
            raise ClarityError(f"{rel} is not a git repo — no .git in it", code=4)
        with self._write():
            if rel in self.worklog.repos:
                return list(self.worklog.repos)
            name = Path(rel).name
            clash = [r for r in self.worklog.repos if Path(r).name == name]
            if clash:
                raise ClarityError(
                    f"{clash[0]} is also called {name} — each repo's worktree is "
                    f"wt/<folder name>, so two can't share one", code=4)
            self.worklog.repos.append(rel)
        return list(self.worklog.repos)

    def repo_remove(self, name: str) -> list[str]:
        with self._write():
            rel = self.listed_repo(name)
            self.worklog.repos.remove(rel)
        return list(self.worklog.repos)

    def listed_repo(self, raw: str, among: list[str] | None = None,
                    what: str = "a listed repo") -> str:
        """The one listed repo `raw` names: a listed path or a folder name, exactly,
        or a path that leads to a listed repo. Every command that takes a repo reads
        it here, so a name means the same thing whichever directory the shell is in.

        Nothing looser picks: a prefix that is unique today stops being the repo you
        meant once that repo leaves the list, and then it names a different one
        without a word. Close matches only ever appear in the refusal.
        """
        listed = self.worklog.repos if among is None else among
        if not listed and among is None:
            raise ClarityError(
                "no repos listed — epochs here branch the project root\n"
                "  list one with: clarity-ctl repo add <path>", code=4)
        names = {Path(r).name: r for r in listed}
        name = raw.strip().rstrip("/")
        if name in listed or name in names:
            return names.get(name, name)
        try:
            rel = self._repo_rel(name)
        except ClarityError:
            rel = None
        if rel in listed:
            return rel
        close = difflib.get_close_matches(name, [*names, *listed], n=3)
        hint = f" — did you mean {' or '.join(close)}?" if close else ""
        if among is not None:
            raise ClarityError(f"{raw!r} is not {what}{hint}\n"
                               f"  it has: {', '.join(listed) or 'none'}", code=4)
        raise ClarityError(
            f"{raw!r} is not a listed repo{hint}\n"
            f"  listed: {', '.join(listed)}\n"
            f"  list another with: clarity-ctl repo add <path>", code=4)

    def pick_repos(self, wanted: list[str]) -> list[str]:
        """The listed repos `wanted` names, in list order."""
        picked = {self.listed_repo(raw) for raw in wanted}
        return [r for r in self.worklog.repos if r in picked]

    # ---------- items ----------

    def add(self, name: str, type_: str = "feature", description: str | None = None,
            status: str = "idea", evidence: str | None = None) -> Item:
        if type_ not in TYPES:
            raise ClarityError(f"unknown type {type_!r}; one of {', '.join(TYPES)}", code=4)
        if status not in STATUSES:
            raise ClarityError(f"unknown status {status!r}", code=4)
        with self._write():
            item = Item(
                id=self.worklog.next_id(),
                name=name,
                type=type_,
                status=status,
                description=description,
                evidence=evidence,
            )
            self.worklog.items.append(item)
            if status in NEEDS_FOLDER:
                self._make_folder(item)
        return item

    def _make_folder(self, item: Item) -> Path:
        if item.folder and (self.root / item.folder).is_dir():
            return self.root / item.folder
        home = self.epochs_dir
        if item.parent is not None:
            parent = self.worklog.by_id(item.parent)
            home = self.epochs_dir / SUBEPOCHS / Path(parent.folder).name
        folder = home / item.folder_name
        for sub in EPOCH_SUBDIRS:
            (folder / sub).mkdir(parents=True, exist_ok=True)
        item.folder = str(folder.relative_to(self.root))
        return folder

    def start(self, item_id: int, branch: str | None = None,
              take_lease: bool = True, reopen: bool = False,
              repos: list[str] | None = None,
              no_repos: bool = False,
              brief: str | None = None,
              as_name: str | None = None) -> tuple[Item, list[str]]:
        """idea -> active: resolve a branch to a worktree or a symlink, then lease it.

        A closed epoch needs `reopen`, so picking work back up is deliberate rather
        than a typo that quietly reanimates something you finished last month.

        `repos` narrows which listed repos a new epoch branches; left out, it gets
        all of them. `no_repos` branches none — a folder and a lease, for planning or
        analysis before any code; add_repos brings repos in when the code starts. A reopen takes back the repos the epoch had — adding one is
        add_repos, so no command does two jobs depending on the epoch's state.

        A subepoch (see spawn) starts only while its parent is active, and a reopen
        of one asks the same.

        `brief` is the text, or the path to a file holding it. Given on a reopen, it
        replaces the old one; left out, the brief stays.

        `as_name` is who the lease is for, as `claim --as` takes it — so the agent that
        starts an epoch holds it under its own name, and needs no claim after.
        """
        warnings: list[str] = []
        if brief and Path(brief).is_file():
            brief = Path(brief).read_text(encoding="utf-8").strip()
        with self._write():
            item = self.worklog.by_id(item_id)
            if item.parent is not None:
                self._check_parent(self.worklog.by_id(item.parent))
            if brief:
                item.brief = brief
            if item.status == "active":
                raise ClarityError(
                    f"epoch {item.id} is already active — to add a repo:\n"
                    f"  clarity-ctl epoch add-repo {item.id} <repo>", code=4)
            closed = item.status in CLOSED
            if closed and not reopen:
                raise ClarityError(
                    f"item {item_id} is {item.status} — pick it back up with:\n"
                    f"  clarity-ctl epoch reopen {item_id}",
                    code=4,
                )
            if repos and reopen:
                raise ClarityError(
                    "a reopen takes back the repos the epoch had — add one after with:\n"
                    f"  clarity-ctl epoch add-repo {item.id} <repo>", code=4)
            chosen = self.pick_repos(repos) if repos else None
            if no_repos and self.branches_root():
                raise ClarityError(
                    "this project branches its root, not a list of repos — there would be "
                    "nothing to add later. Start it without --no-repos", code=4)
            if closed:
                # the outcome was true when it was written; keep it in the trail
                if item.outcome:
                    item.notes.append(
                        Note(at=today(), text=f"reopened — previous outcome: {item.outcome}")
                    )
                item.outcome = None
                item.ended = None
            folder = self._make_folder(item)
            if item.parent is not None:
                self.ensure_gitignore(SUBEPOCH_IGNORES)  # projects set up before subepochs
            # Claim before anything else: _write() saves only if the body succeeds, so a
            # refused lease leaves no half-started epoch and no worktree we may not use.
            if take_lease:
                lease.claim(folder, label=item.name, name=as_name)
            if no_repos and item.repos is None and item.branch is None:
                item.repos = []
            elif item.repos is None and item.branch is None and self.worklog.repos:
                # first time this epoch touches git: the repos asked for, else the
                # project's whole list as it is now
                item.repos = chosen or list(self.worklog.repos)
            targets = self._targets(item, folder)
            if targets:
                item.branch, warnings = self._attach_all(item, targets, branch)
            item.status = "active"
            item.started = item.started or today()
        return item, warnings

    def _check_parent(self, parent: Item) -> None:
        """Refuse a parent that cannot take a subepoch: not active, or a subepoch
        itself. One level only, so the tree stays something a person can read.
        by_id has already refused one that is missing or archived."""
        if parent.parent is not None:
            raise ClarityError(
                f"epoch {parent.id} is itself a subepoch of {parent.parent} — "
                "subepochs nest one level only", code=4)
        if parent.status not in IN_FLIGHT:
            how = "start" if parent.status in FUTURE else "reopen"
            raise ClarityError(
                f"parent epoch {parent.id} is {parent.status} — a subepoch runs only while "
                f"its parent is active:\n  clarity-ctl epoch {how} {parent.id}", code=4)

    def spawn(self, parent_id: int | str, name: str, type_: str = "feature",
              brief: str | None = None, repos: list[str] | None = None,
              no_repos: bool = False) -> tuple[Item, list[str]]:
        """A new subepoch of an active epoch, started: id 7.1, 7.2, … under parent 7.

        It branches the parent's repos, or the ones `repos` names among them, and its
        branch is cut from the parent's branch, which is recorded as its base — so
        refresh catches it up with whatever siblings have merged into the parent, and
        the close warning asks for a merge into the parent, not into main. Only the
        parent merges onward. The lease is left free: whoever spawns hands the
        subepoch to another agent, and that agent claims it.
        """
        if type_ not in TYPES:
            raise ClarityError(f"unknown type {type_!r}; one of {', '.join(TYPES)}", code=4)
        with self._write():
            parent = self.worklog.by_id(self.as_id(parent_id))
            self._check_parent(parent)
            if no_repos:
                chosen: list[str] | None = []
            elif repos:
                if parent.repos is None:
                    raise ClarityError(
                        f"epoch {parent.id} branches the project root — its subepochs do "
                        f"too; leave out --repo", code=4)
                named = {self.listed_repo(
                    r, among=parent.repos,
                    what=f"one of epoch {parent.id}'s repos — add it there first: "
                         f"clarity-ctl epoch add-repo {parent.id} <repo>") for r in repos}
                chosen = [r for r in parent.repos if r in named]
            else:
                chosen = None if parent.repos is None else list(parent.repos)
            item = Item(id=self.worklog.next_sub_id(parent.id), name=name, type=type_,
                        parent=parent.id, repos=chosen)
            if parent.branch:
                keys = chosen if chosen is not None else (["."] if self.branches_root() else [])
                item.bases = {k: parent.branch for k in keys} or None
            self.worklog.items.append(item)
        try:
            return self.start(item.id, take_lease=False, brief=brief)
        except Exception:
            # a subepoch that never started is not an idea anyone queued — take it back
            with self._write():
                self.worklog.items = [i for i in self.worklog.items if i.id != item.id]
            raise

    def children_of(self, item_id: int) -> list[Item]:
        """Every child of an epoch, archived ones too: a finished child still counts."""
        return sorted((i for i in self.worklog.all_items() if i.parent == item_id),
                      key=lambda i: id_key(i.id))

    def child_summary(self, child: Item) -> dict:
        """What a parent's roll-up says about one child. Plain data, the same in
        `show --json` and in the text view, so the two cannot disagree."""
        held = self.leases().get(child.id)
        return {
            "id": child.id,
            "name": child.name,
            "status": child.status,
            "outcome": child.outcome,
            "handoff": child.handoff,
            "lease": held,
        }

    def _in_flight_with_repos(self, item: Item) -> Path:
        if item.status not in IN_FLIGHT:
            hint = (f"start it with: clarity-ctl epoch start {item.id} --repo <repo>"
                    if item.status in FUTURE
                    else f"reopen it first: clarity-ctl epoch reopen {item.id}")
            raise ClarityError(f"epoch {item.id} is {item.status} — {hint}", code=4)
        if item.repos is None and item.branch is not None:
            raise ClarityError(
                f"epoch {item.id} branched the project root before repos were "
                f"listed — it has no repo list to change", code=4)
        return self._make_folder(item)

    def add_repos(self, item_id: int, repos: list[str]) -> tuple[Item, list[str], list[str]]:
        """Branch more listed repos in an epoch in flight, on the branch it already has.

        (item, the repos newly added, warnings). Naming one it already has is not an
        error — the end state is what was asked for.
        """
        with self._write():
            item = self.worklog.by_id(item_id)
            folder = self._in_flight_with_repos(item)
            chosen = self.pick_repos(repos)
            added = [r for r in chosen if r not in (item.repos or [])]
            if not added:
                return item, [], []
            lease.claim(folder, label=item.name)
            item.repos = [*(item.repos or []), *added]
            targets = [(repo, link) for repo, link in self._targets(item, folder)
                       if repo.relative_to(self.root).as_posix() in added]
            item.branch, warnings = self._attach_all(item, targets, None)
        return item, added, warnings

    def drop_repo(self, item_id: int, name: str) -> tuple[Item, str]:
        """Stop branching one repo in an epoch in flight: its worktree goes, its
        branch stays. Refuses uncommitted work, and the epoch's last repo — closing
        is how an epoch lets go of everything."""
        with self._write():
            item = self.worklog.by_id(item_id)
            folder = self._in_flight_with_repos(item)
            rel = self.listed_repo(name, among=item.repos or [],
                                   what=f"one of epoch {item.id}'s repos")
            if len(item.repos) == 1:
                raise ClarityError(
                    f"{rel} is epoch {item.id}'s only repo — close the epoch instead:\n"
                    f"  clarity-ctl epoch close {item.id} \"...\"", code=4)
            repo, link = self.root / rel, folder / "wt" / Path(rel).name
            if link.exists() and not link.is_symlink():
                dirty = gitops.is_dirty(link)
                if dirty:
                    raise ClarityError(
                        f"{len(dirty)} uncommitted change(s) in {link} — commit or stash first",
                        code=4)
            lease.claim(folder, label=item.name)
            if link.is_symlink():
                link.unlink()  # we only borrowed the path
            elif link.exists():
                gitops.remove_worktree(repo, link)  # branch survives
            sha = gitops.branch_sha(repo, item.branch) if item.branch else None
            item.repos = [r for r in item.repos if r != rel]
            if item.bases:
                item.bases = {k: v for k, v in item.bases.items() if k != rel} or None
            at = f" at {sha}" if sha else ""
            item.notes.append(Note(at=model_now(),
                                   text=f"dropped {rel} — its branch {item.branch} stays{at}"))
        return item, rel

    def _targets(self, item: Item, folder: Path) -> list[tuple[Path, Path]]:
        """(repo, worktree path) for every repo this epoch branches.

        An epoch with a repo list branches exactly those; one without is the old
        single-repo case and branches the root, if the root is a repo of code.
        """
        if item.repos is not None:
            return [(self.root / r, folder / "wt" / Path(r).name) for r in item.repos]
        if self.branches_root():
            return [(self.root, folder / "wt" / self.root.name)]
        return []

    def _refuse_gone(self, item: Item, targets: list[tuple[Path, Path]], then: str) -> None:
        """A repo whose folder is gone has nothing git can act on — say which."""
        gone = [self._repo_key(repo) for repo, _ in targets if not repo.is_dir()]
        if gone:
            raise ClarityError(
                f"epoch {item.id} branches {', '.join(gone)}, and its folder is gone\n"
                f"  restore it at {self.root / gone[0]}, then {then}", code=4)

    def _attach_all(self, item: Item, targets: list[tuple[Path, Path]],
                    branch: str | None) -> tuple[str, list[str]]:
        """The same branch in every repo, or none of them.

        A start that fails in the third repo would otherwise leave two worktrees and
        two fresh branches behind with nothing recording them, so it undoes its own
        work before the error goes up. _write() already keeps the worklog unchanged.
        """
        # item.branch before the slug: after a rename, a reopen must find the branch
        # the epoch actually has, not one named after its new title
        name = branch or item.branch or f"epoch/{item.code}-{item.slug}"
        warnings: list[str] = []
        made: list[tuple[Path, Path, bool]] = []
        try:
            for repo, link in targets:
                if not gitops.is_repo(repo):
                    raise ClarityError(
                        f"{repo.relative_to(self.root) if repo != self.root else repo} "
                        f"is not a git repo — nothing to branch", code=4)
                result = self._attach_worktree(item, repo, link, name, branch)
                if result is None:
                    continue  # already attached
                created, notes = result
                made.append((repo, link, created))
                warnings += notes
        except Exception:
            for repo, link, created in reversed(made):
                if link.is_symlink():
                    link.unlink()
                else:
                    gitops.remove_worktree(repo, link)
                if created:
                    gitops.delete_branch(repo, name)
            raise
        return name, warnings

    def _attach_worktree(self, item: Item, repo: Path, link: Path, name: str,
                         branch: str | None) -> tuple[bool, list[str]] | None:
        """One repo. (created the branch?, warnings), or None if already attached."""
        warnings: list[str] = []
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.exists() or link.is_symlink():
            # Already attached. Moving it would mean tearing down a checkout someone may
            # be sitting in, so refuse rather than quietly record a branch that isn't
            # the one on disk — which is what this used to do.
            if branch and branch != item.branch:
                raise ClarityError(
                    f"epoch {item.id} is already checked out at {link}\n"
                    f"  on {item.branch or 'an unrecorded branch'}, not {branch}\n"
                    f"  close the epoch, or remove that worktree yourself, to move it",
                    code=4,
                )
            return None

        key = self._repo_key(repo)
        if key not in (item.bases or {}):
            base = gitops.base_branch(repo)
            if base == name:  # the checkout is on the epoch's own branch
                base = gitops.default_branch(repo)
            if base and base != name:
                item.bases = {**(item.bases or {}), key: base}
        exists = gitops.branch_exists(repo, name)
        if exists:
            warnings += self._staleness(item, name, repo)
        checked_out = gitops.worktree_path_for(repo, name) if exists else None
        if checked_out:
            # already checked out somewhere (often the main checkout) — point at it
            link.symlink_to(os.path.relpath(checked_out, link.parent))
            borrowers = [
                i.id for i in self.worklog.items
                if i.id != item.id and i.status in IN_FLIGHT and i.branch == name
            ]
            if borrowers:
                warnings.append(
                    f"epoch(s) {', '.join(map(str, borrowers))} are already working "
                    f"{name} in the same checkout — edits will collide"
                )
        else:
            # a worktree can be added from a dirty tree; git carries nothing across.
            # A subepoch's new branch starts where its parent's is, not at the checkout.
            start = (item.bases or {}).get(key) if item.parent is not None else None
            gitops.add_worktree(repo, link, name, create=not exists, start=start)
        return not exists, warnings

    def _repo_key(self, repo: Path) -> str:
        """How `repos` and `bases` name a repo: relative to the root, "." for the root."""
        return repo.relative_to(self.root).as_posix()

    def base_of(self, item: Item, repo: Path) -> str | None:
        """What `item`'s branch catches up with in `repo`: the base recorded when the
        epoch first branched it. An epoch from before bases were recorded follows the
        checkout, as it did then."""
        recorded = (item.bases or {}).get(self._repo_key(repo))
        return recorded or gitops.base_branch(repo)

    def refresh(self, item_id: int | None = None, base: str | None = None,
                repos: list[str] | None = None) -> tuple[Item, dict]:
        """Merge each repo's recorded base into an in-flight epoch's branch.

        Merges rather than recreating: the branch keeps its identity and its commits,
        so a refresh can never lose work. Deleting branches is a separate question.
        Every repo is checked before any is merged, so a dirty third repo refuses the
        whole refresh instead of leaving two caught up and one not.

        `base` changes what the named repos (default: all the epoch's) catch up with
        from now on, and is recorded before the merge. `repos` narrows the refresh.

        Returns the item and what happened, per repo: {merged: [{repo, base, commits}],
        up_to_date: [{repo, base}]} — the only record of what came in.
        """
        item = self.worklog.by_id(self.resolve_id(item_id))
        if item.status not in IN_FLIGHT:
            raise ClarityError(
                f"epoch {item.id} is {item.status} — only an in-flight epoch refreshes",
                code=4,
            )
        folder = self.folder_of(item)
        targets = self._targets(item, folder) if folder else []
        if not targets or not item.branch:
            raise ClarityError("not a git repo — nothing to refresh from", code=4)
        if repos:
            wanted = {self.listed_repo(r, among=item.repos or [],
                                       what=f"one of epoch {item.id}'s repos")
                      for r in repos}
            targets = [(repo, wt) for repo, wt in targets if self._repo_key(repo) in wanted]
        self._refuse_gone(item, targets, "refresh")

        if base:
            for repo, _ in targets:
                where = "" if repo == self.root else f" in {self._repo_key(repo)}"
                if base == item.branch:
                    raise ClarityError(
                        f"{base} is epoch {item.id}'s own branch — a base is what it "
                        f"catches up with", code=4)
                if not gitops.branch_exists(repo, base):
                    raise ClarityError(f"no branch {base}{where}", code=4)
            with self._write():
                item = self.worklog.by_id(item.id)
                changed = [self._repo_key(repo) for repo, _ in targets
                           if (item.bases or {}).get(self._repo_key(repo)) != base]
                if changed:
                    item.bases = {**(item.bases or {}), **{k: base for k in changed}}
                    item.notes.append(Note(at=model_now(),
                                           text=f"base set to {base} for {', '.join(changed)}"))

        plan: list[tuple[Path, Path, str, int]] = []
        up_to_date: list[dict] = []
        for repo, _ in targets:
            where = "" if repo == self.root else f" in {repo.relative_to(self.root)}"
            base = self.base_of(item, repo)
            if not base:
                raise ClarityError(
                    f"no base recorded, no branch checked out, and no main or master, "
                    f"to refresh from{where}\n"
                    f"  name one with: clarity-ctl epoch refresh {item.id} --base <branch>",
                    code=4,
                )
            if item.branch == base:
                raise ClarityError(f"epoch {item.id} is on {base} already{where}", code=4)
            worktree = gitops.worktree_path_for(repo, item.branch)
            if not worktree:
                raise ClarityError(f"{item.branch} is not checked out anywhere{where}", code=4)
            if worktree == repo:
                # a shared checkout: merging here would move the tree under everyone else
                raise ClarityError(
                    f"{item.branch} shares the main checkout{where} — refresh it there yourself",
                    code=4,
                )
            dirty = gitops.is_dirty(worktree)
            if dirty:
                raise ClarityError(
                    f"{len(dirty)} uncommitted change(s) in {worktree} — commit or stash first",
                    code=4,
                )
            _, behind = gitops.ahead_behind(repo, item.branch, base)
            if behind:
                plan.append((repo, worktree, base, behind))
            else:
                up_to_date.append({"repo": self._repo_key(repo), "base": base})

        merged: list[dict] = []
        if plan:
            # Take the lease before moving anyone's tree. claim() already does the right
            # thing: free, stale or ours goes through, someone else's live one refuses.
            lease.claim(folder, label=item.name)
        for repo, worktree, base, behind in plan:
            gitops.merge_into(worktree, base)
            merged.append({"repo": self._repo_key(repo), "base": base, "commits": behind})
        return item, {"merged": merged, "up_to_date": up_to_date}

    def _behind(self, item: Item, branch: str,
                repo: Path | None = None) -> tuple[str, int, int] | None:
        """(base, ahead, behind) when `branch` trails its base, else None."""
        repo = repo or self.root
        base = self.base_of(item, repo)
        if not base or base == branch:
            return None
        try:
            ahead, behind = gitops.ahead_behind(repo, branch, base)
        except ClarityError:
            return None
        return (base, ahead, behind) if behind else None

    def _staleness(self, item: Item, branch: str, repo: Path | None = None) -> list[str]:
        """Reopening gives you the branch as you left it — say so before work resumes."""
        found = self._behind(item, branch, repo)
        if not found:
            return []
        base, ahead, behind = found
        where = "" if not repo or repo == self.root else f" in {repo.relative_to(self.root)}"
        note = f"{branch}{where} is {behind} commit{'s' if behind != 1 else ''} behind {base}"
        if ahead:
            note += f" and {ahead} ahead"
        return [note]

    def stale_map(self) -> dict[int, list[str]]:
        """Short notes on how in-flight epochs sit against their bases, for status.

        The start-time warning fires once, when the worktree is created; the base moves on
        afterwards and nothing said so. This is what keeps saying it. It also says when
        a repo's checkout has moved off the recorded base, since that is the one
        thing that could make "behind" read as the wrong number.
        """
        out: dict[int, list[str]] = {}
        for item in self.worklog.items:
            if item.status not in IN_FLIGHT or not item.branch:
                continue
            folder = self.folder_of(item)
            behind_parts, drift = [], []
            for repo, _ in (self._targets(item, folder) if folder else []):
                if not repo.is_dir():
                    continue  # missing_warnings() says so, once, for every command
                where = "" if repo == self.root else f" ({repo.name})"
                found = self._behind(item, item.branch, repo)
                if found:
                    base, _, behind = found
                    behind_parts.append(f"{behind} behind {base}{where}")
                recorded = (item.bases or {}).get(self._repo_key(repo))
                checkout = gitops.current_branch(repo)
                if (recorded and checkout and checkout not in ("HEAD", recorded, item.branch)):
                    name = repo.name if repo != self.root else "the"
                    drift.append(f"{name} checkout is on {checkout}; epoch {item.id} "
                                 f"follows {recorded}")
            lines = []
            if behind_parts:
                lines.append(f"{', '.join(behind_parts)} — clarity-ctl epoch refresh {item.id}")
            lines += drift
            if lines:
                out[item.id] = lines
        return out

    def landed_map(self, only: int | None = None) -> dict[int, dict[str, str]]:
        """Per epoch, per repo: whether its work reached its base. Live, never stored.

        merged, unmerged or unknown. A closed epoch is judged by the sha recorded at
        close, falling back to its branch for one closed before shas were recorded. One
        in flight is judged only once someone has committed on its branch — before that
        there is nothing to land, and "merged" would read as finished. Dropped epochs
        get no mark: a drop says the idea failed, whatever happened to its commits.
        """
        out: dict[int, dict[str, str]] = {}
        for item in self.worklog.items:
            if only is not None and item.id != only:
                continue  # git calls per repo add up; show <id> needs just the one
            if not item.branch or item.status == "dropped" or item.status == "idea":
                continue
            if item.repos is not None:
                repos = [self.root / r for r in item.repos]
            elif self.branches_root():
                repos = [self.root]
            else:
                continue
            ends = item.extra.get("end_shas") or {}
            marks: dict[str, str] = {}
            for repo in repos:
                if not repo.is_dir():
                    continue  # missing_warnings() says so, once, for every command
                key = self._repo_key(repo)
                base = self.base_of(item, repo)
                if item.status in IN_FLIGHT:
                    sha = gitops.branch_sha(repo, item.branch)
                    if not sha or not base:
                        continue
                    worked = gitops.committed_on(repo, item.branch)
                    if worked is None:  # no reflog: ahead of base is the next best
                        try:
                            worked = bool(gitops.ahead_behind(repo, item.branch, base)[0])
                        except ClarityError:
                            continue
                    if not worked:
                        continue
                else:
                    sha = (ends.get(key) if item.repos is not None
                           else item.extra.get("end_sha"))
                    sha = sha or gitops.branch_sha(repo, item.branch)
                found = gitops.landed(repo, sha, base) if sha and base else None
                marks[key] = {True: "merged", False: "unmerged", None: "unknown"}[found]
            if marks:
                out[item.id] = marks
        return out

    def note(self, item_id: int | None, text: str) -> Item:
        with self._write():
            item = self.worklog.by_id(self.resolve_id(item_id))
            item.notes.append(Note(at=model_now(), text=text))
        return item

    def rename(self, item_id: int | None, name: str) -> Item:
        """Change what an item is called. Its folder and branch keep their old slug.

        Both are paths other things point at — a worktree, a shell's cwd, a remote —
        and the id prefix already identifies them. The old name goes into a note, so
        the item's history still reads in order.
        """
        name = " ".join(name.split())
        if not name:
            raise ClarityError("a name can't be empty", code=4)
        with self._write():
            item = self.worklog.by_id(self.resolve_id(item_id))
            if name != item.name:
                item.notes.append(Note(at=model_now(), text=f"renamed from: {item.name}"))
                item.name = name
        return item

    def unmerged(self, item_id: int | str) -> list[str]:
        """One line per repo whose epoch branch has commits its base does not.

        close never merges, so this is what stops finished work from being closed
        while it still sits only on its branch. Asked the same way status asks, so
        a squash-merged branch — ahead by its own commits, its changes all in the
        base — is not warned about here and marked merged there.

        A subepoch's base is its parent's branch, so its line says to merge there and
        gives the command. A parent also gets a line for each done subepoch whose
        work never reached it: closing the parent would strand that work for good.
        An experiment is meant to stay unmerged, so it gets no warning of its own.
        """
        item = self.worklog.by_id(item_id)
        folder = self.folder_of(item)
        out = []
        if item.branch and folder and item.type != "experiment":
            into = self._parent_worktrees(item)
            for repo, _ in self._targets(item, folder):
                base = self.base_of(item, repo)
                ahead = self._ahead(repo, item.branch, base)
                if not ahead:
                    continue
                where = "" if repo == self.root else f" in {self._repo_key(repo)}"
                line = (f"{item.branch}{where} has {ahead} commit{'s' if ahead != 1 else ''} "
                        f"not in {base}")
                if repo in into:
                    line += (f" — merge it into epoch {item.parent} before closing:\n"
                             f"  git -C {into[repo]} merge {item.branch}")
                else:
                    line += " — merge before closing"
                out.append(line)
        for child in self.children_of(item.id):
            if child.status != "done" or not child.branch or not item.branch:
                continue
            for repo in self._repo_paths(child):
                ahead = self._ahead(repo, child.branch, item.branch)
                if ahead:
                    where = "" if repo == self.root else f" in {self._repo_key(repo)}"
                    out.append(f"subepoch {child.id}'s {child.branch}{where} has {ahead} "
                               f"commit{'s' if ahead != 1 else ''} not in {item.branch} — "
                               f"its work never reached epoch {item.id}")
        return out

    def _ahead(self, repo: Path, branch: str, base: str | None) -> int:
        """Commits on `branch` that `base` lacks; 0 when either is missing or unreadable,
        or when every change on it is already in `base`, as after a squash merge."""
        if (not repo.is_dir() or not base or base == branch
                or not gitops.branch_exists(repo, branch)
                or not gitops.branch_exists(repo, base)):
            return 0
        try:
            ahead, _ = gitops.ahead_behind(repo, branch, base)
        except ClarityError:
            return 0
        sha = gitops.branch_sha(repo, branch)
        if ahead and sha and gitops.landed(repo, sha, base):
            return 0
        return ahead

    def _repo_paths(self, item: Item) -> list[Path]:
        """The repos an epoch branched, whether or not its folder is still there."""
        if item.repos is not None:
            return [self.root / r for r in item.repos]
        return [self.root] if self.branches_root() else []

    def _parent_worktrees(self, item: Item) -> dict[Path, str]:
        """For a subepoch: each repo's worktree of its parent, as a path from the root —
        where the merge into the parent is run."""
        if item.parent is None:
            return {}
        parent, _ = self.worklog.lookup(item.parent)
        folder = self.folder_of(parent)
        if not folder:
            return {}
        return {repo: os.path.relpath(wt, self.root)
                for repo, wt in self._targets(parent, folder)}

    def close(self, item_id: int | None, outcome: str, dropped: bool = False) -> Item:
        with self._write():
            item = self.worklog.by_id(self.resolve_id(item_id))
            if item.status in CLOSED:
                raise ClarityError(f"item {item.id} is already {item.status}", code=4)
            # a parent is not done while a subepoch is still running or still leased
            leased = self.leases()
            running = [c.id for c in self.children_of(item.id)
                       if c.status in IN_FLIGHT or c.id in leased]
            if running:
                ids = ", ".join(str(i) for i in running)
                raise ClarityError(
                    f"epoch {item.id} has subepochs still active: {ids}\n"
                    f"  close or release them first — see: clarity-ctl show {item.id}", code=4)
            folder = self.folder_of(item)
            # its branch and end sha live in that repo: closing now would record
            # neither, and leave a worktree git can no longer remove
            self._refuse_gone(item, self._targets(item, folder) if folder else [], "close")
            if folder:
                for repo, worktree in self._targets(item, folder):
                    if worktree.is_symlink():
                        worktree.unlink()  # we only borrowed the path
                    elif worktree.exists():
                        gitops.remove_worktree(repo, worktree)  # branch survives
                lease.release(folder, force=True)
            if item.branch and item.repos is not None:
                previous = item.extra.get("end_shas") or {}
                item.extra["end_shas"] = {
                    r: gitops.branch_sha(self.root / r, item.branch) or previous.get(r)
                    for r in item.repos
                }
            elif item.branch:
                # the epoch's own branch, not whatever the main checkout has checked
                # out — the work being closed lives on the former
                item.extra["end_sha"] = (gitops.branch_sha(self.root, item.branch)
                                         or item.extra.get("end_sha"))
            item.status = "dropped" if dropped else "done"
            item.outcome = outcome
            item.ended = today()
            # Derived, not a stored counter: a counter is a second source of truth that
            # can drift from the items it numbers. Safe under _write()'s lock.
            item.closed_seq = max(
                (i.closed_seq or 0 for i in self.worklog.all_items()), default=0
            ) + 1
        return item

    def archive(self) -> list[tuple[str, int]]:
        """Move every closed epoch out of worklog.yaml into ARCHIVE/<month>.yaml.

        Their folders stay where they are, and their ids are never reused. Returns
        the files written, empty when nothing was closed.
        """
        with self._write():
            closing = [i for i in self.worklog.items if i.status in CLOSED]
            if not closing:
                return []
            written = write_archive(self.root, closing)
            gone = {i.id for i in closing}
            self.worklog.items = [i for i in self.worklog.items if i.id not in gone]
            # this object now answers for them too, without a reload
            for item in closing:
                self.worklog.archived[item.id] = (item, f"{(item.ended or item.created)[:7]}.yaml")
        return written

    # ---------- reading ----------

    # Named views for `show`. `current` is what `clarity-ctl status` prints — both
    # in-flight and next — and is reached through `status --json`, not by name.
    VIEWS = {
        "active": IN_FLIGHT,
        "next": FUTURE,
        "closed": CLOSED,
        "all": set(STATUSES),
    }
    # No `leases` view: who holds what is for agents, and status --json and
    # show <id> --json already carry it.
    SHOW_NAMES = [*VIEWS, "objective"]

    def query(self, name: str, arg: str | None = None) -> dict:
        views = {**self.VIEWS, "current": IN_FLIGHT | FUTURE}
        if name == "item":
            item, archive_file = self.worklog.lookup(self.resolve_id(arg))
            data = item.to_dict()
            if archive_file:
                data["archived"] = f"{ARCHIVE}/{archive_file}"
            held = self.leases().get(item.id)
            if held:
                data["lease"] = held
            kids = self.children_of(item.id)
            if kids:
                # the roll-up: each child's status, outcome, handoff and lease
                data["children"] = [self.child_summary(c) for c in kids]
            folder = self.folder_of(item)
            if folder and folder.is_dir():
                plans = self._plans(folder)
                if plans:
                    data["plans"] = plans
                git = self.git_state(item, folder)
                if git:
                    data["git"] = git
            return data
        if name == "objective":
            return self.worklog.objectives.to_dict()
        if name not in views:
            raise ClarityError(
                f"unknown view {name!r}; try: {', '.join(self.SHOW_NAMES)}, or an id",
                code=4,
            )
        return {"items": [i.to_dict() for i in self.worklog.with_status(views[name])]}

    def git_state(self, item: Item, folder: Path) -> list[dict]:
        """Per repo, what an agent would otherwise shell out to git for: where the
        worktree is, whether it is its own or a link to the repo's main checkout
        (`shared` — edits there land in that checkout), what the branch follows, how
        far it sits from it, and how much is uncommitted. Live, never stored."""
        if not item.branch:
            return []
        out = []
        for repo, link in self._targets(item, folder):
            if not repo.is_dir():
                out.append({"repo": self._repo_key(repo), "worktree": str(link),
                            "exists": link.exists(), "missing": True})
                continue
            base = self.base_of(item, repo)
            entry: dict = {
                "repo": self._repo_key(repo),
                "worktree": str(link),
                "exists": link.exists(),
                "shared": link.is_symlink(),
                "base": base,
                "checkout": gitops.current_branch(repo),
            }
            if base and base != item.branch and gitops.branch_exists(repo, item.branch):
                try:
                    entry["ahead"], entry["behind"] = gitops.ahead_behind(
                        repo, item.branch, base)
                except ClarityError:
                    pass
            if entry["exists"]:
                entry["dirty"] = len(gitops.is_dirty(link))
            out.append(entry)
        return out

    def missing_warnings(self) -> list[str]:
        """One line per repo the worklog points at whose folder is gone — listed, or
        branched by an epoch in flight. Every git call there would fail, so every
        command says which one up front instead of tripping over it later."""
        using: dict[str, list[int]] = {r: [] for r in self.worklog.repos}
        for item in self.worklog.items:
            if item.status in IN_FLIGHT:
                for r in item.repos or []:
                    using.setdefault(r, []).append(item.id)
        out = []
        for rel, ids in using.items():
            if (self.root / rel).is_dir():
                continue
            fixes = ["restore it"]
            if rel in self.worklog.repos:
                fixes.append(f"stop branching it in new epochs: clarity-ctl repo remove {rel}")
            line = f"{rel} is gone from {self.root / rel} — {', or '.join(fixes)}"
            if ids:
                line += f" (epoch {', '.join(map(str, ids))} branches it)"
            out.append(line)
        return out

    def branches_root(self) -> bool:
        """The root is a repo, and one of code rather than clarity's state."""
        return gitops.is_repo(self.root) and not self.worklog.state_repo

    def view_text(self, name: str) -> str:
        """A `show` view as status draws it: the same tables, for just its groups."""
        titles = {"active": ["Active"], "next": ["Up next"], "closed": ["Closed", "Dropped"],
                  "all": list(render.GROUPS)}[name]
        return render.view_text(self.worklog.items, titles, self.leases(),
                                self.stale_map(), self.landed_map(),
                                kids=self.children_by_parent())

    def status_text(self, show_all: bool = False, oldest_first: bool = False,
                    landed: dict | None = None, limit: int = render.CLOSED_LIMIT,
                    children: bool = False) -> str:
        return render.status_text(
            self.worklog.objectives, self.worklog.items, show_all, self.leases(),
            branches=self.branches_root() or bool(self.worklog.repos),
            stale=self.stale_map(),
            landed=self.landed_map() if landed is None else landed,
            oldest_first=oldest_first,
            limit=limit,
            kids=self.children_by_parent(),
            children=children,
        )

    def children_by_parent(self) -> dict[int, list[Item]]:
        out: dict[int, list[Item]] = {}
        for item in sorted(self.worklog.all_items(), key=lambda i: id_key(i.id)):
            if item.parent is not None:
                out.setdefault(item.parent, []).append(item)
        return out
