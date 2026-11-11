/* Layout of the mod module. Linked with the game's main at 0 and this module at MODULE_BASE (the address it
   has in today's game); the installer moves it to wherever the modules of the installed game put it. */
OUTPUT_ARCH(aarch64)
ENTRY(__module_start)

PHDRS
{
    text   PT_LOAD FLAGS(5);
    rodata PT_LOAD FLAGS(4);
    data   PT_LOAD FLAGS(6);
}

SECTIONS
{
    . = MODULE_BASE;
    .text : {
        KEEP(*(.text.head))
        KEEP(*(.text.tramp))
        KEEP(*(.text.entry))
        *(.text .text.*)
    } :text
    __text_end = .;

    . = ALIGN(0x1000);
    .rodata : {
        KEEP(*(.rodata.mod0))
        *(.rodata .rodata.*)
    } :rodata
    __rodata_end = .;

    . = ALIGN(0x1000);
    .data : {
        KEEP(*(.data.settings))
        KEEP(*(.data.table))
        KEEP(*(.data.dynamic))
        *(.data .data.*)
    } :data
    __data_end = .;

    . = ALIGN(16);
    __bss_start = .;
    .bss (NOLOAD) : {
        *(.bss .bss.*)
        *(COMMON)
    } :data
    ASSERT(. <= MODULE_BASE + MODULE_SIZE, "the module is bigger than MODULE_SIZE (game/table.py)")
    . = MODULE_BASE + MODULE_SIZE;
    __bss_end = .;

    __off_dynstr   = __dynstr   - __module_start;
    __off_dynsym   = __dynsym   - __module_start;
    __off_gnu_hash = __gnu_hash - __module_start;
    __off_init     = __mod_init - __module_start;
    __off_fini     = __mod_fini - __module_start;

    /DISCARD/ : { *(.comment) *(.note*) *(.eh_frame*) *(.ARM.*) *(.got*) *(.plt*) *(.iplt*) *(.igot*) }
}
