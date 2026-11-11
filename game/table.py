"""Where things are in the game's main module. Addresses are relative to main's start, in the game version
below. The build turns each one into a pattern (module/manifest.json) that the installer uses to find the
same place in whatever version of the game is installed."""

BUILD_ID = "E0F3CCFAF50065AE4EA01EB5AEB13B1A45DA3348"
MODULE_BASE = 0x4F80000       # where the module sits in this version: after main and subsdk0
MODULE_SIZE = 0x40000         # what the module takes in memory. Fixed, so a new version of the mod moves nothing

# The parts of the mod. Each is installed only if every place it needs was found in the game; the others still
# work. The order is the order of the "installed" bytes in the settings block: add new ones at the end.
FEATURES = ["core", "shield", "ocarina", "crouch", "swap", "sprint", "autojump", "hero", "hero_drop",
            "hero_interval"]
NEEDS = {"crouch": "shield"}  # a part that is no use without another

# Instructions of main that the installer replaces with a branch into the module.
#   name: (address, original instruction, "b" or "bl", entry in the module, feature)
HOOKS = {
    # Every frame with Link in play (the routine that steps a scheduler), and every read of a controller.
    "frame":         (0x2B30DE0, 0xD503237F, "b",  "tramp_frame",         "core"),
    "pad_dual":      (0x34694F8, 0x941F64BE, "bl", "pad_dual",            "core"),
    "pad_left":      (0x3469524, 0x941F64BB, "bl", "pad_left",            "core"),
    "pad_right":     (0x3469550, 0x941F64B4, "bl", "pad_right",           "core"),
    "pad_full":      (0x346966C, 0x941F6465, "bl", "pad_full",            "core"),
    "pad_hand":      (0x3469698, 0x941F6466, "bl", "pad_hand",            "core"),
    # Manual shield: the two places the game raises the guard flag by itself, and the routine that tells the
    # hero's animation whether the guard is up.
    "guard_flags":   (0x0972E18, 0x2A090108, "b",  "tramp_guard_flags",   "shield"),
    "guard_update":  (0x097320C, 0x320D0129, "b",  "tramp_guard_update",  "shield"),
    "setter":        (0x37BA100, 0x37F801C1, "b",  "tramp_setter",        "shield"),
    # Playing the ocarina starts and ends: every button is the game's meanwhile.
    "ocarina_enter": (0x2894340, 0xD503237F, "b",  "tramp_ocarina_enter", "ocarina"),
    "ocarina_leave": (0x28947F0, 0xD503237F, "b",  "tramp_ocarina_leave", "ocarina"),
    # Crouch shield: the game asks whether the shield on Link's arm is one to crouch under.
    "crouch":        (0x04A1C3C, 0x94000051, "bl", "entry_crouch",        "crouch"),
    # Quick swap: the item selector's controller (each time it is updated) and its list (when it is made).
    "swap_ctrl":     (0x33C9270, 0xD503237F, "b",  "tramp_swap_ctrl",     "swap"),
    "swap_list":     (0x0E9EE30, 0xD503237F, "b",  "tramp_swap_list",     "swap"),
    # Sprint: the call that gives the run animation its speed.
    "sprint":        (0x0934474, 0xD63F0100, "b",  "tramp_sprint",        "sprint"),
    # Auto-jump: the Walk state has found no ground ahead and looks at the stick.
    "autojump":      (0x07F755C, 0xF94052C8, "b",  "tramp_autojump",      "autojump"),
    # Hero Mode: the two places an actor's life is written, the routine that decides what a thing drops, and
    # the end of the routine that draws how long an enemy waits before its next attack.
    "life_a":        (0x049DCF4, 0x2A0A03EB, "b",  "tramp_life_a",        "hero"),
    "life_b":        (0x049DECC, 0x2A0A03EB, "b",  "tramp_life_b",        "hero"),
    "drop":          (0x2EF45E0, 0xD503237F, "b",  "tramp_drop",          "hero_drop"),
    "interval":      (0x0F2F54C, 0xF9400FF3, "b",  "tramp_interval",      "hero_interval"),
}

# Hooks that are the first instruction of a routine although it is not the usual one (pacibsp) and nothing
# calls it by a plain bl: a pattern for them must not reach into the routine before.
STARTS = ["setter"]

# Code of main the module branches to or calls.
#   name: ("at", address, feature)   a routine of the game
#         ("after", hook)            the instruction after a hook
#         ("target", hook)           where the hook's original instruction branches (b, bl, cbz, tbz, b.cond)
#         ("near", hook, distance)   a place in the same routine, that many bytes after the hook
#         ("self", hook)             the hook itself (the start of a routine the module calls again)
CODE = {
    "frame_resume":         ("after", "frame"),
    "pad_get_dual":         ("target", "pad_dual"),
    "pad_get_left":         ("target", "pad_left"),
    "pad_get_right":        ("target", "pad_right"),
    "pad_get_full":         ("target", "pad_full"),
    "pad_get_hand":         ("target", "pad_hand"),
    "resolve_player":       ("at", 0x0973030, "core"),      # (scheduler) -> the hero's state object, or 0

    "guard_flags_resume":   ("after", "guard_flags"),
    "guard_update_resume":  ("after", "guard_update"),
    "setter_resume":        ("after", "setter"),
    "setter_early":         ("target", "setter"),
    "get_guard_component":  ("at", 0x0974EB0, "shield"),    # (actor)
    "draw_equipment":       ("at", 0x06B6820, "shield"),    # (equipment, which)

    "ocarina_enter_resume": ("after", "ocarina_enter"),
    "ocarina_leave_resume": ("after", "ocarina_leave"),

    "crouch_asked":         ("target", "crouch"),

    "swap_ctrl_resume":     ("after", "swap_ctrl"),
    "swap_list_resume":     ("after", "swap_list"),
    "set_index":            ("at", 0x3774350, "swap"),      # (list, index, 0, 0, 1)
    "equip_index":          ("at", 0x33C8F50, "swap"),      # (controller, index)
    "commit_item":          ("at", 0x33C98F0, "swap"),      # (controller, 0)
    "items_lock":           ("at", 0x0946A50, "swap"),      # (game + 0x3b90)
    "items_unlock":         ("at", 0x0947300, "swap"),
    "read_mode":            ("at", 0x33ABED0, "swap"),      # (game)
    "event_busy":           ("at", 0x05741F0, "swap"),      # ()

    "sprint_resume":        ("after", "sprint"),

    "autojump_resume":      ("after", "autojump"),
    "autojump_take":        ("near", "autojump", 0x48),     # go to the state whose number is in w1
    "may_jump":             ("at", 0x07FB690, "autojump"),  # (hero, 1)

    "life_a_resume":        ("after", "life_a"),
    "life_b_resume":        ("after", "life_b"),
    "drop_resume":          ("after", "drop"),
    "drop_decide":          ("self", "drop"),
    "pouch_count":          ("at", 0x05963E0, "hero_drop"), # (pouch, &name, 0, 0)
    "interval_resume":      ("after", "interval"),
}

# Data of main the module reads.   name: (address, feature)
DATA = {
    "sched_vtable": (0x4B05318, "core"),        # what the scheduler of Link's actions starts with
    "life_vtable":  (0x4B4C460, "hero"),        # what an actor's life component starts with
    "game_slot":    (0x4C7E0D0, "swap"),        # holds the address of the pointer to the game's manager
    "ui_flags":     (0x4E7CFA8, "swap"),        # points at the object whose byte 0x58c says items may change
    "pouch":        (0x4E78E28, "hero_drop"),   # points at what knows the things Link carries
}
