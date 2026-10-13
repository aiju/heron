/* bst: insert 100 random keys (xorshift16 seeded with 0xBEEF) into a binary
   search tree built from a static pool of nodes, walk it in order printing
   every 10th key and checking the order, and print the tree's height. Equal
   keys go right. */
#include <stdio.h>

struct node {
    unsigned key;
    struct node *left, *right;
};

static struct node pool[100];
static int used;
static unsigned last, visited, ordered = 1;

static void insert(struct node **root, unsigned key)
{
    struct node *n = &pool[used++];
    n->key = key;
    n->left = n->right = 0;
    while (*root)
        root = key < (*root)->key ? &(*root)->left : &(*root)->right;
    *root = n;
}

static void walk(struct node *n)
{
    if (!n)
        return;
    walk(n->left);
    if (visited % 10 == 0)
        printf(" %u", n->key);
    if (visited && n->key < last)
        ordered = 0;
    last = n->key;
    visited++;
    walk(n->right);
}

static int height(struct node *n)
{
    int l, r;
    if (!n)
        return 0;
    l = height(n->left);
    r = height(n->right);
    return 1 + (l > r ? l : r);
}

int main(void)
{
    struct node *root = 0;
    unsigned x = 0xbeef;
    int i;
    for (i = 0; i < 100; i++) {
        x ^= (x << 7) & 0xffff;
        x ^= x >> 9;
        x ^= (x << 8) & 0xffff;
        insert(&root, x);
    }
    printf("every 10th key in order:");
    walk(root);
    printf("\nvisited %u nodes, in order: %s\n", visited, ordered ? "yes" : "no");
    printf("height: %d\n", height(root));
    return 0;
}
