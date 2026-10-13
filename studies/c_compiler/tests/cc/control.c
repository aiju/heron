/* Control flow: loops, switch, goto, short-circuit, conditional expressions. */
#include <stdio.h>

static int calls;
static int side(int v) { calls++; return v; }

static const char *name(int n)
{
    switch (n) {
    case 0: return "zero";
    case 1: return "one";
    case 2: return "two";
    case 3: return "three";
    case 4: return "four";
    case 5: return "five";
    case 6: return "six";
    case 7: return "seven";
    default: return "many";
    }
}

static int sparse(int n)
{
    switch (n) {
    case -1000: return 1;
    case 3: return 2;
    case 77: return 3;
    case 1000: return 4;
    case 5000: return 5;
    case 123456: return 6;
    case 99: return 7;
    case 100: return 8;
    }
    return 0;
}

static int fall(int n)
{
    int r = 0;
    switch (n) {
    case 1:
        r += 1;
    case 2:
        r += 10;
        break;
    case 3:
        r += 100;
    default:
        r += 1000;
    case 4:
        r += 10000;
    }
    return r;
}

int main(void)
{
    int i, j, k, sum = 0;
    for (i = 0; i < 10; i++)
        printf("%s ", name(i));
    printf("\n");
    for (i = -1001; i < 123460; i += 7)
        sum += sparse(i);
    printf("sparse %d %d %d %d\n", sum, sparse(77), sparse(123456), sparse(5000));
    for (i = 0; i < 6; i++)
        printf("fall(%d) = %d\n", i, fall(i));
    /* nested loops with break and continue */
    sum = 0;
    for (i = 0; i < 20; i++) {
        if (i % 3 == 0)
            continue;
        for (j = 0; j < 20; j++) {
            if (j > i)
                break;
            if ((i + j) % 5 == 0)
                continue;
            sum += i * j;
        }
    }
    printf("nested %d\n", sum);
    /* while and do-while */
    k = 0;
    i = 100;
    while (i > 1) {
        i = i % 2 ? 3 * i + 1 : i / 2;
        k++;
    }
    printf("collatz %d\n", k);
    i = 0;
    do {
        i += 3;
    } while (i < 50);
    printf("do %d\n", i);
    /* goto */
    i = 0;
again:
    i++;
    if (i < 10)
        goto again;
    printf("goto %d\n", i);
    /* short circuit */
    calls = 0;
    k = 0;
    for (i = 0; i < 10; i++) {
        if (side(i & 1) && side(i & 2))
            k++;
        if (side(i > 5) || side(i == 2))
            k += 10;
        k += !side(i) + (side(i) ? 100 : 1000);
    }
    printf("short %d %d\n", k, calls);
    j = 0;
    for (i = -5; i < 5; i++)
        j = j * 3 + (i < 0 ? -i : i) + (i && j) + (i || 0);
    printf("cond %d\n", j);
    /* loops counting down, unsigned */
    {
        unsigned u;
        sum = 0;
        for (u = 10; u-- > 0;)
            sum += u;
        printf("down %d\n", sum);
    }
    return 0;
}
