"""The mod's switches: where each one lives in the settings block, what it starts as, and how the Mods window
shows it. The module is built from this list too (tools/build_module.py), so the two cannot disagree.

Never reorder or remove an entry: a switch keeps its place for good, so settings carry over to a newer mod."""

# The bit each button has in the controller's state.
BUTTONS = {"A": 0, "B": 1, "X": 2, "Y": 3, "L3": 4, "R3": 5, "L": 6, "R": 7, "ZL": 8, "ZR": 9,
           "Plus": 10, "Minus": 11, "Left": 12, "Up": 13, "Right": 14, "Down": 15}

BUTTON_TEXT = {"L3": "L3 (click the left stick)", "R3": "R3 (click the right stick)", "Up": "D-pad up",
               "Down": "D-pad down", "Left": "D-pad left", "Right": "D-pad right", "Minus": "Minus (-)"}

# kind "switch": 0 or 1.
# kind "button": the place of the chosen button in `buttons` ("Off" = no button).
# kind "number": a value from `least` to `most`.
# feature: the part of the module that must have been installed for the switch to do anything.
OPTIONS = [
    dict(key="shield", start=1, kind="switch", feature="shield", text="Manual shield",
         help="The shield comes up only while you hold the shield button. L turns Z-targeting on and off "
              "(R3 turns it off)."),
    dict(key="shield_button", start=0, kind="button", feature="shield", text="Shield button",
         buttons=["ZL", "ZR", "L", "R", "R3", "L3"],
         help="The button you hold to raise the shield. It changes places with ZL."),
    dict(key="crouch", start=1, kind="switch", feature="crouch", text="Crouch behind the shield",
         help="Young Link crouches behind his shield when it comes up with no target, as on the N64."),
    dict(key="swap", start=1, kind="switch", feature="swap", text="Quick swap",
         help="Hold the button to remember the item in your hands; tap it to swap to that item and back. "
              "Open the item selector (R) once after starting the game."),
    dict(key="swap_button", start=0, kind="button", feature="swap", text="Quick swap button",
         buttons=["L3", "R3", "Up", "Right", "Minus"],
         help="The game does not get this button in play. It may also be the sprint button."),
    dict(key="sprint", start=1, kind="button", feature="sprint", text="Sprint button",
         buttons=["Off", "L3", "R3", "B", "ZR"],
         help="Hold it while running to run faster. Link does not roll."),
    dict(key="sprint_speed", start=140, kind="number", feature="sprint", text="Sprint speed", least=110, most=200,
         step=5, unit="%", help="How fast the sprint is, against the normal run."),
    dict(key="autojump", start=1, kind="switch", feature="autojump", text="Auto-jump",
         help="Link jumps by himself when he runs off a ledge, as on the N64."),
    dict(key="hero", start=0, kind="switch", feature="hero", text="Hero Mode",
         help="Link takes double damage, enemies take half and attack twice as often, and once Link has a sword "
              "and a shield, grass gives no hearts or rupees."),
]

INDEX = {o["key"]: i for i, o in enumerate(OPTIONS)}


def button_mask(name):
    return 0 if name == "Off" else 1 << BUTTONS[name]


def button_text(name):
    return BUTTON_TEXT.get(name, name)


# The parts of the module, as the installer names them when one cannot be fitted to a version of the game.
FEATURE_TEXT = {"core": "the mod's base", "shield": "Manual shield", "ocarina": "playing the ocarina with a moved button",
                "crouch": "Crouch behind the shield", "swap": "Quick swap", "sprint": "Sprint", "autojump": "Auto-jump",
                "hero": "Hero Mode", "hero_drop": "Hero Mode: no hearts or rupees from grass",
                "hero_interval": "Hero Mode: enemies attack twice as often"}


def feature_text(name):
    return FEATURE_TEXT.get(name, name)


def chosen(values, key):
    """The button a button switch is set to."""
    return OPTIONS[INDEX[key]]["buttons"][values[INDEX[key]]]


def clashes(values):
    """What does not go together in a set of switches: [text]. The game still runs with them; one of the two
    buttons just does not do its second job."""
    out = []
    shield, swap, sprint = chosen(values, "shield_button"), chosen(values, "swap_button"), chosen(values, "sprint")
    if values[INDEX["shield"]]:
        if values[INDEX["swap"]] and shield == swap:
            out.append("The shield and quick swap are both on %s: choose another button for one of them."
                       % button_text(shield))
        if shield == sprint:
            out.append("The shield and the sprint are both on %s: choose another button for one of them."
                       % button_text(shield))
    return out


def notes(values):
    """Things worth knowing about a set of switches: [text]."""
    out = []
    swap, sprint = chosen(values, "swap_button"), chosen(values, "sprint")
    if values[INDEX["shield"]] and "R3" in (swap if values[INDEX["swap"]] else "", sprint):
        out.append("With Manual shield on, R3 also turns Z-targeting off.")
    if values[INDEX["swap"]] and swap == sprint:
        out.append("Quick swap and sprint share %s: a tap swaps, a hold while standing remembers the item, a hold "
                   "while running sprints." % button_text(swap))
    return out


def show_value(o, v):
    if o["kind"] == "switch":
        return "on" if v else "off"
    if o["kind"] == "button":
        return o["buttons"][v]
    return "%d%s" % (v, o.get("unit", ""))


def parse_value(o, text):
    """The value a player typed for a switch ("on", "R3", "150%"). Raises ValueError when it is not one."""
    t = text.strip().lower()
    if o["kind"] == "switch":
        if t in ("1", "on", "yes", "true"):
            return 1
        if t in ("0", "off", "no", "false"):
            return 0
    elif o["kind"] == "button":
        for i, name in enumerate(o["buttons"]):
            if t == name.lower():
                return i
    else:
        t = t.rstrip("%")
        if t.isdigit() and o["least"] <= int(t) <= o["most"]:
            return int(t)
    raise ValueError(text)


def choices(o):
    """What a switch can be set to, as a player types it."""
    if o["kind"] == "switch":
        return "on or off"
    if o["kind"] == "button":
        return ", ".join(o["buttons"])
    return "%d to %d" % (o["least"], o["most"])
