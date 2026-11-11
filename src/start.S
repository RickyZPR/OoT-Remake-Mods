// The module's header. Hand-written so the game's own loader (rtld) and the Hookshot builder both accept it:
// a text head in the old form (branch, then the offset of MOD0), MOD0, a dynamic section with no relocations,
// an empty GNU hash table (rtld crashes on a module with no hash table) and one null symbol.

    .section .text.head, "ax"
    .global __module_start
__module_start:
    b       1f                              // 0x14000002: rtld takes this as an old-form header
    .word   __mod0 - __module_start
1:  ret

    .global __mod_init
__mod_init:                                 // DT_INIT / DT_FINI: nothing to do
    ret
__mod_fini:
    ret

    .global mods_stub
mods_stub:                                  // where the installer points what it did not find in the game
    ret

    .section .rodata.mod0, "a"
    .balign 8
__mod0:
    .ascii  "MOD0"
    .word   __dynamic - __mod0
    .word   __bss_start - __mod0
    .word   __bss_end - __mod0
    .word   0                               // .eh_frame_hdr: none (start = end)
    .word   0
    .word   __module_object - __mod0
    .word   0, 0, 0, 0, 0, 0

    .balign 8
__gnu_hash:
    .word   1                               // buckets
    .word   1                               // first hashed symbol
    .word   1                               // bloom words
    .word   6                               // bloom shift
    .quad   0                               // bloom filter: matches nothing
    .word   0                               // bucket 0: empty
    .word   0
__dynsym:
    .zero   0x18                            // the null symbol
__dynstr:
    .byte   0
    .balign 8

    .section .data.dynamic, "aw"
    .balign 8
__dynamic:
    .quad   5,  __off_dynstr                // DT_STRTAB
    .quad   6,  __off_dynsym                // DT_SYMTAB
    .quad   10, 1                           // DT_STRSZ
    .quad   11, 0x18                        // DT_SYMENT
    .quad   0x6ffffef5, __off_gnu_hash      // DT_GNU_HASH
    .quad   12, __off_init                  // DT_INIT
    .quad   13, __off_fini                  // DT_FINI
    .quad   0,  0

    .section .bss.modobj, "aw", %nobits
    .balign 16
__module_object:
    .space  0x100                           // rtld's record of this module (0xd0 bytes used)

    .global __off_refs                      // keep the symbols the linker script needs
    .set    __off_refs, 0
    .global __gnu_hash, __dynsym, __dynstr, __mod_fini
