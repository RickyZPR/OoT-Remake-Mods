"""Fit the mod module to one copy of the game: where it will sit, its branches into the game, the game's
branches into it."""
import hashlib
import json
import os
import struct

from . import nso

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODULE_NAME = 'subsdk9'
ORDER = ['main'] + ['subsdk%d' % i for i in range(10)]      # the order the game's modules are loaded in

SET_OPT, SET_AVAIL, SET_BEAT = 16, 112, 128                 # offsets inside the settings block
TAB_DELTA, TAB_DATA = 8, 16                                 # offsets inside the table


class PlaceError(Exception):
    pass


def load_module():
    with open(os.path.join(HERE, 'module', 'manifest.json'), encoding='utf-8') as f:
        man = json.load(f)
    with open(os.path.join(HERE, 'module', 'module.bin'), 'rb') as f:
        image = bytearray(f.read())
    if hashlib.sha256(image).hexdigest() != man['module_sha256']:
        raise PlaceError('module/module.bin does not match module/manifest.json')
    return man, image


def module_address(sizes):
    """Address of the mod module relative to main, from the loaded sizes of the game's modules
    ({'main': n, 'subsdk0': n, ...}). The modules sit back to back in load order."""
    at = 0
    for name in ORDER:
        if name == MODULE_NAME:
            return at
        at += sizes.get(name, 0)
    raise PlaceError('no place for the module')


def branch(src, dst, link):
    delta = dst - src
    if delta & 3 or not -(1 << 27) <= delta < (1 << 27):
        raise PlaceError('branch out of range: 0x%X -> 0x%X' % (src, dst))
    return (0x94000000 if link else 0x14000000) | (delta >> 2 & 0x3ffffff)


def branch_target(site, word):
    """Where the branching instruction `word` at `site` goes, or None if it is not a branch with a fixed target."""
    def signed(v, bits):
        return v - (1 << bits) if v >> (bits - 1) else v
    if word & 0x7c000000 == 0x14000000:                         # b, bl
        return site + signed(word & 0x3ffffff, 26) * 4
    if word & 0x7e000000 == 0x34000000 or word & 0xff000010 == 0x54000000:      # cbz, cbnz, b.cond
        return site + signed(word >> 5 & 0x7ffff, 19) * 4
    if word & 0x7e000000 == 0x36000000:                         # tbz, tbnz
        return site + signed(word >> 5 & 0x3fff, 14) * 4
    return None


def code_feature(man, name):
    """The part of the mod a piece of game code belongs to."""
    spec = man['code'][name]
    return spec[2] if spec[0] == 'at' else man['hooks'][spec[1]]['feature']


def code_address(spec, site, word):
    """Address of one entry of the table's CODE that hangs on a hook: the hook is at `site` and the game's own
    instruction there is `word`."""
    kind = spec[0]
    if kind == 'after':
        return site + 4
    if kind == 'self':
        return site
    if kind == 'near':
        return site + spec[2]
    if kind == 'target':
        return branch_target(site, word)
    raise PlaceError('unknown kind of code: %r' % (spec,))


def nominal(man):
    """The game's addresses in the version the module was built against."""
    found = {'hook:' + n: h['site'] for n, h in man['hooks'].items()}
    found.update({'data:' + n: a for n, a in man['data_at'].items()})
    found.update({'code:' + n: spec[1] for n, spec in man['code'].items() if spec[0] == 'at'})
    return found


def resolve_code(man, found, word_at):
    """Addresses of the game code the module branches to: {name: address}, for what was found. word_at(site)
    gives the game's own instruction there (without this mod's branches)."""
    out = {}
    for name, spec in man['code'].items():
        if spec[0] == 'at':
            addr = found.get('code:' + name)
        else:
            site = found.get('hook:' + spec[1])
            addr = None if site is None else code_address(spec, site, word_at(site))
        if addr is not None:
            out[name] = addr
    return out


def features(man, found, code):
    """{feature: installed?}. A part is installed only if every place it needs was found."""
    ok = {f: True for f in man['features']}
    for name, h in man['hooks'].items():
        if 'hook:' + name not in found:
            ok[h['feature']] = False
    for name in man['data_names']:
        if 'data:' + name not in found:
            ok[man['data_feature'][name]] = False
    for name in man['code']:
        if name not in code:
            ok[code_feature(man, name)] = False
    for f, other in man.get('needs', {}).items():
        if not ok[other]:
            ok[f] = False
    if not ok['core']:
        ok = {f: False for f in ok}
    return ok


def place(man, image, at, found, word_at):
    """Return (module NSO, patches, features) for a game whose main-relative addresses are in `found`.

    patches = [(address in main's text, new instruction word)]; features = {name: installed?}."""
    image = bytearray(image)
    code = resolve_code(man, found, word_at)
    ok = features(man, found, code)
    if not ok['core']:
        raise PlaceError('cannot find the places every mod needs (the frame and the controller) in this game')

    # The module's branches into the game. Those of a part that is not installed go to a routine of the module
    # that just returns: nothing runs them, but nothing may point into the game at a guess either.
    for off, name, addend, op in man['fixups']:
        dst = code[name] + addend if ok[code_feature(man, name)] else at + man['stub']
        struct.pack_into('<I', image, off, branch(at + off, dst, op == 'bl'))

    tab = man['table']
    struct.pack_into('<q', image, tab + TAB_DELTA, at)
    for i, name in enumerate(man['data_names']):
        struct.pack_into('<I', image, tab + TAB_DATA + 4 * i, found.get('data:' + name, 0))
    for i, f in enumerate(man['features']):
        image[man['settings'] + SET_AVAIL + i] = 1 if ok[f] else 0

    patches = []
    for name, h in man['hooks'].items():
        if ok[h['feature']]:
            site = found['hook:' + name]
            patches.append((site, branch(site, at + h['entry'], h['op'] == 'bl')))

    mod = nso.Nso()
    for i, key in enumerate(('text', 'rodata', 'data')):
        off, size = man[key]
        mod.seg[i] = (off, bytearray(image[off:off + size]))
    mod.bss = man['bss']
    mod.module_id = hashlib.sha256(image).digest()[:20] + bytes(12)
    mod.extents = struct.pack('<6I', 0, 0, man['dynstr'][0], man['dynstr'][1], man['dynsym'][0], man['dynsym'][1])
    return mod.build(), patches, ok


def ips32(patches):
    """An IPS32 patch for main (offsets count the 0x100-byte NSO header, as emulators expect)."""
    out = bytearray(b'IPS32')
    for site, word in sorted(patches):
        out += struct.pack('>IH', site + 0x100, 4) + struct.pack('<I', word)
    return bytes(out + b'EEOF')


def patch_main(raw, patches):
    """A copy of the game's main (the bytes of its NSO file) with the branches written in."""
    flags = struct.unpack_from('<I', raw, 12)[0]
    off, mem, size = struct.unpack_from('<III', raw, 16)
    if flags & 1:                           # compressed text: written back plain
        main = nso.Nso(raw)
        for site, word in patches:
            struct.pack_into('<I', main.text, site, word)
        return main.build()
    out = bytearray(raw)                    # everything else in the file stays as it was
    for site, word in patches:
        struct.pack_into('<I', out, off + site - mem, word)
    out[0xa0:0xc0] = hashlib.sha256(out[off:off + size]).digest()
    return bytes(out)
