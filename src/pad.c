// Each read of a controller, after the system has filled in the states. p[0] is the newest.
//
// Nothing here acts on the game: buttons are taken from it or handed to it, and what the frame should do is
// left in the state for mods_frame. Times are counted in frames of play, never in reads: the game reads the
// controller more than once a frame, and goes on reading it while it is paused.
#include "mods.h"

#define HOLD_FRAMES 20      // quick swap's button held this long remembers the item
#define TAP_FRAMES  15      // on the sprint button, a press on the run still swaps if it was shorter than this
#define STOPPED     8       // more reads than this with no new frame: the game is paused or in a menu

static const u16 shield_buttons[] = { BUTTONS_shield_button };
static const u16 swap_buttons[] = { BUTTONS_swap_button };
static const u16 sprint_buttons[] = { BUTTONS_sprint };

#define PICK(list, at) ((at) < COUNT(list) ? (list)[at] : (list)[0])

static void strip(struct npad *p, u32 count, u64 bits)
{
    for (u32 i = 0; i < count; i++)
        p[i].buttons &= ~bits;
}

static u32 centred(s32 v)
{
    return v > -8000 && v < 8000;
}

// The shield's button and ZL change places: the mod listens to ZL, and the game gets the other's job on ZL.
static u64 exchange(u64 b, u32 with)
{
    u64 zl = b & B_ZL, other = b & with;

    if (with == B_ZL)
        return b;
    b &= ~(u64)(B_ZL | with);
    if (zl)
        b |= with;
    if (other)
        b |= B_ZL;
    return b;
}

// Sprint and quick swap on one button. The game is not shown it. Let go before HOLD_FRAMES: a swap. Held that
// long standing still: the item is remembered. Held with the stick pushed: a sprint, which remembers nothing,
// and letting go of it swaps only if it was a tap.
static void shared_button(struct state *s, struct npad *p, u32 count, u32 bit)
{
    u32 now = (u32)p[0].buttons, down = (now & bit) != 0;

    strip(p, count, bit);
    if (down && !s->btn_down) {
        s->btn_since = s->frame;
        s->btn_done = 0;
        s->btn_moved = 0;
    }
    if (now & B_R)                          // the item selector is open: this press is not ours
        s->btn_done = 1;
    if (down) {
        s64 x = p[0].lx, y = p[0].ly;

        if (x * x + y * y > 9000LL * 9000LL)
            s->btn_moved = 1;
        if (!s->btn_done && !s->btn_moved && s->frame - s->btn_since >= HOLD_FRAMES) {
            s->btn_done = 1;
            s->event = 2;
        }
    } else if (s->btn_down && !s->btn_done && (!s->btn_moved || s->frame - s->btn_since < TAP_FRAMES)) {
        s->event = 1;
    }
    s->btn_down = (u8)down;
}

// Quick swap on a button of its own (after favorite_raw of OoT Quick Item, the project this one grew from).
static void swap_button(struct state *s, struct npad *p, u32 count, u32 bit)
{
    u32 now = (u32)p[0].buttons, held;

    if (!bit) {                             // off: nothing pending, nothing held
        s->event = 0;
        s->fav_last = s->fav_fired = 0;
        return;
    }
    held = (now & bit) != 0;
    if (now & B_R) {                        // the item selector is open
        held = 0;
        s->fav_fired = 1;
    }
    if (held && !s->fav_last) {
        s->fav_press = s->frame;
        s->fav_fired = 0;
    }
    if (held && !s->fav_fired && s->frame - s->fav_press >= HOLD_FRAMES) {
        s->event = 2;
        s->fav_fired = 1;
    }
    if (!held && s->fav_last && !s->fav_fired)
        s->event = 1;
    s->fav_last = (u8)held;
    strip(p, count, bit);
}

// Manual shield (REXCRAFT88's hero_controls_raw): ZL is the shield, L turns Z-targeting on and off, R3 turns
// it off. In play the game gets ZL while either is wanted, and never L.
static void shield_controls(struct state *s, struct npad *p, u32 count, u32 on)
{
    u32 now = (u32)p[0].buttons, guard, l;

    if (!on) {
        s->l_prev = s->targeting = s->guard = 0;
        return;
    }
    guard = (now & B_ZL) != 0;
    l = (now & B_L) != 0;
    strip(p, count, B_L | B_ZL);
    if (l && !s->l_prev)
        s->targeting ^= 1;
    if (now & B_R3)
        s->targeting = 0;
    s->l_prev = (u8)l;
    s->guard = (u8)guard;
    if (s->targeting || guard)
        for (u32 i = 0; i < count; i++)
            p[i].buttons |= B_ZL;
}

// Every button is the game's for now. What is held is taken as dealt with, so that nothing fires afterwards;
// the shield's button alone keeps its meaning, so that a shield held up stays up.
static void hands_off(struct state *s, u64 seen, u32 shield)
{
    s->l_prev = (seen & B_L) != 0;
    s->guard = shield && (seen & B_ZL) != 0;
    s->btn_down = s->btn_done = 1;
    s->fav_last = s->fav_fired = 1;
    s->sprint_held = 0;
}

void mods_pad(struct npad *p, u32 count, u32 id, u32 style)
{
    struct state *s = &g_st;
    struct settings *o = &g_set;
    u32 now, shield, sprint, swap, with;

    o->beat++;
    s->hero = HAVE(F_hero) && o->opt[O_hero];
    if (!p || count == 0 || count > 64 || (id != 0 && id != 0x20) || style > 4)
        return;
    o->stat[S_pads]++;
    o->stat[S_dual + style]++;
    now = (u32)p[0].buttons;

    // The game reads player 1's controller and the console's own, each in more than one style, and only one
    // of those has anything. The one in use is the last that had a button down or a stick pushed; the reads of
    // the others are left as they came.
    if (id != s->pad_id || style != s->pad_style) {
        if (!(now & 0xffff) && centred(p[0].lx) && centred(p[0].ly) && centred(p[0].rx) && centred(p[0].ry))
            return;
        s->pad_id = id;
        s->pad_style = (u8)style;
    }
    if (s->frame != s->seen) {
        s->seen = s->frame;
        s->stale = 0;
    } else if (s->stale < 16) {
        s->stale++;
    }

    shield = HAVE(F_shield) && o->opt[O_shield];
    sprint = HAVE(F_sprint) ? PICK(sprint_buttons, o->opt[O_sprint]) : 0;
    swap = HAVE(F_swap) && o->opt[O_swap] ? PICK(swap_buttons, o->opt[O_swap_button]) : 0;
    with = shield ? PICK(shield_buttons, o->opt[O_shield_button]) : B_ZL;
    if (with == swap)
        with = B_ZL;

    // While the ocarina is played every button is a note: nothing is touched.
    if (s->ocarina) {
        if (!s->ocarina_seen) {
            s->ocarina_seen = 1;
            o->stat[S_ocarina]++;
        }
        hands_off(s, exchange(now, with), 0);
        s->targeting = 0;
        s->held = 0;
        return;
    }
    s->ocarina_seen = 0;

    // While the game is paused, in a menu or showing a scene, a button pressed there is the game's, as it is
    // (L and R turn the pages of the pause menu). One that was down before goes on being what it was in play
    // until it is let go: R, held, keeps the item selector open.
    if (s->stale > STOPPED) {
        u64 taken = (shield ? B_L | B_ZL : 0) | swap;

        for (u32 i = 0; i < count; i++) {
            u64 b = p[i].buttons, old = b & s->held;

            p[i].buttons = (b & ~(u64)s->held) | (exchange(old, with) & ~taken);
        }
        s->held &= now;
        hands_off(s, exchange(now, with), shield);
        return;
    }
    s->held = now;

    if (with != B_ZL) {
        for (u32 i = 0; i < count; i++)
            p[i].buttons = exchange(p[i].buttons, with);
        now = (u32)p[0].buttons;
    }
    s->sprint_held = (now & sprint) != 0;
    if (sprint && sprint == swap) {
        shared_button(s, p, count, sprint);
        s->fav_last = s->fav_fired = 1;
    } else {
        s->btn_down = s->btn_done = 1;
    }
    shield_controls(s, p, count, shield);
    if (!(sprint && sprint == swap))
        swap_button(s, p, count, swap);
}
