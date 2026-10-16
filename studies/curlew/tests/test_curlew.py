"""Curlew: the front end's errors, the reference interpreter against the
expected output, and the compiled programs on the draft 2 simulator
against it too, as built, with draft 2's tagged operations, and with a
small heap."""

import unittest

from heron.studies.curlew import frontend, machine, reference, testing
from heron.studies.curlew.lexer import CurlewError


def check(text):
    frontend.check(text)


class FrontEnd(unittest.TestCase):
    def error(self, text, fragment):
        with self.assertRaises(CurlewError) as cm:
            check(text)
        self.assertIn(fragment, str(cm.exception))

    def test_type_errors(self):
        self.error('main s = 1 + "x"', "is applied to String")
        self.error("main s = show (\\x -> x)", "no instance for Show")
        self.error("f :: a -> a\nf x = x + 1\nmain s = s", "should be a -> a")
        self.error("main s = nowhere s", "isn't defined")
        self.error("g x = x x\nmain s = s", "infinite type")
        self.error("main = 3", "main should be String -> String")

    def test_layout(self):
        check("main s = case s of\n  [] -> \"empty\"\n  (c:_) -> [c]\n  where x = 1\n")
        check("main s = let a = 1\n             b = 2\n         in show (a + b)\n")
        check("main s = show (f 3) where\n  f x | x > 2 = 1\n      | otherwise = 2\n")
        check("main s = do { x <- [s]; return 'a' }\n")

    def test_classes(self):
        check("class C a where\n  m :: a -> Int\n  m _ = 1\ninstance C Bool\nmain s = show (m True)\n")
        self.error("class C a where\n  m :: a -> Int\nmain s = show (m 'x')\n", "no instance for C Char")

    def test_defaulting(self):
        check("main s = show []\n")


class Reference(unittest.TestCase):
    """The reference interpreter writes the expected output: it must still
    produce it."""

    def test_programs(self):
        for p in testing.programs():
            if p.name == "life":
                continue        # half a minute on the interpreter
            with self.subTest(p.name):
                self.assertEqual(reference.run(p.text, p.input), p.expected)


class Machine(unittest.TestCase):
    def run_all(self, features):
        for p in testing.programs():
            with self.subTest(p.name, features=features):
                r = machine.run(p.text, p.input, features)
                self.assertIsNone(r.error)
                if r.output != p.expected:
                    self.fail(testing.diff(r.output, p.expected))

    def test_as_built(self):
        self.run_all(())

    def test_tagged(self):
        self.run_all(("tagged",))

    def test_small_heap(self):
        """32 KB halves: the collector runs at many more of the heap
        checks, the merged ones too."""
        for p in testing.programs(["hamming", "parser", "peano", "apply", "laziness", "features"]):
            for features in ((), ("tagged",)):
                with self.subTest(p.name, features=features):
                    r = machine.run(p.text, p.input, features, heap_size=0x8000)
                    self.assertIsNone(r.error)
                    self.assertGreater(r.stats()["gc_count"], 0)
                    if r.output != p.expected:
                        self.fail(testing.diff(r.output, p.expected))


if __name__ == "__main__":
    unittest.main()
