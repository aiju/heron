"""heron reports reserve (RFC 0000), against a scratch remote: a number is
the next free one on main, a session that loses the race to main takes the
next, and a push refused for another reason stops."""

import os
import shutil
import subprocess
import tempfile
import unittest

from heron import meta, reserve

# Pushes clone c's commit to main once, while clone a's push is under way.
RACE = """#!/bin/sh
[ -e "{flag}" ] && exit 0
touch "{flag}"
env -u GIT_DIR -u GIT_WORK_TREE -u GIT_INDEX_FILE git -C "{c}" push -q origin HEAD:refs/heads/main
"""


def git(*args, cwd=None):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


class Reserve(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.remote = os.path.join(self.dir, "remote.git")
        git("init", "-q", "--bare", "-b", "main", self.remote)
        a = self.clone("a")
        self.write(os.path.join(a, "reports/0000-rfc-layout.md"), reserve.stub(0, "rfc", "Layout", "2026-10-14", "0000000", None))
        git("add", ".", cwd=a)
        git("commit", "-q", "-m", "start", cwd=a)
        git("push", "-q", "origin", "HEAD:refs/heads/main", cwd=a)

    def clone(self, name):
        path = os.path.join(self.dir, name)
        git("clone", "-q", self.remote, path)
        for key, value in (("user.name", "test"), ("user.email", "test@example.com"), ("commit.gpgsign", "false")):
            git("config", key, value, cwd=path)
        return path

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def main(self):
        """A fresh clone of main: its reports/ folder."""
        return os.path.join(self.clone(os.path.basename(tempfile.mkdtemp(dir=self.dir))), "reports")

    def test_next_free_number(self):
        a = os.path.join(self.dir, "a")
        git("checkout", "-q", "-b", "work", cwd=a)
        self.assertEqual(reserve.reserve("report", "first", "First", root=a), "reports/0001-report-first.md")
        folder = self.main()
        fm = meta.front_matter(os.path.join(folder, "0001-report-first.md"))
        self.assertEqual((fm["number"], fm["type"], fm["title"], fm["status"]), (1, "report", "First", "draft"))
        with open(os.path.join(folder, "0001-report-first.md")) as f:
            self.assertIn("`work`", f.read())
        with open(os.path.join(folder, "README.md")) as f:
            self.assertEqual(f.read(), meta.index(folder))
        # the session's own checkout is untouched
        self.assertFalse(os.path.exists(os.path.join(a, "reports", "0001-report-first.md")))
        self.assertEqual(git("status", "--porcelain", cwd=a), "")

    def test_losing_the_race(self):
        a = os.path.join(self.dir, "a")
        c = self.clone("c")
        self.write(os.path.join(c, "reports/0001-rfc-other.md"), reserve.stub(1, "rfc", "Other", "2026-10-14", "0000000", None))
        git("add", ".", cwd=c)
        git("commit", "-q", "-m", "other", cwd=c)
        hook = os.path.join(a, ".git", "hooks", "pre-push")
        self.write(hook, RACE.format(flag=os.path.join(self.dir, "raced"), c=c))
        os.chmod(hook, 0o755)
        self.assertEqual(reserve.reserve("rfc", "second", "Second", root=a), "reports/0002-rfc-second.md")
        folder = self.main()
        self.assertTrue(os.path.exists(os.path.join(folder, "0001-rfc-other.md")))
        with open(os.path.join(folder, "README.md")) as f:
            self.assertEqual(f.read(), meta.index(folder))

    def test_refused(self):
        a = os.path.join(self.dir, "a")
        hook = os.path.join(self.remote, "hooks", "pre-receive")
        self.write(hook, "#!/bin/sh\necho no pushes to main >&2\nexit 1\n")
        os.chmod(hook, 0o755)
        with self.assertRaisesRegex(RuntimeError, "no pushes to main"):
            reserve.reserve("report", "first", "First", root=a)

    def test_bad_names(self):
        a = os.path.join(self.dir, "a")
        for kind, slug, title in (("note", "x", "X"), ("rfc", "Bad_Slug", "X"), ("rfc", "x", "a # b")):
            with self.assertRaises(RuntimeError):
                reserve.reserve(kind, slug, title, root=a)


if __name__ == "__main__":
    unittest.main()
