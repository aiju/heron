/* Egret's memory map for the GUI build (egret.h includes this with
   EGRET_GUI). The VM, the graphics library and the fonts don't fit below
   0x30000 (they come to about 310 KB), and the desktop's source doesn't
   fit in 32 KB of console input (it's 96 KB here), so everything moves
   up, the permanent space grows to 224 KB (the desktop and what the
   Workspaces compile), and the semispaces shrink to 120 KB. The screen
   isn't here: it's in VRAM, outside the 1 MB (gui.h).

     0x00000  the image: the VM, the graphics library, the fonts
     INPUT    the console input: the desktop's source
     PERM     classes, methods, bytecode, symbols, literals
     SCRATCH  the compiler's syntax trees
     VSTACK   the value stack
     FRAMES   the frame stack
     SEMI     the heap: two semispaces
     0xEE000  the C stack, up to the top of RAM */

#define RAM_SIZE   0x100000
#define INPUT_LO   0x50000
#define INPUT_HI   0x68000
#define PERM_LO    0x68000
#define PERM_HI    0xA0000
#define SCRATCH_LO 0xA0000
#define SCRATCH_HI 0xA8000
#define VSTACK_LO  0xA8000
#define VSTACK_HI  0xAE000
#define FRAMES_LO  0xAE000
#define FRAMES_HI  0xB2000
#define SEMI_LO    0xB2000
#define SEMI_SIZE  0x1E000
#define SEMI_HI    (SEMI_LO + 2 * SEMI_SIZE)
