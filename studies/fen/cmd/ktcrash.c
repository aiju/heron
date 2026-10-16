/* ktcrash: ktest's child that writes through a null pointer. */
int main(void)
{
    *(volatile int *)0 = 1;
    return 0;
}
