; A small 6502 program for the guest's lockstep test: decimal ADC and SBC,
; overflow, the stack, JSR, (zp),y, ROR on memory; prints "ok".
        .org $0400
start:  ldx #$ff
        txs
        cld
        lda #$99
        clc
        sed
        adc #$01        ; decimal: $00, carry
        sta $10
        lda #$50
        sec
        sbc #$25        ; decimal: $25
        sta $11
        cld
        lda #$7f
        clc
        adc #$01        ; overflow
        php
        pla
        sta $12
        jsr sub
        ror $12
        ldy #0
loop:   lda msg,y
        beq done
        sta $E000
        iny
        bne loop
done:   .byte $02
sub:    lda ($10),y
        rts
msg:    .byte "ok", 10, 0
