/* A flat image from address 0: code, constants, data, then the zeroed
   data, whose end the C library's heap starts from. */
ENTRY(_start)
SECTIONS
{
    . = 0;
    .text : { KEEP(*(.text.start)) *(.text .text.*) }
    .rodata : { *(.rodata .rodata.* .srodata .srodata.*) }
    .data : { *(.data .data.* .sdata .sdata.*) }
    .bss : { *(.bss .bss.* .sbss .sbss.* COMMON) }
    _end = .;
    /DISCARD/ : { *(.comment) *(.note*) *(.riscv.attributes) *(.ARM.attributes) *(.ARM.exidx*) }
}
