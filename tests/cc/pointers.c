/* Arrays, pointers, strings and function pointers. */
#include <stdio.h>
#include <string.h>

int grid[5][7];
char text[] = "the quick brown fox jumps over the lazy dog";

static int add(int a, int b) { return a + b; }
static int mul(int a, int b) { return a * b; }
static int sub(int a, int b) { return a - b; }

static int apply(int (*f)(int, int), int a, int b) { return f(a, b); }

static void reverse(char *s)
{
    char *e = s + strlen(s) - 1;
    while (s < e) {
        char t = *s;
        *s++ = *e;
        *e-- = t;
    }
}

static int count(const char *s, int c)
{
    int n = 0;
    while (*s)
        if (*s++ == c)
            n++;
    return n;
}

static void swap(int *a, int *b)
{
    int t = *a;
    *a = *b;
    *b = t;
}

int main(void)
{
    int i, j, sum;
    int a[10], *p, *q;
    short sh[8];
    int (*ops[3])(int, int) = {add, mul, sub};
    char buf[64];
    char *words[4];
    for (i = 0; i < 5; i++)
        for (j = 0; j < 7; j++)
            grid[i][j] = i * 10 + j;
    sum = 0;
    for (i = 0; i < 5; i++)
        for (j = 0; j < 7; j++)
            sum += grid[i][j] * (j + 1);
    printf("grid %d %d %d\n", sum, grid[3][4], *(*(grid + 2) + 5));
    for (i = 0; i < 10; i++)
        a[i] = i * i;
    p = a;
    q = &a[9];
    printf("diff %d %d %d\n", (int)(q - p), *q, p[3]);
    sum = 0;
    for (p = a; p < a + 10; p++)
        sum += *p;
    printf("sum %d\n", sum);
    swap(&a[0], &a[9]);
    printf("swap %d %d\n", a[0], a[9]);
    for (i = 0; i < 8; i++)
        sh[i] = (short)(i * -1000);
    printf("short %d %d\n", sh[7], sh[3] + sh[4]);
    for (i = 0; i < 3; i++)
        printf("op%d %d %d\n", i, ops[i](7, 3), apply(ops[i], 10, 4));
    printf("count %d %d\n", count(text, 'o'), count(text, ' '));
    strcpy(buf, text);
    reverse(buf);
    printf("%s\n", buf);
    words[0] = "alpha";
    words[1] = "beta";
    words[2] = "gamma";
    words[3] = "delta";
    for (i = 0; i < 4; i++)
        printf("%s %d %c\n", words[i], (int)strlen(words[i]), words[i][1]);
    {
        char *s = text;
        int n = 0;
        while (*s) {
            if (*s == ' ')
                n++;
            s++;
        }
        printf("spaces %d, end at %d\n", n, (int)(s - text));
    }
    {
        int **pp, *arr[3], x = 1, y = 2, z = 3;
        arr[0] = &x;
        arr[1] = &y;
        arr[2] = &z;
        pp = arr;
        **pp = 10;
        *pp[2] += 30;
        printf("pp %d %d %d\n", x, y, z);
    }
    {
        unsigned char bytes[16];
        unsigned *w = (unsigned *)bytes;
        for (i = 0; i < 16; i++)
            bytes[i] = i * 17;
        printf("le %x %x\n", w[0], w[3]);
    }
    return 0;
}
