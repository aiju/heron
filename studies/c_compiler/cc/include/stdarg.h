#ifndef _STDARG_H
#define _STDARG_H
/* Variadic arguments are all on the stack, one word each (char and short
   are promoted to int). Structs can't be passed through "...". */
typedef char *va_list;
#define va_start(ap, last) ((ap) = __builtin_va_start())
#define va_arg(ap, type) (*(type *)(((ap) += 4) - 4))
#define va_end(ap) ((void)0)
#define va_copy(dst, src) ((dst) = (src))
#endif
