; Fen's C start-up code. The kernel starts a program's first thread at
; __start with r1 pointing at its startup block (fen/abi.h), and sp at the
; top of its stack.
;
; It also lays the program out for page protection: the linker puts the
; text after the near data, and this file, linked first, starts the text
; on a page (__text_start) and the far data after it on another
; (__text_end), so the loader can map the text's pages read-only and
; executable and the rest writable but not executable.

        .global __start, __text_start, __text_end
        .far ___libc_start, __text_end

        .text
        .align 4096
__text_start:
__start:
        MOV  r0, #__text_end            ; (keeps the marker in the link)
        CALL ___libc_start              ; __libc_start(block): main, then exit
.hang:  BRA  .hang

        .section .fardata.__text_end
        .align 4096
__text_end:
        .word 0
