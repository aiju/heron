/* Initialized data: arrays, structs, pointers to data, string tables, statics. */
#include <stdio.h>

struct entry { const char *name; int value; struct entry *next; };

int counter = 5;
int zeros[100];
int primes[] = {2, 3, 5, 7, 11, 13, 17, 19, 23, 29};
char hello[] = "hello";
char letters[10] = "abc";
const char *names[] = {"red", "green", "blue", 0};
struct entry e3 = {"three", 3, 0};
struct entry e2 = {"two", 2, &e3};
struct entry e1 = {"one", 1, &e2};
int *pp = &primes[4];
char *mid = hello + 2;
short shorts[] = {-1, 2, -3, 400};
unsigned char ubytes[] = {200, 100, 255};
int matrix[3][3] = {{1, 2, 3}, {4, 5, 6}, {7, 8, 9}};
int partial[3][4] = {{1}, {2, 3}, {4, 5, 6}};
struct { int a; char b[3]; int c; } mixed = {1, "xy", 3};

static int next_id(void)
{
    static int id = 100;
    return id++;
}

int main(void)
{
    int i, s = 0;
    struct entry *e;
    for (i = 0; i < 100; i++)
        s += zeros[i];
    printf("%d %d\n", counter, s);
    for (i = 0; i < 10; i++)
        s += primes[i];
    printf("primes %d\n", s);
    printf("%s %s %d %d\n", hello, letters, (int)sizeof hello, (int)sizeof letters);
    for (i = 0; names[i]; i++)
        printf("%s ", names[i]);
    printf("\n");
    for (e = &e1; e; e = e->next)
        printf("%s=%d ", e->name, e->value);
    printf("\n");
    printf("%d %s\n", *pp, mid);
    printf("%d %d %d %d\n", shorts[0], shorts[3], ubytes[0], ubytes[2]);
    for (i = 0; i < 3; i++)
        printf("%d %d %d | %d %d %d %d\n", matrix[i][0], matrix[i][1], matrix[i][2],
               partial[i][0], partial[i][1], partial[i][2], partial[i][3]);
    printf("%d %s %d\n", mixed.a, mixed.b, mixed.c);
    i = next_id();
    s = next_id();
    printf("%d %d %d\n", i, s, next_id());
    counter += 10;
    printf("%d\n", counter);
    return 0;
}
