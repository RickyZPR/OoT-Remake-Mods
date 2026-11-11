// Quick swap, each frame of play: what the controller read left in s->event is done here.
// 2: remember the item in hand. 1: change to the remembered item, or from it back to the one before.
#include "mods.h"

static s32 find(u64 **node, s32 count, u64 want, u64 mask)
{
    for (s32 i = 0; i < count; i++)
        if (node[i] && (*node[i] & mask) == (want & mask))
            return i;
    return -1;
}

void swap_frame(struct state *s)
{
    u32 ev = s->event, cur, mode, mask, have;
    u8 *c, *l, *g, *ui, *items;
    void **slot;
    u64 **node, curv, want;
    s32 count, target = -1;

    if (!ev)
        return;
    s->event = 0;
    if (!HAVE(F_swap))
        return;
    c = s->ctrl;                        // the item selector, opened at least once since the game started
    l = s->list;
    if (!c || !l || *(u8 **)(c + 0x68) != l)
        return;
    slot = *(void ***)GDATA(D_game_slot);
    g = slot ? *slot : 0;
    ui = *(u8 **)GDATA(D_ui_flags);
    if (!g || !ui)
        return;
    mode = g_read_mode(g);              // Link has the controls, and no event is running
    mask = mode == 0 ? 8 : mode <= 2 ? 4 : 0;
    if (mask && !(ui[0x58c] & mask))
        return;
    if (g_event_busy() & 1)
        return;

    items = g + 0x498;
    cur = *(u32 *)(l + 0x4c);
    g_items_lock(g + 0x3b90);
    count = *(s32 *)items;
    if (count < 0)
        count = 0;
    if (count > 64)
        count = 64;
    node = *(u64 ***)(items + 8);
    have = node && cur < (u32)count && node[cur];
    curv = have ? *node[cur] : 0;
    if (ev == 2) {
        if (have) {
            s->fav = curv;
            s->fav_ok = 1;
            g_set.stat[S_remembered]++;
        }
    } else if (s->fav_ok && node) {
        want = s->fav;
        if (have && curv == s->fav) {
            if (s->prev_ok)
                want = s->prev;
        } else if (have) {
            s->prev = curv;
            s->prev_ok = 1;
        }
        target = find(node, count, want, ~0ULL);
        if (target < 0)                 // the same item, in another state
            target = find(node, count, want, 0xffffffffULL);
    }
    g_items_unlock(g + 0x3b90);

    if (target >= 0 && (u32)target != cur) {
        g_set_index(l, (u32)target, 0, 0, 1);
        g_equip_index(c, (u32)target);
        g_commit_item(c, 0);
        g_set.stat[S_swaps]++;
    }
}
