/* Character classes (ASCII) for the C library. */

#include <ctype.h>

int isdigit(int c) { return (unsigned)(c - '0') < 10; }
int isxdigit(int c) { return isdigit(c) || (unsigned)((c | 32) - 'a') < 6; }
int isalpha(int c) { return (unsigned)((c | 32) - 'a') < 26; }
int isalnum(int c) { return isalpha(c) || isdigit(c); }
int isspace(int c) { return c == ' ' || (unsigned)(c - 9) < 5; }
int isupper(int c) { return (unsigned)(c - 'A') < 26; }
int islower(int c) { return (unsigned)(c - 'a') < 26; }
int isprint(int c) { return (unsigned)(c - 32) < 95; }
int iscntrl(int c) { return (unsigned)c < 32 || c == 127; }
int ispunct(int c) { return isprint(c) && !isalnum(c) && c != ' '; }
int toupper(int c) { return islower(c) ? c - 32 : c; }
int tolower(int c) { return isupper(c) ? c + 32 : c; }
