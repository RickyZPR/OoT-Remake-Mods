// The settings block, the game's table, the module's memory, and the entry for each frame of play.
#include "mods.h"

struct settings g_set __attribute__((section(".data.settings"))) = {
    .magic = "OOTMODS1", .version = 1, .count = O_COUNT, .size = sizeof(struct settings), .opt = { OPTIONS_START },
};

struct table g_tab __attribute__((section(".data.table"))) = {
    .magic = "OOTMTAB1", .main_delta = NOMINAL_DELTA, .data = { NOMINAL_DATA },
};

struct state g_st __attribute__((section(".data.state"))) = { .sprint_now = 1.0f, .pad_style = 0xff };

#define AT(field, place) _Static_assert(__builtin_offsetof(struct state, field) == place, #field)
AT(player, ST_PLAYER);
AT(iface, ST_IFACE);
AT(list, ST_LIST);
AT(ctrl, ST_CTRL);
AT(allowed, ST_ALLOWED);
AT(ocarina, ST_OCARINA);
AT(inside, ST_INSIDE);
AT(hero, ST_HERO);
_Static_assert(sizeof(struct settings) == 192, "the settings block keeps its layout");
_Static_assert(__builtin_offsetof(struct settings, opt) == 16, "opt");
_Static_assert(__builtin_offsetof(struct settings, avail) == 112, "avail");
_Static_assert(__builtin_offsetof(struct settings, beat) == 128, "beat");
_Static_assert(O_COUNT <= 96 && F_COUNT <= 16, "no room in the settings block");
_Static_assert(sizeof(struct npad) == 0x28, "npad");

// The compiler may ask for these.
void *memset(void *to, int value, unsigned long size)
{
    u8 *d = to;
    while (size--)
        *d++ = (u8)value;
    return to;
}

void *memcpy(void *to, const void *from, unsigned long size)
{
    u8 *d = to;
    const u8 *s = from;
    while (size--)
        *d++ = *s++;
    return to;
}

// From the routine that steps a scheduler, before it runs. Only the one that runs Link's actions counts: it
// is stepped once a frame while Link is in play, and not in menus or while the game is paused.
void mods_frame(void **scheduler)
{
    struct state *s = &g_st;
    u8 *hero;

    if (!scheduler || *scheduler != GDATA(D_sched_vtable))
        return;
    hero = g_resolve_player(scheduler);
    if (!hero)
        return;
    s->frame++;
    g_set.stat[S_frames]++;
    shield_frame(s, hero);
    swap_frame(s);
}
