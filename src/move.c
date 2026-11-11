// Sprint, and the N64's auto-jump.
#include "mods.h"

// Running has no speed of its own in this game: the run animation carries Link, and the number passing through
// here sets how fast it plays. Once a frame while Link moves.
f32 mods_sprint(f32 v)
{
    struct state *s = &g_st;
    f32 to = 1.0f;

    if (s->frame - s->sprint_last > 30)         // he was not running: nothing is left of the last sprint
        s->sprint_now = 1.0f;
    s->sprint_last = s->frame;
    if (s->sprint_held && HAVE(F_sprint) && g_set.opt[O_sprint]) {
        u32 percent = g_set.opt[O_sprint_speed];

        if (percent < 100)
            percent = 100;
        if (percent > 250)
            percent = 250;
        to = (f32)percent / 100.0f;
    }
    s->sprint_now += (to - s->sprint_now) * 0.25f;
    if (to == 1.0f && s->sprint_now < 1.005f)
        s->sprint_now = 1.0f;
    if (s->sprint_now == 1.0f)
        return v;
    g_set.stat[S_sprint]++;
    return v * s->sprint_now;
}

// The Walk state has no ground ahead. The game lets Link drop off the edge unless the stick is pushed all the
// way; on the N64 he jumped whenever he ran off one. 1: jump.
u32 mods_autojump(u8 *state, void *hero, u8 *input)
{
    f32 *stick, left, full;

    if (!g_set.opt[O_autojump] || !state || !hero || !input)
        return 0;
    if (state[0x32] == 0xff)                    // this Walk has no jump to go to
        return 0;
    stick = *(f32 **)(input + 0xa0);
    if (!stick || !(*stick >= 0.5f))
        return 0;
    left = *(f32 *)(state + 0x24);              // the run-up: not from a standing start
    full = *(f32 *)(state + 0x28);
    if (left > full - 1.0f)
        return 0;
    if (!(g_may_jump(hero, 1) & 1))
        return 0;
    g_set.stat[S_jumps]++;
    return 1;
}
