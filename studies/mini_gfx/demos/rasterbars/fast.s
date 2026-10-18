; The line interrupt without the runtime's dispatch: a handler of its own
; on the interrupt vector (fx_vector, demos/rasterbars/fx.c, patches the
; JMP at address 4 to come here), a software "copper": each line
; interrupt writes palette entry 0 with the colour of the line about to
; start, from a list a word a line. Anything that isn't a line interrupt
; (the beam's line is before the picture's table: the frame's end) goes
; on to the runtime's entry, fx_orig, as if this weren't here.
;
; The line is the beam's (P1; its line is the register's low half): the
; interrupt of picture line y comes in line T + y (T = 44), so the colour
; is rb_base[beam's line] with rb_base = the list - 44 words. A handler
; that starts late (a block instruction holds interrupts off for up to
; three lines, and interrupts that come meanwhile merge into one) writes
; the colour of the line under the beam then, so the lines after are
; right again; counting the interrupts instead would put every line after
; a merge a line or more off.
;
; The frame's end and the lines share one interrupt flag and one
; acknowledge (RFC 0042, 8). A line's interrupt taken late can still be
; pending when the frame ends and sets the flag again; acknowledging it
; then clears the frame's too, and the runtime never sees the frame
; (the main program's wait for it never ends). So the handlers
; acknowledge, then read the beam again: past the frame's end, they do
; the frame's work themselves (rb_frame).
;
; The flags need no saving: the interrupt pushed them and RTI restores
; them.
;
;   rb_fast       the copper
;   rb_probe      the same, and the beam just after the write, and as it
;                 started, in rb_beam_out[rb_y] and rb_beam_in[rb_y++]
;                 (rb_y set to 0 at each frame's end by the program)
;   rb_probe_n    rb_n writes a line from the list at rb_ptr (moving on),
;                 to palette entries 0, 1, ...; the beam after them in
;                 rb_beam_out[rb_y++]
;   rb_probe_in   the beam as the handler starts, in rb_beam_in[rb_y++]

        .global _rb_fast, _rb_probe, _rb_probe_n, _rb_probe_in

        .section .text._rb_fast
_rb_fast:
        PUSH r1
        MOV  r1, half [0xF0000008]      ; the beam's line
        CMP  r1, #40
        BLO  .frame
        PUSH r2
        MOV  r2, [_rb_base]
        MOV  r2, [r2 + r1*4]            ; the line's colour
        MOV  [0xF0000400], r2           ; palette entry 0
        MOV  [0xF0000004], r1           ; the acknowledge
        MOV  r1, half [0xF0000008]      ; and the frame's end with it?
        POP  r2
        CMP  r1, #40
        POP  r1
        BLO  _rb_frame
        RTI
.frame: POP  r1
        JMP  [_fx_orig]

        .section .text._rb_probe
_rb_probe:
        PUSH r1
        MOV  r1, half [0xF0000008]
        CMP  r1, #40
        BLO  .frame
        PUSH r2
        MOV  r2, [_rb_base]
        MOV  r2, [r2 + r1*4]
        MOV  [0xF0000400], r2
        PUSH r3
        MOV  r3, [0xF0000008]           ; the beam just after the write
        PUSH r4
        MOV  r2, [_rb_y]
        MOV  r4, [pc + _rb_beam_out_p]
        MOV  [r4 + r2*4], r3
        MOV  r4, [pc + _rb_beam_in_p]
        MOV  [r4 + r2*4], r1            ; and its line as it started
        INC  r2
        MOV  [_rb_y], r2
        POP  r4
        POP  r3
        MOV  [0xF0000004], r1
        MOV  r1, half [0xF0000008]
        POP  r2
        CMP  r1, #40
        POP  r1
        BLO  _rb_frame
        RTI
.frame: POP  r1
        JMP  [_fx_orig]

        .section .text._rb_probe_n
_rb_probe_n:
        PUSH r1
        MOV  r1, half [0xF0000008]
        CMP  r1, #40
        BLO  .frame
        SAVE r2-r4
        MOV  r1, [_rb_ptr]
        MOV  r2, #0xF0000400
        MOV  r3, [_rb_n]
.w:     MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .w
        MOV  r4, [0xF0000008]           ; the beam just after the last write
        MOV  [_rb_ptr], r1
        MOV  r1, [_rb_y]
        MOV  r2, [pc + _rb_beam_out_p]
        MOV  [r2 + r1*4], r4
        INC  r1
        MOV  [_rb_y], r1
        MOV  [0xF0000004], r1
        MOV  r1, half [0xF0000008]
        RESTORE r2-r4
        CMP  r1, #40
        POP  r1
        BLO  _rb_frame
        RTI
.frame: POP  r1
        JMP  [_fx_orig]

        .section .text._rb_probe_in
_rb_probe_in:
        PUSH r1
        MOV  r1, [0xF0000008]           ; the beam, first thing
        PUSH r1
        AND  r1, #0x3FF
        CMP  r1, #40
        BLO  .frame
        PUSH r2
        MOV  r1, [_rb_y]
        MOV  r2, [pc + _rb_beam_in_p]
        PUSH r3
        MOV  r3, [sp + 8]
        MOV  [r2 + r1*4], r3
        POP  r3
        INC  r1
        MOV  [_rb_y], r1
        MOV  [0xF0000004], r1
        MOV  r1, half [0xF0000008]
        POP  r2
        ADD  sp, #4
        CMP  r1, #40
        POP  r1
        BLO  _rb_frame
        RTI
.frame: ADD  sp, #4
        POP  r1
        JMP  [_fx_orig]

; the frame's end found after a line's acknowledge: what rt/start.s's
; entry and rt.c's rt_irq would do, but for the status check (the
; acknowledge cleared it): the video's handler, and a HALT (FE 03) the
; interrupt came at stepped over, so that a wait for the frame
; (rt_wait_frame_after) sees it
        .global _rb_frame
        .section .text._rb_frame
_rb_frame:
        SAVE r0-r7
        MOV  r1, [_rt_video_irq]
        CALL r1
        MOV  r1, [sp + 36]              ; the saved PC
        MOV  r2, half [r1]
        CMP  r2, #0x03FE
        BNE  .back
        ADD  r1, #2
        MOV  [sp + 36], r1
.back:  RESTORE r0-r7
        RTI

; rb_noguard: rb_probe_n's writes without the beam read after the
; acknowledge, for the repro of the frame's interrupt swallowed by a line's
; acknowledge (rasterbars.c, -D SWALLOW=1)
        .global _rb_noguard
        .section .text._rb_noguard
_rb_noguard:
        PUSH r1
        MOV  r1, half [0xF0000008]
        CMP  r1, #40
        BLO  .frame
        SAVE r2-r4
        MOV  r1, [_rb_ptr]
        MOV  r2, #0xF0000400
        MOV  r3, [_rb_n]
.w:     MOV  r4, [r1]+
        MOV  [r2]+, r4
        DBNZ r3, .w
        MOV  [_rb_ptr], r1
        MOV  [0xF0000004], r1           ; the acknowledge: the frame's too, if it came
        RESTORE r2-r4
        POP  r1
        RTI
.frame: POP  r1
        JMP  [_fx_orig]
