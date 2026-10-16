/* The window system's protocol: what a program sends wsys (srv/wsys) to
 * have windows, draw in them and hear what happens to them. libgui
 * (fen/gui.h) wraps it.
 *
 * Drawing is batched: a program builds a list of commands in its own
 * memory and sends WS_DRAW with where it is; wsys reads it and draws each
 * command through the visible part of the window. Events wait in wsys
 * until the program asks for them with WS_EVENTS; wsys notifies the
 * program's port (with the bits it gave in WS_HELLO) when there are some.
 *
 * wsys keeps nothing of a window's content: whatever of a window comes
 * into view is filled with its background and becomes an EV_EXPOSE, which
 * the program answers by drawing that part again. */

#ifndef FEN_WSYS_H
#define FEN_WSYS_H

/* requests (word 0), and their words */
#define WS_HELLO 1      /* port, bits -> 0: the events' notification */
#define WS_OPEN 2       /* x, y (-1: wsys picks), content width, height, title, its length, background -> window */
#define WS_CLOSE 3      /* window */
#define WS_TITLE 4      /* window, title, its length */
#define WS_DRAW 5       /* window, commands, their length in words -> 0 */
#define WS_EVENTS 6     /* buffer, its size in events -> how many */
#define WS_INFO 7       /* -> 0; width, height, depth in words 1-3 */
#define WS_FONT 8       /* font, buffer for struct ws_font -> 0 */
#define WS_RESIZE 9     /* window, content width, height */
#define WS_RAISE 10     /* window */

/* fonts */
#define FONT_SANS 0
#define FONT_MONO 1

struct ws_font {
    int ascent, descent, height;
    int first, count;
    unsigned char adv[96];      /* the advance of characters 32-127 */
};

/* drawing commands: a word of op << 24 | length in words (this one
 * included), then the arguments. Coordinates are in the window's content,
 * colours 0xRRGGBB (the palette's nearest) or WS_PIXEL | a pixel value. */
#define WS_PIXEL 0x01000000
#define D_FILL 1        /* colour, x0, y0, x1, y1 */
#define D_FRAME 2       /* colour, x0, y0, x1, y1, thickness */
#define D_LINE 3        /* colour, x0, y0, x1, y1 */
#define D_TEXT 4        /* colour, font, x, baseline y, n, then n bytes (to a word) */
#define D_ELLIPSE 5     /* colour, x centre, y centre, a, b, filled */
#define D_SCROLL 6      /* x0, y0, x1, y1, dy: the rectangle's pixels up by dy; the strip
                           that opens is filled for the program to draw, and what couldn't
                           be copied (it was covered) is exposed */
#define D_CLIP 7        /* x0, y0, x1, y1: draw only there, until D_NOCLIP */
#define D_NOCLIP 8
#define D_PIXELS 9      /* x, y, w, h, then w x h bytes of pixel values (to a word) */
#define D_POLY 10       /* colour, n, then n (x, y) pairs */
#define D_TEXTBG 11     /* colour, background, font, x, baseline y, n, bytes: text on its cells */

/* events: 6 words */
#define EV_KEY 1        /* window, key (a character, or KEY_*), modifiers, down */
#define EV_MOUSE 2      /* window, x, y, buttons, what (MOUSE_*) */
#define EV_EXPOSE 3     /* window, x0, y0, x1, y1 */
#define EV_CLOSE 4      /* window: its close box was clicked */
#define EV_RESIZE 5     /* window, width, height */
#define EV_FOCUS 6      /* window, 1 got the keyboard, 0 lost it */

struct ws_event {
    int type, win, a, b, c, d;
};

#define MOUSE_DOWN 1
#define MOUSE_UP 2
#define MOUSE_MOVE 3
#define MOUSE_WHEEL 4   /* (a PS/2 mouse without a wheel never sends it) */

/* keys that aren't characters */
#define KEY_LEFT 0x101
#define KEY_RIGHT 0x102
#define KEY_UP 0x103
#define KEY_DOWN 0x104
#define KEY_HOME 0x105
#define KEY_END 0x106
#define KEY_PGUP 0x107
#define KEY_PGDN 0x108
#define KEY_INS 0x109
#define KEY_DEL 0x10A
#define KEY_F1 0x111    /* F1-F12 follow */

/* modifiers */
#define MOD_SHIFT 1
#define MOD_CTRL 2
#define MOD_ALT 4
#define MOD_META 8

#endif
