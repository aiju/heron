#include <unistd.h>
int main(void) { return sync() < 0; }
