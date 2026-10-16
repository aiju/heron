/* ktspin: ktest's child that never ends, until ktest ends it. */
int main(void)
{
    volatile int i = 0;
    for (;;)
        i++;
}
