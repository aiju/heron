/* An editing session: a C file opened, and a script of what someone
   working on it does, each command followed by a frame, as the editor
   redraws after every key. Typed text is typed a character at a time,
   a frame after each.

   The commands, one a line:
       up N, down N, left N, right N    the caret's moves
       word N, back N                   by words, as vi's w and b
       home, end, goto N, pgdn N, pgup N
       type TEXT                        typed: \t a tab, \n Enter (indented)
       bs N, del N, kill, join          deleting
       find TEXT, next                  searching, the match lit
       replace A B                      every A by B
       undo                             the last command undone

   The file is linked in by the harness (workload.py makes it). STEPS
   commands of the script are run, PASSES times: each pass after the
   first starts with a goto elsewhere in the file, as a session moves
   from one function to the next. */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "bench.h"
#include "ed.h"

extern const unsigned char source[];
extern unsigned source_len;

static const char *const script[] = {
    "down 9", "end", "type  //", "type  held", "find printk", "word 2", "type [%d]", "kill",
    "undo", "pgdn 1", "down 22", "end", "type  /* XXX */", "up 8", "end", "bs 3", "type 0;",
    "join", "replace printk kprintf", "goto 66", "end", "type  ok",
};

/* the number after a command's name */
static int arg(const char *s)
{
    int n = atoi(s);
    return n > 0 ? n : 1;
}

/* two words, a and b, of "a b": 0 if there aren't two */
static int words(const char *s, char *a, char *b)
{
    const char *sp = strchr(s, ' ');
    int n = sp ? sp - s : 0;
    if (n == 0 || n > 63 || !sp[1] || strlen(sp + 1) > 63)
        return 0;
    memcpy(a, s, n);
    a[n] = 0;
    strcpy(b, sp + 1);
    return 1;
}

/* text typed: a tab is Tab, a newline Enter */
static void type(Ed *e, const char *s)
{
    for (; *s; s++) {
        if (*s == '\n')
            ed_enter(e);
        else
            ed_type(e, *s);
        frame(e);
    }
}

static void run(Ed *e, const char *cmd)
{
    char name[16], a[64], b[64];
    const char *rest;
    int k;
    for (k = 0; cmd[k] && cmd[k] != ' ' && k < 15; k++)
        name[k] = cmd[k];
    name[k] = 0;
    rest = cmd[k] ? cmd + k + 1 : cmd + k;
    ed_begin(e);
    if (!strcmp(name, "type")) {
        type(e, rest);
        return;                 /* framed as it went */
    }
    if (!strcmp(name, "up")) ed_up(e, arg(rest));
    else if (!strcmp(name, "down")) ed_down(e, arg(rest));
    else if (!strcmp(name, "left")) ed_left(e, arg(rest));
    else if (!strcmp(name, "right")) ed_right(e, arg(rest));
    else if (!strcmp(name, "word")) ed_word(e, arg(rest));
    else if (!strcmp(name, "back")) ed_back_word(e, arg(rest));
    else if (!strcmp(name, "home")) ed_home(e);
    else if (!strcmp(name, "end")) ed_end(e);
    else if (!strcmp(name, "goto")) ed_goto(e, arg(rest));
    else if (!strcmp(name, "pgdn")) ed_page(e, arg(rest));
    else if (!strcmp(name, "pgup")) ed_page(e, -arg(rest));
    else if (!strcmp(name, "bs")) {
        for (k = arg(rest); k > 0; k--)
            ed_backspace(e);
    } else if (!strcmp(name, "del")) {
        for (k = arg(rest); k > 0; k--)
            ed_delete(e);
    } else if (!strcmp(name, "kill")) ed_kill_line(e);
    else if (!strcmp(name, "join")) ed_join(e);
    else if (!strcmp(name, "find")) ed_find(e, rest);
    else if (!strcmp(name, "next")) ed_find(e, e->find);
    else if (!strcmp(name, "replace") && words(rest, a, b))
        ed_replace(e, a, b);
    else if (!strcmp(name, "undo")) ed_undo(e);
    else
        sprintf(e->msg, "%s: unknown", name);
    frame(e);
}

#ifndef PASSES
#define PASSES 1
#endif

int main(void)
{
    static Ed e;
    char cmd[24];
    int i, pass, n = sizeof script / sizeof script[0];
    ed_open(&e, "ring.c", (const char *)source, source_len);
    view_init();
    frame(&e);
    for (pass = 0; pass < PASSES; pass++) {
        if (pass > 0) {
            sprintf(cmd, "goto %d", 1 + pass * 97 % (e.nlines > 100 ? e.nlines - 100 : 1));
            run(&e, cmd);
        }
        for (i = 0; i < STEPS && i < n; i++)
            run(&e, script[i]);
    }
    bench_report("frames", frames);
    bench_report("rows", rows_drawn);
    bench_report("bytes", term_bytes);
    bench_report("screen", term_hash);
    bench_report("lines", e.nlines);
    bench_report("length", gap_len(&e.g));
    bench_report("undo", e.nundo);
    return 0;
}
