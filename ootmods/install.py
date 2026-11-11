"""Put the mod into a copy of the game: an emulator's mod folder, or a Hookshot game folder."""
import json
import mmap
import os
import shutil
import struct

from . import nso, place, settings

MOD_NAME = 'OoT Mods'
KEPT = '.hookshot_exefs'            # a Hookshot game folder keeps the game's code here and rebuilds from it
RECORD = '.ootmods.json'            # in a Hookshot game folder: what this installer changed in that code
EMU_RECORD = 'ootmods.json'         # in an emulator's "OoT Mods" folder: what was installed


class InstallError(Exception):
    pass


class Game:
    """The game's code modules: {name: bytes of the NSO file}."""

    def __init__(self, files):
        if 'main' not in files:
            raise InstallError("the game's main module is missing")
        self.files = files
        try:
            self.main = nso.Nso(files['main'])
            self.sizes = {n: nso.Nso(raw).size() for n, raw in files.items() if n != place.MODULE_NAME}
        except (ValueError, struct.error) as e:
            raise InstallError("the game's code cannot be read: %s" % e)
        self.build_id = self.main.build_id


def read_exefs(folder):
    files = {}
    for name in place.ORDER:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            with open(path, 'rb') as f:
                files[name] = f.read()
    return Game(files)


def locate(man, game):
    """(main-relative addresses of the places the module needs, a function that gives the game's own
    instruction at an address). With no game: the version the module was built against, from the manifest."""
    words = {h['site']: int(h['orig'], 16) for h in man['hooks'].values()}
    if game is None:
        return place.nominal(man), words.__getitem__
    if game.build_id == man['game_build_id'] or not man.get('patterns'):
        found = place.nominal(man)
        try:
            for name, h in man['hooks'].items():        # the same build must have the same instructions
                if game.main.word(h['site']) != words[h['site']]:
                    found.pop('hook:' + name)
        except nso.NsoError:                # packed code and nothing to open it with: the build says enough
            return place.nominal(man), words.__getitem__
        return found, game.main.word
    from . import patterns
    return patterns.find(man, game.main), game.main.word


class Fit:
    """The module made to fit one copy of the game. Without a game: the version it was built against."""

    def __init__(self, game=None):
        self.game = game
        try:
            self.man, image = place.load_module()
            self.found, word_at = locate(self.man, game)
            if game is None:
                self.build_id, self.at = self.man['game_build_id'], self.man['nominal_base']
            else:
                self.build_id, self.at = game.build_id, place.module_address(game.sizes)
            self.module, self.patches, self.features = place.place(self.man, image, self.at, self.found, word_at)
        except (place.PlaceError, nso.NsoError) as e:
            raise InstallError(str(e))
        except (ValueError, IndexError, struct.error) as e:
            raise InstallError("the game's code cannot be read: %s" % e)
        self.known = self.build_id == self.man['game_build_id']

    def missing(self):
        return [f for f, ok in self.features.items() if not ok]

    def sites(self):
        return [site for site, word in self.patches]


def write_file(path, data):
    tmp = path + '.part'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def read_json(path):
    try:
        with open(path, encoding='utf-8') as f:
            value = json.load(f)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path, value):
    write_file(path, json.dumps(value, indent=1).encode('utf-8'))


def current_sha():
    return place.load_module()[0]['module_sha256']


# ---- emulators ----

def write_emulator(fit, mods_dir, values=None, ran=''):
    """Write the mod for Fritchii, Eden and other emulators: <mods_dir>/OoT Mods/exefs. The switches are the
    given ones, or those of the mod already there. `ran`: the build of the game the emulator ran last, as far
    as its log says; it is kept to tell later when the game was updated."""
    folder = os.path.join(mods_dir, MOD_NAME)
    exefs = os.path.join(folder, 'exefs')
    module = os.path.join(exefs, place.MODULE_NAME)
    os.makedirs(exefs, exist_ok=True)
    if values is None:
        values = settings.carried(module)
    for old in os.listdir(exefs):
        if old.lower().endswith('.ips'):
            os.remove(os.path.join(exefs, old))         # a patch for an earlier version of the game
    write_file(module, settings.module_with(fit.module, values))
    write_file(os.path.join(exefs, fit.build_id + '.ips'), place.ips32(fit.patches))
    write_json(os.path.join(folder, EMU_RECORD),
               dict(format=1, module_sha256=fit.man['module_sha256'], build_id=fit.build_id,
                    fitted=fit.game is not None, features=fit.features, sites=fit.sites(), ran=ran))
    return exefs


def emulator_state(mods_dir):
    """(state, record) of the mod in an emulator's folder for the game:
    'absent', 'ok', 'old' (an earlier version of the mod), 'broken' (files are missing)."""
    folder = os.path.join(mods_dir, MOD_NAME)
    exefs = os.path.join(folder, 'exefs')
    module = os.path.join(exefs, place.MODULE_NAME)
    rec = read_json(os.path.join(folder, EMU_RECORD))
    have = os.path.isfile(module)
    ips = [n for n in os.listdir(exefs) if n.lower().endswith('.ips')] if os.path.isdir(exefs) else []
    if not have and not ips and rec is None:
        return 'absent', None
    if not have or not ips or settings.read_file(module) is None:
        return 'broken', rec
    if rec is None or rec.get('module_sha256') != current_sha():
        return 'old', rec
    return 'ok', rec


def remove_emulator(mods_dir):
    folder = os.path.join(mods_dir, MOD_NAME)
    if os.path.isdir(folder):
        shutil.rmtree(folder)


def emulator_save(mods_dir, values):
    """Set the switches the game starts with in an emulator. False when the mod is not there."""
    return settings.write_module(os.path.join(mods_dir, MOD_NAME, 'exefs', place.MODULE_NAME), values)


def ips_records(data):
    """[(offset, length)] of the records of an IPS or IPS32 patch."""
    if data[:5] == b'IPS32':
        wide, end = 4, b'EEOF'
    elif data[:5] == b'PATCH':
        wide, end = 3, b'EOF'
    else:
        return []
    pos, out = 5, []
    while pos + wide + 2 <= len(data) and data[pos:pos + len(end)] != end:
        off = int.from_bytes(data[pos:pos + wide], 'big')
        size = int.from_bytes(data[pos + wide:pos + wide + 2], 'big')
        pos += wide + 2
        if size == 0:                                   # a run of one byte
            size = int.from_bytes(data[pos:pos + 2], 'big')
            pos += 3
        else:
            pos += size
        out.append((off, size))
    return out


def same_build(name, build_id):
    """True when a patch file's name says it is for this build of the game (emulators pad the shorter of the
    two with zeros)."""
    stem = name.split('.')[0].upper().rstrip('0')
    return bool(stem) and stem == build_id.upper().rstrip('0')


def conflicts(mods_dir, sites, build_id):
    """Other mods in an emulator's folder for the game that get in this one's way: [(mod, why)]. `sites` are
    the addresses in main where this mod writes a branch."""
    out = []
    if not os.path.isdir(mods_dir):
        return out
    for name in sorted(os.listdir(mods_dir)):
        exefs = os.path.join(mods_dir, name, 'exefs')
        if name == MOD_NAME or not os.path.isdir(exefs):
            continue
        for f in sorted(os.listdir(exefs)):
            low = f.lower()
            if low in ('main', 'rtld', 'sdk') or (low.startswith('subsdk') and '.' not in low):
                out.append((name, "it replaces the game's code file %s" % f))
            elif low.endswith('.ips') and same_build(f, build_id):
                try:
                    with open(os.path.join(exefs, f), 'rb') as h:
                        recs = ips_records(h.read())
                except OSError:
                    continue
                if any(off < s + 0x104 and s + 0x100 < off + size for s in sites for off, size in recs):
                    out.append((name, 'its patch %s changes the same instructions' % f))
    return out


# ---- Hookshot ----

def words_at(path, sites):
    """The instructions at some addresses of a module file's code."""
    with open(path, 'rb') as f:
        head = f.read(0x100)
        if len(head) < 0x100 or head[:4] != b'NSO0':
            raise InstallError('%s is not a code module' % path)
        off, mem, size = struct.unpack_from('<III', head, 16)
        if struct.unpack_from('<I', head, 12)[0] & 1:           # packed: opened whole
            f.seek(0)
            main = nso.Nso(f.read())
            return [main.word(s) for s in sites]
        out = []
        for s in sites:
            f.seek(off + s - mem)
            out.append(struct.unpack('<I', f.read(4))[0])
        return out


def hookshot_read(game_dir):
    """The game's code as the builder read it from the dump, with this installer's earlier changes undone."""
    kept = os.path.join(game_dir, KEPT)
    if not os.path.isfile(os.path.join(kept, 'main')):
        raise InstallError('%s has no %s folder with the game\'s code: build the game with Hookshot Builder first'
                           % (game_dir, KEPT))
    game = read_exefs(kept)
    rec = read_json(os.path.join(game_dir, RECORD))
    if rec and rec.get('patches'):
        try:
            ours = [game.main.word(site) == new for site, orig, new in rec['patches']]
        except (nso.NsoError, struct.error, ValueError) as e:
            raise InstallError("the game's code in %s cannot be read: %s" % (kept, e))
        if all(ours):
            files = dict(game.files)
            files['main'] = place.patch_main(files['main'], [(site, orig) for site, orig, new in rec['patches']])
            game = Game(files)
        elif any(ours):
            raise InstallError('the game code in %s was changed by something else: build the game again from your '
                               'dump with Hookshot Builder, then install the mod' % kept)
        # None of them: the builder read the dump again, or an install was cut off before it wrote its branches
        # (write_hookshot keeps to an order that leaves no other case). The code is the game's own.
    return game


def write_hookshot(fit, game_dir, values=None):
    """Put the mod into the code a Hookshot game folder is built from. The folder must then be built again.
    The switches are the given ones, or those of the mod already there."""
    if fit.game is None:
        raise InstallError('a Hookshot game folder is fitted to its own code')
    kept = os.path.join(game_dir, KEPT)
    module = os.path.join(kept, place.MODULE_NAME)
    not_ours(module)
    if values is None:
        values = settings.carried(module)
    rec = dict(format=1, module_sha256=fit.man['module_sha256'], build_id=fit.build_id, at=fit.at,
               features=fit.features,
               patches=[[site, fit.game.main.word(site), word] for site, word in fit.patches])
    # In an order that a job cut off anywhere (a crash, a full disk) cannot spoil: the record always tells the
    # truth about the branches in main, or main has none. Then the folder reads as 'dropped', and the next
    # install does it all again.
    record = os.path.join(game_dir, RECORD)
    main = os.path.join(kept, 'main')
    if read_json(record):                           # an earlier install: its branches leave the code first
        write_file(main, fit.game.files['main'])
    write_json(record, rec)
    write_file(module, settings.module_with(fit.module, values))
    write_file(main, place.patch_main(fit.game.files['main'], fit.patches))


def not_ours(module):
    """Stop when the place of the mod's module holds a module of something else."""
    if os.path.isfile(module) and settings.read_file(module) is None:
        raise InstallError('%s is not a file of this mod: another mod uses the same place in the game\'s code, '
                           'and the two cannot be in it together. (If it is a leftover, delete that file.)' % module)


def remove_hookshot(game_dir):
    """Take the mod out of a Hookshot game folder's code. The folder must then be built again."""
    game = hookshot_read(game_dir)              # main as it was
    kept = os.path.join(game_dir, KEPT)
    module = os.path.join(kept, place.MODULE_NAME)
    write_file(os.path.join(kept, 'main'), game.files['main'])
    if settings.read_file(module) is not None:  # (a module that is not this mod's is not this mod's to delete)
        os.remove(module)
    if os.path.exists(os.path.join(game_dir, RECORD)):
        os.remove(os.path.join(game_dir, RECORD))


def image_module(game_dir):
    """Where the mod sits in a Hookshot game's memory image: (offset of the module in image.bin, offset of the
    settings block in image.bin), or None when the image has no mod in it or the kept module is not there."""
    try:
        with open(os.path.join(game_dir, KEPT, place.MODULE_NAME), 'rb') as f:
            raw = f.read()
    except OSError:
        return None
    in_file = settings.find(raw)
    got = settings.read_file(os.path.join(game_dir, 'image.bin'))
    if in_file < 0 or got is None or raw[:4] != b'NSO0':
        return None
    off, mem, size = struct.unpack_from('<III', raw, 16 + 32)       # the module's data: the block is in it
    start = got[0] - (mem + in_file - off)
    return (start, got[0]) if start >= 0 else None


def hookshot_built(game_dir, rec=None):
    """True when the game in the folder was built from the code that is kept there now: its memory image
    (image.bin) holds this very module, and the game's branches into it."""
    where = image_module(game_dir)
    if where is None:
        return False
    start = where[0]
    try:
        text = bytes(nso.load(os.path.join(game_dir, KEPT, place.MODULE_NAME)).text)
        with open(os.path.join(game_dir, 'image.bin'), 'rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                if data[start:start + len(text)] != text:
                    return False
                if rec and 'at' in rec:
                    main = start - rec['at']
                    for site, orig, new in rec['patches']:
                        if main < 0 or data[main + site:main + site + 4] != struct.pack('<I', new):
                            return False
    except (OSError, ValueError, struct.error, nso.NsoError):
        return False
    return True


def hookshot_state(game_dir):
    """(state, record) of the mod in a Hookshot game folder:
    'nofolder'  the folder has no kept code: Hookshot Builder did not build it, or an old one did
    'absent'    the mod is not in it
    'dropped'   the builder read the dump again, and the mod went with the old code
    'broken'    only a part of the mod is there
    'old'       an earlier version of the mod is in it
    'unbuilt'   the mod is in the kept code, and the game has not been built from it yet
    'ok'        installed and built"""
    kept = os.path.join(game_dir, KEPT)
    main = os.path.join(kept, 'main')
    module = os.path.join(kept, place.MODULE_NAME)
    if not os.path.isfile(main):
        return 'nofolder', None
    rec = read_json(os.path.join(game_dir, RECORD))
    if not rec or not rec.get('patches'):
        return ('broken' if settings.read_file(module) else 'absent'), None
    try:
        got = words_at(main, [site for site, orig, new in rec['patches']])
    except (OSError, struct.error, ValueError, TypeError, InstallError, nso.NsoError):
        return 'broken', rec
    ours = [w == new for w, (site, orig, new) in zip(got, rec['patches'])]
    if not any(ours):
        return 'dropped', rec
    if not all(ours) or settings.read_file(module) is None:
        return 'broken', rec
    if rec.get('module_sha256') != current_sha():
        return 'old', rec
    return ('ok' if hookshot_built(game_dir, rec) else 'unbuilt'), rec


def hookshot_save(game_dir, values):
    """Set the switches a Hookshot game starts with: in the kept module (what the next build is made from) and
    in the built game's memory image. Returns (kept written, image written)."""
    try:
        kept = settings.write_module(os.path.join(game_dir, KEPT, place.MODULE_NAME), values)
    except OSError:
        kept = False
    try:
        image = settings.write_image(os.path.join(game_dir, 'image.bin'), values)
    except OSError:
        image = False
    return kept, image
