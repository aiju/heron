/* The keyboard and the mouse. RFC 0041 has neither; in the simulations
   they come over UART 1 as packets (a header byte with bit 7 set, then
   data bytes without), standing for a keyboard and mouse controller:

     0x80 k            key k down
     0x81 k            key k up
     0x82 b xl xh yl yh   the mouse at (x, y), 7 bits a byte, buttons b
                       (bit 0 left, 1 right, 2 middle)

   A key is its unshifted character for the printable ones, else one of
   the K_ codes below; the driver applies Shift and Ctrl. */

#ifndef INPUT_H
#define INPUT_H

#define K_BACKSPACE 8
#define K_TAB       9
#define K_ENTER     13
#define K_UP        0x11
#define K_DOWN      0x12
#define K_LEFT      0x13
#define K_RIGHT     0x14
#define K_SHIFT     0x15
#define K_CTRL      0x16
#define K_ALT       0x17
#define K_ESC       27
#define K_PGUP      0x1C
#define K_PGDN      0x1D
#define K_HOME      0x1E
#define K_END       0x1F
#define K_DEL       0x7F
#define K_F1        1           /* F1-F7 are 1-7 */

enum { EV_NONE, EV_KEY, EV_KEYUP, EV_MOUSE };

typedef struct {
    int type;
    int key;                    /* EV_KEY, EV_KEYUP */
    int ch;                     /* EV_KEY: the character it types (Shift and Ctrl applied), or 0 */
    int mods;                   /* M_SHIFT, M_CTRL, M_ALT as they were */
    int x, y, buttons;          /* the mouse, for every event */
} Event;

#define M_SHIFT 1
#define M_CTRL  2
#define M_ALT   4

void input_init(void);              /* UART 1's interrupt on */
int input_next(Event *e);           /* the next event, 1; or 0 */
int key_down(int k);                /* whether key k is down now */
extern volatile int mouse_x, mouse_y, mouse_buttons;

#endif
