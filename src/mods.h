// OoT Remake Mods: what the module's C files and its assembly share.
#ifndef MODS_H
#define MODS_H

#include "game_table.h"     // made by tools/build_module.py from game/table.py and ootmods/options.py

// Where the assembly finds things in struct state (core.c checks these against the struct).
#define ST_PLAYER   0x00
#define ST_IFACE    0x08
#define ST_LIST     0x10
#define ST_CTRL     0x18
#define ST_ALLOWED  0x20
#define ST_OCARINA  0x21
#define ST_INSIDE   0x22
#define ST_HERO     0x23

#ifndef __ASSEMBLER__

typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
typedef unsigned long long u64;
typedef signed int s32;
typedef signed long long s64;
typedef float f32;

#define COUNT(a)    (sizeof(a) / sizeof((a)[0]))

// The settings block. The Mods window finds it by its magic, in the installed file and in the running game.
// Its layout never changes: new switches take the next free place in opt.
struct settings {
    char magic[8] __attribute__((nonstring));   // "OOTMODS1"
    u16  version;           // layout of this block
    u16  count;             // how many switches this module knows: opt[0] to opt[count - 1]
    u32  size;
    u8   opt[96];           // the switches (O_...), written by the Mods window
    u8   avail[16];         // 1 = the installer found this part's places in the game (F_...)
    u32  beat;              // one per read of a controller: the module is alive
    u32  stat[15];          // counters (S_...), for the window's status line and for tests
};
extern struct settings g_set;

enum { S_frames, S_pads, S_dual, S_full, S_left, S_right, S_hand, S_swaps, S_remembered, S_shield, S_jumps,
       S_damage, S_drops, S_ocarina, S_sprint };

// Filled in by the installer.
struct table {
    char magic[8] __attribute__((nonstring));   // "OOTMTAB1"
    s64  main_delta;        // this module's address minus main's
    u32  data[D_COUNT];     // main-relative addresses of the game's data (D_...)
};
extern struct table g_tab;
extern char __module_start[];

#define MAIN        ((u8 *)__module_start - g_tab.main_delta)
#define GDATA(id)   ((void *)(MAIN + g_tab.data[id]))
#define HAVE(f)     (g_set.avail[f])

// One state of a controller, as the system hands it over.
struct npad {
    s64 sampling;
    u64 buttons;
    s32 lx, ly, rx, ry;     // the sticks, -32767 to 32767
    u32 attributes;
    u32 unused;
};
enum { B_A = 0x1, B_B = 0x2, B_X = 0x4, B_Y = 0x8, B_L3 = 0x10, B_R3 = 0x20, B_L = 0x40, B_R = 0x80,
       B_ZL = 0x100, B_ZR = 0x200 };

struct carry { u8 *where; u32 half; };

// Everything the module remembers.
struct state {
    void *player;           // 0x00  the hero's state object, while the manual shield is on
    void *iface;            // 0x08  the object that tells the hero's animation whether the guard is up
    void *list;             // 0x10  the item selector's list
    void *ctrl;             // 0x18  the item selector's controller
    u8   allowed;           // 0x20  the shield is up: its button is held
    u8   ocarina;           // 0x21  the ocarina is being played
    u8   inside;            // 0x22  the game is deciding a drop that mods_drop_end will look at
    u8   hero;              // 0x23  Hero Mode is on

    u8   was_allowed, ocarina_seen;
    u8   l_prev, targeting, guard;          // the shield's controls
    u8   btn_down, btn_done, btn_moved;     // the button that sprint and quick swap share
    u8   fav_last, fav_fired;               // quick swap's own button
    u8   fav_ok, prev_ok;
    u8   sprint_held;
    u8   armed, armed_known;
    u8   pad_style;                         // the controller in use, and how the game reads it
    u32  pad_id;
    u32  frame;                             // frames with Link in play
    u32  seen, stale;                       // the frame at the last controller read; reads since it moved on
    u32  btn_since, fav_press;
    u32  event;                             // for quick swap at the next frame: 1 swap, 2 remember
    u32  sprint_last;
    f32  sprint_now;                        // the run's speed is times this (eased)
    u32  armed_at;
    u32  carry_next;
    u64  fav, prev;                         // the remembered item, and the one swapped away from
    struct carry carries[64];               // Hero Mode: the half points of damage enemies are owed
    u32  held;                              // buttons down at the last read in play, and not let go since
};
extern struct state g_st;

// The game's own routines (game/table.py says where each one is).
void *g_resolve_player(void *scheduler);
void *g_get_guard_component(void *actor);
void  g_draw_equipment(void *equipment, u32 which);
void  g_set_index(void *list, u32 index, u32 a, u32 b, u32 c);
void  g_equip_index(void *controller, u32 index);
void  g_commit_item(void *controller, u32 a);
void  g_items_lock(void *lock);
void  g_items_unlock(void *lock);
u32   g_read_mode(void *game);
u32   g_event_busy(void);
u32   g_may_jump(void *hero, u32 pressed);
s32   g_pouch_count(void *pouch, const char **name, u32 a, u32 b);

// The module's parts.
void shield_frame(struct state *s, u8 *hero);
void swap_frame(struct state *s);

// An address the game could have given us: in a process of the console, between these.
static inline u32 valid(const void *p)
{
    return (u64)p >= 0x8000000ULL && (u64)p < 0x8000000000ULL;
}

#endif
#endif
