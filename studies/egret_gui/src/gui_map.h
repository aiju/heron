/* Egret's memory map for the GUI build (egret.h includes this with
   EGRET_GUI). The VM, the graphics library and the fonts don't fit below
   0x30000 (they come to about 316 KB), so everything moves up. The
   console input (the desktop's source, about 170 KB) doesn't fit in RAM
   as well, so it goes in VRAM, past the screen and Gadgets' layers
   (gui.h): the compiler reads it from there, and so does the Browser.
   That leaves 368 KB for the permanent space (the desktop, Egretica, and
   what the Workspaces compile). The semispaces shrink to 120 KB, and the
   C stack to 24 KB (booting, the deepest it goes, takes about 3 KB).

     0x00000  the image: the VM, the graphics library, the fonts
     PERM     classes, methods, bytecode, symbols, literals
     SCRATCH  the compiler's syntax trees
     VSTACK   the value stack
     FRAMES   the frame stack
     SEMI     the heap: two semispaces
     0xFA000  the C stack, up to the top of RAM
     INPUT    the console input, in VRAM */

#ifdef __HERON__
#define RAM_SIZE   0x100000
#else
/* on the host (host.py) memory is an array, big enough to have the input
   where it is on the machine */
#define RAM_SIZE   0x1100000
#endif
#define INPUT_LO   0x10C0000
#define INPUT_HI   0x1100000
#define PERM_LO    0x50000
#define PERM_HI    0xAC000
#define SCRATCH_LO 0xAC000
#define SCRATCH_HI 0xB4000
#define VSTACK_LO  0xB4000
#define VSTACK_HI  0xBA000
#define FRAMES_LO  0xBA000
#define FRAMES_HI  0xBE000
#define SEMI_LO    0xBE000
#define SEMI_SIZE  0x1E000
#define SEMI_HI    (SEMI_LO + 2 * SEMI_SIZE)
