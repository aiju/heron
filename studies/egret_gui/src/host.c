/* The GUI's hooks in Egret's VM, for a build on the host (host.py): no
   screen, and of the GUI's primitives only gui_stats; output to stdout
   only. It runs the parts of the desktop that don't draw, such as
   Egretica's algebra, with the desktop's memory map. */

#include "egret.h"

#define ITEMS(l) (&F(F(l, L_ITEMS), 0))     /* as in prims.c */

/* as gui_prims.c's: [permanent space used, its size, heap used, its size,
   collections] */
static Value p_stats(Value *args, int argc)
{
    int v[5], i;
    Value l = make_list(5);
    v[0] = perm_hp - PERM_LO;
    v[1] = PERM_HI - PERM_LO;
    v[2] = SEMI_SIZE - (hlimit - hp);
    v[3] = SEMI_SIZE;
    v[4] = gc_count;
    for (i = 0; i < 5; i++)
        ITEMS(l)[i] = MKINT(v[i]);
    F(l, L_SIZE) = MKINT(5);
    return l;
}

static const PrimDef defs[] = {
    { "Object", "gui_stats", 0, p_stats, 0 },
    { 0, 0, 0, 0, 0 }
};

const PrimDef *gui_prim_defs(void) { return defs; }
void gui_out_char(int c) { (void)c; }
void gui_boot(const unsigned char *input, unsigned n) { (void)input; (void)n; }
int gui_compiling(const char *source, int line) { (void)source; return line + 1000000; }
