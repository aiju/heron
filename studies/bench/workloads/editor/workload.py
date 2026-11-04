"""A text editor's core at work: a C file in a gap buffer, a scripted
session of edits, and the window redrawn after every key.

It stands for the editors Heron runs (Heron Mini's editor app, an editor
on Fen): the colouring is the Mini editor's, and its redisplay idea, rows
redrawn only when what they show changed. The text is a gap buffer, as in
Emacs; a line index with the colouring's state at each line's start
finds lines and colours the window without scanning from the top; edits
within a line shift the index lazily, a pending offset for the lines
after it.

The session (session.c) is a script of moves, typing (a character and a
frame at a time, Enter indenting), deletes, line kills and joins,
searches, a replace over the whole file and undos. A frame lays out the
80 x 30 window from the lines that changed (tabs expanded, long lines
clipped, C's colours: keywords, comments over several lines, strings,
numbers, preprocessor lines), compares each row with the screen, and
sends the cells that differ to the terminal as escape sequences, which
are hashed. The file (gen_source.py) is a made-up C module with tabs,
block comments, strings and lines wider than the window.

STEPS is how many of the script's commands run (three at test), PASSES
how many times (each from elsewhere in the file), ROWS the
window's height (eight at test) and FUNCS the file's size (about 10 KB at
`small`, 40 KB at `ref`, five passes).

Where the time goes (`small`): a fifth comparing laid-out rows with the
screen (draw_row), a quarter laying rows out (copying the line out of
the gap buffer, colouring it, expanding tabs), an eighth moving the gap
(memmove, memcpy), and the rest in counting lines at load and in the
replace, the search, the status line's sprintf, and hashing what goes to
the terminal (about 6%).
"""

from . import gen_source

TITLE = "a text editor: gap buffer, C colouring, redisplay, undo"
PART = "c"
CATEGORY = "apps"
SOURCES = ["session.c", "edit.c", "view.c", "syntax.c", "gap.c"]
SIZES = {"test": {"STEPS": 3, "ROWS": 8, "FUNCS": 1},
         "small": {"STEPS": 1000, "ROWS": 30, "FUNCS": 15},
         "ref": {"STEPS": 1000, "ROWS": 30, "FUNCS": 60, "PASSES": 5}}


def data(p):
    return {"source": gen_source.source(p["FUNCS"])}
