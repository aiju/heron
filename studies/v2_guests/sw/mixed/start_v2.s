; C start-up (draft 2) for a user process under mixed.py's kernel: the
; stack at the top of the first megabyte (the kernel maps pages there as
; they are touched), main, then SWI #0, which ends the process.

__start:
        MOV  sp, #0x100000
        CALL _main
_exit:
_abort: SWI  #0
        BRA  _exit
