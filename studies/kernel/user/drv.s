; A user-level driver for the timer: wait for its interrupt (signal bit
; 0), count it, wait again. The nucleus acknowledges the device.
        .include "sys.inc"
        .org 0
start:  MOV  r8, #0
.loop:  SWI  #SYS_WAIT
        INC  r8
        BRA  .loop
