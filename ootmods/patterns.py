"""Find the places the module needs in a version of the game it was not built for.

A place is found through anchors: short runs of the game's instructions, with every part left out that depends
on where the code sits (branch distances, the addresses of pages). An anchor gives
    "at"    the place itself: instruction k of the run;
    "bl"    the routine that instruction k of the run calls;
    "adrp"  the data that instructions k (an adrp) and j (the add or load after it) address.
A place is taken as found when at least one of its anchors is in the game exactly once, and all that are say
the same.

tools/build_module.py --main makes the anchors from the version the module was built for (make); the installer
looks for them in the player's game (find).
"""
import array
import struct
import sys

FULL = 0xffffffff
PACIBSP = 0xd503237f


def signed(v, bits):
    return v - (1 << bits) if v >> (bits - 1) else v


def word_masks(words):
    """For each instruction, the bits that do not depend on where the code and the data sit."""
    out, pages = [], {}
    for i, w in enumerate(words):
        m = FULL
        if w & 0x7c000000 == 0x14000000:                # b, bl
            m = 0xfc000000
        elif w & 0xff000010 == 0x54000000:              # b.cond
            m = 0xff00001f
        elif w & 0x7e000000 == 0x34000000:              # cbz, cbnz
            m = 0xff00001f
        elif w & 0x7e000000 == 0x36000000:              # tbz, tbnz
            m = 0xfff8001f
        elif w & 0x1f000000 == 0x10000000:              # adr, adrp
            m = 0x9f00001f
            pages[w & 31] = i
        elif w & 0x3b000000 == 0x18000000:              # a load from a literal
            m = 0xff00001f
        else:
            rn = w >> 5 & 31
            if rn in pages and i - pages[rn] <= 6:      # the low part of an address that began with an adrp
                if w & 0x1f800000 == 0x11000000:        # add
                    m = 0xff8003ff
                elif w & 0x3b000000 == 0x39000000:      # a load or a store
                    m = 0xffc003ff
        out.append(m)
    return out


def key_run(masks):
    """The longest run of instructions with nothing left out: (first, count)."""
    best, at, n = (0, 0), 0, 0
    for i, m in enumerate(list(masks) + [0]):
        if m == FULL:
            if not n:
                at = i
            n += 1
        else:
            if n > best[1]:
                best = (at, n)
            n = 0
    return best


def search(text, words, masks, limit=2):
    """Where in the code the run is: its offsets, at most `limit`. `words` are already masked."""
    n = len(words)
    k, run = key_run(masks)
    if run < 1:
        return []
    key = struct.pack('<%dI' % run, *words[k:k + run])
    form = '<%dI' % n
    found = []
    pos = text.find(key)
    while pos >= 0:
        start = pos - 4 * k
        if pos % 4 == 0 and start >= 0 and start + 4 * n <= len(text):
            got = struct.unpack_from(form, text, start)
            if all(g & m == w for g, w, m in zip(got, words, masks)):
                found.append(start)
                if len(found) >= limit:
                    break
        pos = text.find(key, pos + 1)
    return found


def branch_to(text, at):
    w = struct.unpack_from('<I', text, at)[0]
    if w & 0x7c000000 != 0x14000000:
        return None
    return at + signed(w & 0x3ffffff, 26) * 4


def addressed(text, at, use):
    """The address made by the adrp at `at` and the add or load at `use`."""
    w = struct.unpack_from('<I', text, at)[0]
    u = struct.unpack_from('<I', text, use)[0]
    if w & 0x9f000000 != 0x90000000 or (u >> 5 & 31) != (w & 31):
        return None
    page = (at & ~0xfff) + (signed((w >> 5 & 0x7ffff) << 2 | (w >> 29 & 3), 21) << 12)
    imm = u >> 10 & 0xfff
    if u & 0x1f800000 == 0x11000000:
        return page + (imm << 12 if u >> 22 & 1 else imm)
    if u & 0x3b000000 == 0x39000000:
        scale = u >> 30
        if u >> 26 & 1 and u >> 23 & 1:         # a 128-bit register
            scale = 4
        return page + (imm << scale)
    return None


def value(anchor, text, start):
    kind = anchor['kind']
    if kind == 'at':
        return start + 4 * anchor['k']
    if kind == 'bl':
        return branch_to(text, start + 4 * anchor['k'])
    if kind == 'adrp':
        return addressed(text, start + 4 * anchor['k'], start + 4 * anchor['j'])
    return None


def unhex(s):
    return [int(s[i:i + 8], 16) for i in range(0, len(s), 8)]


def find(man, main, report=None):
    """Main-relative addresses of the module's places in this game: {'hook:x': a, 'code:x': a, 'data:x': a}
    for what was found. `report`, a dict, gets for every place how many of its anchors were found."""
    text = bytes(main.text)
    found = {}
    for name, anchors in man['patterns'].items():
        values, hits = set(), 0
        for a in anchors:
            at = search(text, unhex(a['words']), unhex(a['masks']))
            if len(at) != 1:
                continue
            v = value(a, text, at[0])
            if v is not None:
                values.add(v)
                hits += 1
        if len(values) == 1:
            found[name] = values.pop()
        if report is not None:
            report[name] = (hits if len(values) == 1 else 0, len(anchors))
    return found


# ---- making the anchors ----

def scan(text, routines, data):
    """One pass over the code: where the routines are called from, where the data is addressed, and which of
    the routines are called at all. ({routine: [bl]}, {data: [(adrp, use)]})"""
    words = array.array('I')
    words.frombytes(text[:len(text) & ~3])
    if sys.byteorder != 'little':
        words.byteswap()
    calls = {a: [] for a in routines}
    refs = {a: [] for a in data}
    pages = {a >> 12 for a in data}
    n = len(words)
    for i in range(n):
        w = words[i]
        if w >> 26 == 0x25:                                     # bl
            t = i * 4 + signed(w & 0x3ffffff, 26) * 4
            if t in calls:
                calls[t].append(i * 4)
        elif w & 0x9f000000 == 0x90000000:                      # adrp
            page = (i >> 10) + signed((w >> 5 & 0x7ffff) << 2 | (w >> 29 & 3), 21)
            if page in pages:
                for j in range(1, 5):
                    if i + j >= n:
                        break
                    u = words[i + j]
                    if (u >> 5 & 31) != (w & 31):
                        continue
                    a = addressed(text, i * 4, (i + j) * 4)
                    if a in refs:
                        refs[a].append((i * 4, j))
                        break
    return calls, refs


def anchor(text, kind, at, before, after, grow, extra=None):
    """An anchor around the instruction at `at`, as short as is still found once only (and then a little longer),
    or None. `grow` says which side gets longer: (before, after) per step."""
    limit = len(text)
    for _ in range(24):
        start = max(0, at - 4 * before)
        end = min(limit, at + 4 * after)
        words = list(struct.unpack_from('<%dI' % ((end - start) // 4), text, start))
        masks = word_masks(words)
        masked = [w & m for w, m in zip(words, masks)]
        if key_run(masks)[1] >= 2 and search(text, masked, masks) == [start]:
            # A little longer than needed: the same few instructions may turn up in code a new version adds.
            start = max(0, start - 4 * grow[0])
            end = min(limit, end + 4 * grow[1])
            words = list(struct.unpack_from('<%dI' % ((end - start) // 4), text, start))
            masks = word_masks(words)
            masked = [w & m for w, m in zip(words, masks)]
            if search(text, masked, masks) != [start]:
                return None
            out = dict(kind=kind, k=(at - start) // 4, words=''.join('%08x' % w for w in masked),
                       masks=''.join('%08x' % m for m in masks))
            if extra:
                out.update(extra(start))
            return out
        before += grow[0]
        after += grow[1]
    return None


def make(man, main, log=print):
    """Anchors for every place of the module, from the game it was built for: {place: [anchor]}."""
    text = bytes(main.text)
    hooks = {n: h['site'] for n, h in man['hooks'].items()}
    routines = {n: spec[1] for n, spec in man['code'].items() if spec[0] == 'at'}
    data = dict(man['data_at'])
    near = {}                                               # hook: how far the code after it must stay as it is
    for n, spec in man['code'].items():
        if spec[0] == 'near':
            near[spec[1]] = max(near.get(spec[1], 0), spec[2] // 4 + 2)
    calls, refs = scan(text, set(routines.values()) | set(hooks.values()), set(data.values()))
    known = sorted(set(hooks.values()) | set(routines.values()))

    def closest(sites, where=lambda s: s):
        """The few that are nearest to code the module uses anyway."""
        def distance(s):
            return min(abs(where(s) - k) for k in known)
        return sorted(sites, key=distance)[:8]

    out = {}
    for n, site in hooks.items():
        word = struct.unpack_from('<I', text, site)[0]
        start = word == PACIBSP or n in man.get('starts', []) or bool(calls[site])
        if start:       # the first instruction of a routine: what comes before belongs to another
            a = anchor(text, 'at', site, 0, max(10, near.get(n, 0)), (0, 4))
        else:           # inside a routine: both sides, since the trampoline counts on what the code around does
            a = anchor(text, 'at', site, 8, max(10, near.get(n, 0)), (2, 2))
        out['hook:' + n] = [a] if a else []
    for n, at in routines.items():
        found = []
        if branch_to(text, at) is None or struct.unpack_from('<I', text, at)[0] >> 26 == 0x25:
            a = anchor(text, 'at', at, 0, 10, (0, 4))
            if a:
                found.append(a)
        for site in closest(calls[at]):                     # and through the code that calls it
            if len(found) >= 3:
                break
            a = anchor(text, 'bl', site, 6, 6, (2, 2))
            if a:
                found.append(a)
        out['code:' + n] = found
    for n, at in data.items():
        found = []
        for site, j in closest(refs[at], lambda r: r[0]):
            if len(found) >= 3:
                break
            a = anchor(text, 'adrp', site, 5, 7, (2, 2), lambda start, site=site, j=j: dict(j=(site - start) // 4 + j))
            if a:
                found.append(a)
        out['data:' + n] = found

    class Main:                                             # every anchor must give its place back
        pass
    probe = Main()
    probe.text = text
    again = find(dict(patterns=out), probe)
    want = {'hook:' + n: a for n, a in hooks.items()}
    want.update({'code:' + n: a for n, a in routines.items()})
    want.update({'data:' + n: a for n, a in data.items()})
    for name in sorted(want):
        got = again.get(name)
        if got != want[name]:
            log('patterns: %s is NOT found by its anchors (%d anchors, got %s)'
                % (name, len(out[name]), 'nothing' if got is None else hex(got)))
    sizes = [len(a['words']) // 8 for v in out.values() for a in v]
    log('patterns: %d places, %d anchors of %d to %d instructions' % (len(out), len(sizes), min(sizes), max(sizes)))
    return out
