/* Snake in draft 2 assembly (snake.s): this C only calls it, and tells
   it which build it is (in the blk variant it clears and copies with
   FILL and COPY). */

#ifdef GFX_BLK
int snake_blk = 1;
#else
int snake_blk = 0;
#endif

void snake_main(void);

int main(void)
{
    snake_main();
    return 0;
}
