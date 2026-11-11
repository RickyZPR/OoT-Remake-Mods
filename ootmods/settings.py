"""The mod's settings block: finding it, and reading and writing the switches in it.

The block starts the module's data: "OOTMODS1", u16 layout, u16 the number of switches the module knows,
u32 size, opt[96], avail[16], u32 beat, u32 stat[15]. It is found by its first eight bytes: in the installed
module (an NSO file), in a Hookshot game's image.bin, and in the memory of a running game (live.py)."""
import mmap
import os
import struct

from . import nso
from .options import OPTIONS

MAGIC = b'OOTMODS1'
SIZE = 192
COUNT, OPT, AVAIL, BEAT, STAT = 10, 16, 112, 128, 132
STATS = ['frames', 'pads', 'dual', 'full', 'left', 'right', 'hand', 'swaps', 'remembered', 'shield', 'jumps',
         'damage', 'drops', 'ocarina', 'sprint']


def defaults():
    return [o['start'] for o in OPTIONS]


def fits(i, v):
    """True when v is a value switch i can have."""
    o = OPTIONS[i]
    if o['kind'] == 'switch':
        return v in (0, 1)
    if o['kind'] == 'button':
        return 0 <= v < len(o['buttons'])
    return o['least'] <= v <= o['most']


def clean(values, count=None):
    """A value for every switch: the given ones where they are valid (the first `count` of them, if given),
    the starting values for the rest."""
    out = defaults()
    n = len(values) if count is None else min(count, len(values))
    for i in range(min(n, len(out))):
        if fits(i, values[i]):
            out[i] = values[i]
    return out


def check(block):
    """True when these bytes start a settings block of the layout this code knows."""
    if len(block) < SIZE or bytes(block[:8]) != MAGIC:
        return False
    version, _, size = struct.unpack_from('<HHI', block, 8)
    return version == 1 and size == SIZE


def parse(block):
    return dict(count=struct.unpack_from('<H', block, COUNT)[0], opt=list(block[OPT:OPT + 96]),
                avail=list(block[AVAIL:AVAIL + 16]), beat=struct.unpack_from('<I', block, BEAT)[0],
                stat=list(struct.unpack_from('<15I', block, STAT)))


def find(data):
    """Where the settings block starts in some bytes, or -1."""
    pos = data.find(MAGIC)
    while pos >= 0:
        if check(data[pos:pos + SIZE]):
            return pos
        pos = data.find(MAGIC, pos + 1)
    return -1


def read_file(path):
    """The settings block of a file: (where it starts, its contents), or None."""
    try:
        with open(path, 'rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:     # an image.bin is 100 MB
                pos = find(data)
                return None if pos < 0 else (pos, parse(data[pos:pos + SIZE]))
    except (OSError, ValueError):           # not there, or empty
        return None


def carried(path):
    """The switches as an installed module has them, to keep them when it is replaced."""
    got = read_file(path)
    return clean(got[1]['opt'], got[1]['count']) if got else defaults()


def put(data, pos, values):
    """Write the switches into a block (in a bytearray). A module is given only the ones it knows."""
    count = struct.unpack_from('<H', data, pos + COUNT)[0]
    vals = clean(values)[:count]
    data[pos + OPT:pos + OPT + len(vals)] = bytes(vals)
    return len(vals)


def module_with(module, values):
    """A module's file (an NSO as nso.Nso.build() makes it) with these switches as its starting ones."""
    raw = bytearray(module)
    pos = find(raw)
    if pos < 0:
        raise ValueError('the module has no settings block')
    put(raw, pos, values)
    return nso.rehash(raw)


def write_module(path, values):
    """Set the switches in an installed module. False when the file is not there or has no block."""
    try:
        with open(path, 'rb') as f:
            raw = f.read()
    except OSError:
        return False
    if find(raw) < 0:
        return False
    new = module_with(raw, values)
    if new == raw:
        return True                 # it has them already: the file is left alone
    tmp = path + '.part'
    with open(tmp, 'wb') as f:
        f.write(new)
    os.replace(tmp, path)
    return True


def write_image(path, values):
    """Set the switches in a Hookshot game's image.bin, in place (the file is a hundred megabytes: only the
    switches are written). False when the file is not there or has no block."""
    got = read_file(path)
    if not got:
        return False
    vals = bytes(clean(values)[:got[1]['count']])
    if bytes(got[1]['opt'][:len(vals)]) == vals:
        return True                 # it has them already
    with open(path, 'r+b') as f:
        f.seek(got[0] + OPT)
        f.write(vals)
    return True
