// Hero Mode: Link takes twice the damage and enemies half, grass has no hearts or rupees once Link has a
// sword and a shield, and enemies wait half as long between attacks (that last one is all in hooks.S).
#include "mods.h"

static u32 load16(const u8 *p)
{
    return p[0] | (u32)p[1] << 8;
}

static u32 load32(const u8 *p)
{
    return load16(p) | load16(p + 2) << 16;
}

static u32 starts(const u8 *text, const char *with)
{
    for (u32 i = 0; with[i]; i++)
        if (text[i] != (u8)with[i])
            return 0;
    return 1;
}

// The game is about to write an actor's life: `old` is there, `now` is to be. The answer is written instead.
u32 mods_life(u8 *actor, u8 *where, u32 old, u32 now)
{
    struct state *s = &g_st;
    const u8 *resource, *name;
    u32 loss;

    if (!s->hero || now >= old)
        return now;
    if (!valid(actor) || *(u8 **)actor != (u8 *)GDATA(D_life_vtable))
        return now;
    resource = *(u8 **)(actor + 16);
    if (!valid(resource))
        return now;
    name = resource + 88;
    loss = old - now;

    if (load32(name) == 0x79616c50 && load16(name + 4) == 0x7265 && !name[6]) {     // "Player"
        if (where != *(u8 **)(actor + 0x1c10) + 8)                                  // his life, nothing else
            return now;
        g_set.stat[S_damage]++;
        return old > 2 * loss ? old - 2 * loss : 0;
    }
    if (load32(name) == 0x6d656e45 && load16(name + 4) == 0x5f79) {                 // "Enemy_..."
        struct carry *e = 0;
        u32 total, result;

        for (u32 i = 0; i < COUNT(s->carries); i++)
            if (s->carries[i].where == where) {
                e = &s->carries[i];
                break;
            }
        total = loss + (e ? e->half : 0);       // half of an odd loss is kept for this enemy's next one
        result = old - total / 2;
        if ((total & 1) && result) {
            if (!e)
                e = &s->carries[s->carry_next++ % COUNT(s->carries)];
            e->where = where;
            e->half = 1;
        } else if (e) {
            e->where = 0;
            e->half = 0;
        }
        return result;
    }
    return now;
}

static const char swords[][28] = {
    "Weapon_Sword_Kokiri", "Weapon_Sword_Master", "Weapon_Sword_Giant", "Weapon_Sword_BrokenGiant",
    "Weapon_Sword_Biggoron",
};
static const char shields[][24] = { "Weapon_Shield_Deku", "Weapon_Shield_Hylian", "Weapon_Shield_Mirror" };
static const char loot[][20] = {
    "Obj_Heart", "Obj_Rupee_Green", "Obj_Rupee_Blue", "Obj_Rupee_Red", "Obj_Rupee_Purple", "Obj_Rupee_Gold",
};

static u32 owns(void *pouch, const char *name)
{
    const char *n = name;

    return g_pouch_count(pouch, &n, 0, 0) > 0;
}

// Link has a sword and a shield. Until then grass is left alone: the first shield is bought with its rupees.
static u32 hero_armed(void)
{
    struct state *s = &g_st;
    void *pouch;
    u32 sword = 0, shield = 0;

    if (s->armed_known && s->frame - s->armed_at < 60)
        return s->armed;
    pouch = *(void **)GDATA(D_pouch);
    if (!pouch)
        return 0;
    for (u32 i = 0; i < COUNT(swords) && !sword; i++)
        sword = owns(pouch, swords[i]);
    for (u32 i = 0; i < COUNT(shields) && !shield; i++)
        shield = owns(pouch, shields[i]);
    s->armed = sword && shield;
    s->armed_known = 1;
    s->armed_at = s->frame;
    return s->armed;
}

// The game is about to decide what a thing drops. 1: it is grass and Link is armed, so mods_drop_end gets to
// look through the answer.
u32 mods_drop_begin(u8 *list, u8 *request)
{
    const u8 *actor, *name;
    u32 grass = 0;

    if (!list || !request)
        return 0;
    actor = *(u8 **)(request + 0x40);
    if (valid(actor)) {
        name = *(u8 **)(actor + 0x260);
        if (!valid(name))
            name = *(u8 **)(actor + 0x20);
        if (valid(name))
            grass = starts(name, "Obj_Plant_Grass") || starts(name, "Obj_Plant_DestructibleGrass");
    }
    if (!grass && request[0x4d] != 1)
        return 0;
    if (!hero_armed())
        return 0;
    g_st.inside = 1;
    return 1;
}

// "Some/Path/Obj_Heart.something" is "Obj_Heart".
static u32 is_loot(const u8 *name)
{
    const u8 *base = name;
    u32 size = 0;

    for (u32 i = 0; i < 256 && name[i]; i++)
        if (name[i] == '/')
            base = name + i + 1;
    while (size < 32 && base[size] && base[size] != '.')
        size++;
    for (u32 n = 0; n < COUNT(loot); n++) {
        u32 i = 0;

        while (i < size && loot[n][i] && (u8)loot[n][i] == base[i])
            i++;
        if (i == size && !loot[n][i])
            return 1;
    }
    return 0;
}

// The answer: a list of things to drop (count at 0, its entries at 8, entries not in use at 0x10). The hearts
// and rupees are taken out and put back with the entries not in use.
void mods_drop_end(u8 *list)
{
    u8 **entries;
    u32 count, i = 0;

    g_st.inside = 0;
    if (!list)
        return;
    count = *(u32 *)list;
    entries = *(u8 ***)(list + 8);
    if (!entries || count > 64)
        return;
    while (i < count) {
        u8 *entry = entries[i];
        const u8 *name = valid(entry) ? *(u8 **)entry : 0;

        if (!valid(name) || !is_loot(name)) {
            i++;
            continue;
        }
        for (u32 k = i; k + 1 < count; k++)
            entries[k] = entries[k + 1];
        *(u32 *)list = --count;
        *(u8 **)entry = *(u8 **)(list + 0x10);
        *(u8 **)(list + 0x10) = entry;
        g_set.stat[S_drops]++;
    }
}
