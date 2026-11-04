"""Fen's shell utilities at work: pipelines of grep, sed, sort, uniq, tr,
cut, wc, head and tail over a system log, a document and a C source file.

It stands for the everyday work of Fen's shell and its commands
(studies/fen/cmd): the commands are Fen's, cut down and run as functions,
with in-memory files and pipes as buffers between them (sh.c parses the
script's lines, quotes, | < and >). A script of seventeen pipelines does
what someone looking through a machine's log, a document and a program
might type: the errors by daemon, the failed logins by user, McIlroy's
word count (tr | sort | uniq -c | sort -rn), a source file's identifiers
by frequency, the kernel's message shapes by sed substitution, a
password file sorted on a numeric field. The regular expressions
(regex.c) are grep's and ed's with + and ?, compiled to nodes and matched
by backtracking. Each pipeline's terminal output is hashed and reported.

The files (corpus.py) are made up by a deterministic generator: a system
log, prose with Zipf-distributed words, a C-like source file and a
password file. LOG, WORDS, FUNCS and USERS are their sizes, PIPES how
many of the script's lines run (three at test).

Where the time goes (ref): a quarter in sort (the key comparison, qsort's
calls through a function pointer and its byte-at-a-time swaps, strcmp
for ties), a sixth in the regular-expression matcher (the search loop,
the backtracking `here`), a quarter in moving lines from buffer to
buffer (buf_gets, strlen, memcpy), and the rest in cut, tr, wc and
uniq's loops and printf.
"""

from . import corpus

TITLE = "Fen's text utilities: grep, sed, sort, uniq, tr, cut in pipelines"
PART = "c"
CATEGORY = "text"
SOURCES = ["sh.c", "cmds.c", "grep.c", "regex.c", "sort.c"]
SIZES = {"test": {"PIPES": 3, "LOG": 12, "WORDS": 6, "FUNCS": 0, "USERS": 3},
         "ref": {"PIPES": 99, "LOG": 36, "WORDS": 110, "FUNCS": 2, "USERS": 10}}


def data(p):
    f = corpus.files(p)
    return {"f_syslog": f["syslog"], "f_notes": f["notes.txt"],
            "f_main": f["main.c"], "f_passwd": f["passwd"]}
