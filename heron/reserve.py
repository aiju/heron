"""Reserving a report's or RFC's number on main (RFC 0000): push a stub of
the document, and the index with it, straight to main. A push only
succeeds if main hasn't moved since it was fetched, so the number it
carries is the reserving session's alone. If main moved, someone else got
there first, and it tries again with the next number."""

import datetime
import os
import shutil
import subprocess

from . import ROOT, meta

ATTEMPTS = 5


def git(*args, cwd=ROOT, check=True):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=check)


def stub(number, kind, title, date, commit, branch):
    """The stub that holds a number on main until the document replaces it."""
    heading = "Report" if kind == "report" else "RFC"
    where = f" on the branch `{branch}`" if branch else ""
    return (f"---\nnumber: {number}\ntype: {kind}\ntitle: {title}\nstatus: draft\n"
            f"date: {date}\ncontext:\n  commit: {commit}\n---\n\n"
            f"# {heading} {number:04d}: {title}\n\n"
            f"Reserved; being written{where}.\n")


def reserve(kind, slug, title, root=ROOT):
    """Push a stub for a new document to origin's main: returns its path
    relative to the root. Raises RuntimeError if the push is refused for
    any reason but main having moved."""
    if kind not in meta.STATUSES:
        raise RuntimeError(f"type {kind!r} isn't one of {', '.join(meta.STATUSES)}")
    if not meta.REPORT_RE.match(f"0000-{kind}-{slug}"):
        raise RuntimeError(f"slug {slug!r}: only a-z, 0-9 and -")
    if not title or "#" in title or "\n" in title:
        raise RuntimeError("the title can't be empty or have # in it (the front matter's comments)")
    branch = git("rev-parse", "--abbrev-ref", "HEAD", cwd=root).stdout.strip()
    branch = None if branch in ("HEAD", "main") else branch
    tree = os.path.join(root, "build", "reserve")
    for _ in range(ATTEMPTS):
        git("fetch", "origin", "main", cwd=root)
        base = git("rev-parse", "origin/main", cwd=root).stdout.strip()
        if os.path.exists(tree):
            git("worktree", "remove", "--force", tree, cwd=root, check=False)
            shutil.rmtree(tree, ignore_errors=True)
        git("worktree", "prune", cwd=root)
        git("worktree", "add", "--detach", tree, base, cwd=root)
        try:
            folder = os.path.join(tree, "reports")
            number = max(int(meta.REPORT_RE.match(os.path.basename(p)).group(1))
                         for p, _ in meta.reports(folder)) + 1
            rel = f"reports/{number:04d}-{kind}-{slug}.md"
            date = datetime.date.today().isoformat()
            with open(os.path.join(tree, rel), "w") as f:
                f.write(stub(number, kind, title, date, base[:7], branch))
            with open(os.path.join(folder, "README.md"), "w") as f:
                f.write(meta.index(folder))
            git("add", rel, "reports/README.md", cwd=tree)
            git("commit", "-q", "-m", f"Reserve {kind} {number:04d}: {title}", cwd=tree)
            push = git("push", "origin", "HEAD:refs/heads/main", cwd=tree, check=False)
            if push.returncode == 0:
                return rel
            git("fetch", "origin", "main", cwd=root)
            if git("rev-parse", "origin/main", cwd=root).stdout.strip() == base:
                raise RuntimeError(f"couldn't push to main:\n{push.stderr.strip()}")
        finally:
            git("worktree", "remove", "--force", tree, cwd=root, check=False)
    raise RuntimeError(f"main moved under every one of {ATTEMPTS} attempts")
