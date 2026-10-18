/* The level: 8 rows of 240 tiles, written as text in segments of 20
   columns. Row 6 is the ground's grass and row 7 its dirt; the
   playfield's top row is level with the hills band's bottom, so a fox
   standing on row 2 and jumping reaches the mountains and the sky.

     ' ' empty   '#' grass  '[' ']' grass edges  '=' dirt   'B' bricks
     '?' a star block (a coin from below)  'o' a coin  '(' ')' a bush
     '*' flowers  '|' a fence  '-' a plank (stands from above only)
     'S' stone   '^' spikes  'P' 'F' the flag pole   'e' a beetle
     '{' '}' '<' '>' 't' 'T' a tree in the background, 2 x 3 tiles */

#include "game.h"

static const char *const text[ROWS] = {
    /* 0         20        40        60        80        100       120       140       160       180       200       220 */
    "                    " "                    " "                    " "                    "
    "                    " "                    " "                    " "                    "
    "                    " "                    " "                    " "            F       ",
    "                    " "       o o o        " "                    " "                    "
    "         ooo        " "                    " "                    " "                    "
    "                    " "                    " "        ?           " "            P       ",
    "                    " "        e           " "        ooo         " "                    "
    "       BBBBBB       " "                    " "       o  o  o      " "                    "
    "     o     o        " "      ooooo         " "                    " "            P       ",
    "          ?  {}     " "     BB?BB          " "           {}       " "      SSS  o        "
    "              {}    " "   ?   ?B?          " "                    " "                    "
    "                    " "     BB?BB          " "  ooo               " "            P       ",
    "             <>     " "                    " "           <>       " "    SSSSS ooo       "
    "  ----        <>    " "                    " "     ----------     " "     BBBBBB         "
    "        S           " "                    " "  S     ooo         " "            P       ",
    " ||| *    () tT*  ()" "  *              *  " "    *      tT  |||  " "  SSSSSSS     e     "
    "         ()   tT *  " "  e      *   e   () " "                    " " ()  B    B   |||   "
    "        S       e   " " *     e      ()    " "  SS    SSS    e    " "  *   ()    P    *  ",
    "####################" "####################" "#####]   [##########" "####################"
    "####################" "####################" "####]^^^^^^^^^^[####" "####################"
    "###]    S    [######" "####################" "####################" "####################",
    "====================" "====================" "======   ===========" "===================="
    "====================" "====================" "=====SSSSSSSSSS=====" "===================="
    "====    S    =======" "====================" "====================" "====================",
};

unsigned char level[ROWS][LEVEL_W + 1];
static int tile_of(char ch)
{
    switch (ch) {
    case '#': return T_GRASS;
    case '[': return T_GRASS_L;
    case ']': return T_GRASS_R;
    case '=': return T_DIRT;
    case 'B': return T_BRICK;
    case '?': return T_BLOCK;
    case 'U': return T_USED;
    case 'o': return T_COIN;
    case '(': return T_BUSH_L;
    case ')': return T_BUSH_R;
    case '*': return T_FLOWER;
    case '|': return T_FENCE;
    case '-': return T_PLANK;
    case 'S': return T_STONE;
    case '^': return T_SPIKES;
    case 'P': return T_POLE;
    case 'F': return T_FLAG;
    case '{': return T_TREE_TL;
    case '}': return T_TREE_TR;
    case '<': return T_TREE_ML;
    case '>': return T_TREE_MR;
    case 't': return T_TREE_BL;
    case 'T': return T_TREE_BR;
    default: return T_EMPTY;
    }
}

int level_nbugs;
signed char level_bug[24][2];

void level_init(void)
{
    int r, c;
    level_nbugs = 0;
    for (r = 0; r < ROWS; r++) {
        for (c = 0; c < LEVEL_W; c++) {
            char ch = text[r][c];
            if (ch == 'e' && level_nbugs < 24) {
                level_bug[level_nbugs][0] = c;
                level_bug[level_nbugs][1] = r;
                level_nbugs++;
            }
            level[r][c] = tile_of(ch);
        }
        level[r][LEVEL_W] = T_EMPTY;
    }
}

int tile_solid(int t)
{
    return t == T_GRASS || t == T_GRASS_L || t == T_GRASS_R || t == T_DIRT || t == T_BRICK ||
           t == T_BLOCK || t == T_USED || t == T_STONE || t == T_SPIKES;
}

int tile_top(int t)
{
    return t == T_PLANK;
}
