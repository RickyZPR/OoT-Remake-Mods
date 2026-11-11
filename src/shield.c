// Manual shield, each frame of play: REXCRAFT88's Manual Shield (hero_guard_frame), ported.
//
// The game raises Link's shield whenever he Z-targets. Here it goes up only while the shield's button is held:
// the trampolines in hooks.S keep the game from raising it, and this raises and lowers it.
#include "mods.h"

static u8 *at(u8 *p, u32 offset)
{
    return *(u8 **)(p + offset);
}

static void run(struct state *s, u8 *hero)
{
    u8 *actor, *table, *p, *iface, *component, *equipment;
    u32 allowed = s->guard != 0, *flags;

    s->iface = 0;
    actor = at(hero, 0x18);
    if (!actor)
        return;
    table = at(actor, 0x270);
    if (!table)
        return;
    p = at(table, 0x40);                // the animation, and through it the object that takes its switches
    if (!p)
        return;
    p = at(p, 0x18);
    if (!p)
        return;
    p = at(p, 0x18);
    if (!p)
        return;
    iface = at(p, 0x40);
    s->iface = iface;
    component = g_get_guard_component(actor);
    if (!component)
        return;

    s->allowed = (u8)allowed;
    flags = (u32 *)(hero + 0xe50);
    if (allowed)
        *flags |= 0x80100;
    else
        *flags &= ~0x80000u;
    flags = (u32 *)(component + 0x24);
    if (allowed)
        *flags |= 0x20;
    else
        *flags &= ~0x20u;
    if (iface)                          // switch 14 of the animation: the guard is up
        (*(void (**)(void *, u32, u32))(*(u8 **)iface + 0x88))(iface, 14, allowed);
    if (allowed && !s->was_allowed) {   // just raised: the shield comes off Link's back
        equipment = at(table, 0x200);
        if (equipment)
            g_draw_equipment(equipment, 4);
        g_set.stat[S_shield]++;
    }
    s->was_allowed = (u8)allowed;
}

void shield_frame(struct state *s, u8 *hero)
{
    u32 on = HAVE(F_shield) && g_set.opt[O_shield];

    if (!on) {
        if (!s->player)
            return;
        s->guard = 0;                   // just switched off: once more, to lower the shield
    }
    s->player = hero;
    run(s, hero);
    if (!on) {                          // and the game has its own way again
        s->player = 0;
        s->iface = 0;
        s->allowed = s->was_allowed = 0;
    }
}

// Crouch shield: the game asked whether Link crouches under his shield (as a child does under the Hylian
// Shield). With the shield's button held and no target, he does, whatever the shield.
u32 mods_crouch(u32 answer)
{
    struct state *s = &g_st;

    if (HAVE(F_shield) && g_set.opt[O_shield] && g_set.opt[O_crouch] && s->guard && !s->targeting)
        return 1;
    return answer;
}
