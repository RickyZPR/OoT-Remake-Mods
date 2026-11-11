// Where the game's code comes into the module (the places are HOOKS in game/table.py), and goes back.
//
// The Hookshot recompiler turns this module into C together with the game, and that sets the rules here:
//  - a trampoline (the game reaches it with b) becomes part of the game routine it is reached from. It leaves
//    with b to places of that same routine, shares no code with another trampoline, and is never called;
//  - an entry (the game reaches it with bl) is a routine of its own;
//  - a call may change the flags. Trampolines that sit where the game's flags may be in use call nothing and
//    compare without the flags (eor, cbz); the others sit where the flags were checked to be dead.

#include "mods.h"

    .macro  STATE reg
    adrp    \reg, g_st
    add     \reg, \reg, :lo12:g_st
    .endm

    // Everything a C routine may change, but the flags. x12 is at 0x60, q0 at 0xa0.
    .macro  SAVE_ALL
    sub     sp, sp, #0x220
    stp     x0, x1, [sp, #0x00]
    stp     x2, x3, [sp, #0x10]
    stp     x4, x5, [sp, #0x20]
    stp     x6, x7, [sp, #0x30]
    stp     x8, x9, [sp, #0x40]
    stp     x10, x11, [sp, #0x50]
    stp     x12, x13, [sp, #0x60]
    stp     x14, x15, [sp, #0x70]
    stp     x16, x17, [sp, #0x80]
    stp     x18, x30, [sp, #0x90]
    stp     q0, q1, [sp, #0xa0]
    stp     q2, q3, [sp, #0xc0]
    stp     q4, q5, [sp, #0xe0]
    stp     q6, q7, [sp, #0x100]
    stp     q16, q17, [sp, #0x120]
    stp     q18, q19, [sp, #0x140]
    stp     q20, q21, [sp, #0x160]
    stp     q22, q23, [sp, #0x180]
    stp     q24, q25, [sp, #0x1a0]
    stp     q26, q27, [sp, #0x1c0]
    stp     q28, q29, [sp, #0x1e0]
    stp     q30, q31, [sp, #0x200]
    .endm

    .macro  RESTORE_ALL
    ldp     x0, x1, [sp, #0x00]
    ldp     x2, x3, [sp, #0x10]
    ldp     x4, x5, [sp, #0x20]
    ldp     x6, x7, [sp, #0x30]
    ldp     x8, x9, [sp, #0x40]
    ldp     x10, x11, [sp, #0x50]
    ldp     x12, x13, [sp, #0x60]
    ldp     x14, x15, [sp, #0x70]
    ldp     x16, x17, [sp, #0x80]
    ldp     x18, x30, [sp, #0x90]
    ldp     q0, q1, [sp, #0xa0]
    ldp     q2, q3, [sp, #0xc0]
    ldp     q4, q5, [sp, #0xe0]
    ldp     q6, q7, [sp, #0x100]
    ldp     q16, q17, [sp, #0x120]
    ldp     q18, q19, [sp, #0x140]
    ldp     q20, q21, [sp, #0x160]
    ldp     q22, q23, [sp, #0x180]
    ldp     q24, q25, [sp, #0x1a0]
    ldp     q26, q27, [sp, #0x1c0]
    ldp     q28, q29, [sp, #0x1e0]
    ldp     q30, q31, [sp, #0x200]
    add     sp, sp, #0x220
    .endm

    // At the first instruction of a game routine only what it was given matters: its arguments and where it
    // returns.
    .macro  SAVE_ARGS
    sub     sp, sp, #0xd0
    stp     x0, x1, [sp, #0x00]
    stp     x2, x3, [sp, #0x10]
    stp     x4, x5, [sp, #0x20]
    stp     x6, x7, [sp, #0x30]
    stp     x8, x30, [sp, #0x40]
    stp     q0, q1, [sp, #0x50]
    stp     q2, q3, [sp, #0x70]
    stp     q4, q5, [sp, #0x90]
    stp     q6, q7, [sp, #0xb0]
    .endm

    .macro  RESTORE_ARGS
    ldp     x0, x1, [sp, #0x00]
    ldp     x2, x3, [sp, #0x10]
    ldp     x4, x5, [sp, #0x20]
    ldp     x6, x7, [sp, #0x30]
    ldp     x8, x30, [sp, #0x40]
    ldp     q0, q1, [sp, #0x50]
    ldp     q2, q3, [sp, #0x70]
    ldp     q4, q5, [sp, #0x90]
    ldp     q6, q7, [sp, #0xb0]
    add     sp, sp, #0xd0
    .endm

// ---------------------------------------------------------------------------------------------- trampolines
    .section .text.tramp, "ax"
    .balign 4
    .global tramp_frame, tramp_guard_flags, tramp_guard_update, tramp_setter
    .global tramp_ocarina_enter, tramp_ocarina_leave, tramp_swap_ctrl, tramp_swap_list
    .global tramp_sprint, tramp_autojump, tramp_life_a, tramp_life_b, tramp_drop, tramp_interval

// The routine that steps a scheduler, at its first instruction. x0: the scheduler.
tramp_frame:
    SAVE_ARGS
    bl      mods_frame
    RESTORE_ARGS
    pacibsp
    b       g_frame_resume

// Manual shield. The game is about to raise the guard flag by itself: "orr w8, w8, w9", w8 the hero's flags,
// x20 the hero's state object. It stays down unless the shield's button is held.
tramp_guard_flags:
    orr     w8, w8, w9
    stp     x16, x17, [sp, #-16]!
    STATE   x16
    ldr     x17, [x16, #ST_PLAYER]
    eor     x17, x17, x20
    cbnz    x17, 1f
    ldrb    w17, [x16, #ST_ALLOWED]
    cbnz    w17, 1f
    and     w8, w8, #0xfff7ffff
1:  ldp     x16, x17, [sp], #16
    b       g_guard_flags_resume

// The same in the hero's update: "orr w9, w9, #0x80000", x21 the hero's state object.
tramp_guard_update:
    stp     x16, x17, [sp, #-16]!
    STATE   x16
    ldr     x17, [x16, #ST_PLAYER]
    eor     x17, x17, x21
    cbnz    x17, 1f
    ldrb    w17, [x16, #ST_ALLOWED]
    cbnz    w17, 1f
    and     w9, w9, #0xfff7ffff
    b       2f
1:  orr     w9, w9, #0x80000
2:  ldp     x16, x17, [sp], #16
    b       g_guard_update_resume

// The routine that sets a switch of an animation, at its first instruction: "tbnz w1, #31, <return>".
// x0 the object, w1 which switch, w2 the value. Switch 14 of the hero's is "the guard is up": ours to say.
tramp_setter:
    tbnz    w1, #31, 9f
    STATE   x16
    ldr     x17, [x16, #ST_IFACE]
    cbz     x17, 1f
    eor     x17, x17, x0
    cbnz    x17, 1f
    sub     w17, w1, #14
    cbnz    w17, 1f
    ldrb    w2, [x16, #ST_ALLOWED]
1:  b       g_setter_resume
9:  b       g_setter_early

// Playing the ocarina starts, and ends: both at the first instruction of a routine.
tramp_ocarina_enter:
    STATE   x16
    mov     w17, #1
    strb    w17, [x16, #ST_OCARINA]
    pacibsp
    b       g_ocarina_enter_resume

tramp_ocarina_leave:
    STATE   x16
    strb    wzr, [x16, #ST_OCARINA]
    pacibsp
    b       g_ocarina_leave_resume

// Quick swap. The item selector's controller is updated (x0: the controller, which holds its list at 0x68)...
tramp_swap_ctrl:
    STATE   x16
    ldr     x17, [x16, #ST_LIST]
    cbz     x17, 1f
    ldr     x9, [x0, #0x68]
    eor     x9, x9, x17
    cbnz    x9, 1f
    str     x0, [x16, #ST_CTRL]
1:  pacibsp
    b       g_swap_ctrl_resume

// ...and its list is made (x0: the list).
tramp_swap_list:
    STATE   x16
    str     x0, [x16, #ST_LIST]
    str     xzr, [x16, #ST_CTRL]
    pacibsp
    b       g_swap_list_resume

// Sprint: "blr x8" hands the run animation its speed, in s0.
tramp_sprint:
    SAVE_ALL
    bl      mods_sprint
    str     s0, [sp, #0xa0]
    RESTORE_ALL
    blr     x8
    b       g_sprint_resume

// Auto-jump: the Walk state has no ground ahead and is about to look at the stick ("ldr x8, [x22, #0xa0]").
// x19 the state, x20 the hero, x22 his input. To jump now, go on where the game takes the state in w1.
tramp_autojump:
    SAVE_ALL
    mov     x0, x19
    mov     x1, x20
    mov     x2, x22
    bl      mods_autojump
    cbnz    w0, 1f
    RESTORE_ALL
    ldr     x8, [x22, #0xa0]
    b       g_autojump_resume
1:  RESTORE_ALL
    ldrb    w1, [x19, #0x32]
    b       g_autojump_take

// Hero Mode: the game is about to write an actor's life ("mov w11, w10", then a compare-and-swap).
// x19 the actor's life component, x13 where the life is, w10 the life now, w12 the life to write.
tramp_life_a:
    SAVE_ALL
    mov     x0, x19
    mov     x1, x13
    mov     w2, w10
    mov     w3, w12
    bl      mods_life
    str     w0, [sp, #0x60]
    RESTORE_ALL
    mov     w11, w10
    b       g_life_a_resume

tramp_life_b:
    SAVE_ALL
    mov     x0, x19
    mov     x1, x13
    mov     w2, w10
    mov     w3, w12
    bl      mods_life
    str     w0, [sp, #0x60]
    RESTORE_ALL
    mov     w11, w10
    b       g_life_b_resume

// Hero Mode: the routine that decides what a thing drops, at its first instruction. x1: a list for the answer,
// x2: the request. For grass, once Link is armed, the game's routine runs inside this and its answer is
// looked through before the caller gets it.
tramp_drop:
    STATE   x16
    ldrb    w17, [x16, #ST_HERO]
    cbz     w17, 8f
    ldrb    w17, [x16, #ST_INSIDE]
    cbnz    w17, 8f
    SAVE_ARGS
    mov     x0, x1
    mov     x1, x2
    bl      mods_drop_begin
    cbz     w0, 7f
    RESTORE_ARGS
    stp     x29, x30, [sp, #-0x40]!
    mov     x29, sp
    str     x19, [sp, #0x10]
    mov     x19, x1
    bl      g_drop_decide
    stp     x0, x1, [sp, #0x20]
    str     q0, [sp, #0x30]
    mov     x0, x19
    bl      mods_drop_end
    ldp     x0, x1, [sp, #0x20]
    ldr     q0, [sp, #0x30]
    ldr     x19, [sp, #0x10]
    ldp     x29, x30, [sp], #0x40
    ret
7:  RESTORE_ARGS
8:  pacibsp
    b       g_drop_resume

// Hero Mode: the end of the routine that draws how many frames an enemy waits before its next attack. The
// wait is in s8, and "ldr x19, [sp, #0x18]" begins the return.
tramp_interval:
    STATE   x16
    ldrb    w17, [x16, #ST_HERO]
    cbz     w17, 1f
    fcmp    s8, #0.0
    b.le    1f
    fmov    s0, #0.5
    fmul    s8, s8, s0
1:  ldr     x19, [sp, #0x18]
    b       g_interval_resume

// -------------------------------------------------------------------------------------------------- entries
    .section .text.entry, "ax"
    .balign 4

// In place of the game's call that reads a controller. x0: the states, w1: how many fit, x2: the controller's
// id. The system's routine is called first, then mods_pad(states, how many came, id, style).
    .macro  pad_entry style, number
    .global pad_\style
    .type   pad_\style, %function
pad_\style:
    stp     x29, x30, [sp, #-0x30]!
    mov     x29, sp
    stp     x19, x20, [sp, #0x10]
    str     x21, [sp, #0x20]
    mov     x19, x0
    ldr     w21, [x2]
    bl      g_pad_get_\style
    mov     w20, w0
    mov     x0, x19
    mov     w1, w20
    mov     w2, w21
    mov     w3, #\number
    bl      mods_pad
    mov     w0, w20
    ldr     x21, [sp, #0x20]
    ldp     x19, x20, [sp, #0x10]
    ldp     x29, x30, [sp], #0x30
    ret
    .endm

    pad_entry dual, 0
    pad_entry full, 1
    pad_entry left, 2
    pad_entry right, 3
    pad_entry hand, 4

// Crouch shield: in place of the game's call that asks whether the shield on Link's arm is one to crouch under.
    .global entry_crouch
    .type   entry_crouch, %function
entry_crouch:
    stp     x29, x30, [sp, #-16]!
    mov     x29, sp
    bl      g_crouch_asked
    bl      mods_crouch
    ldp     x29, x30, [sp], #16
    ret
