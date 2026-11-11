"""The hookshot targets of the N64 game, as a file mod built from the game's own collision data.

Every collision material is a 16-byte entry {u32 material, u32 kind, u64 flags}. Bit 44 of the flags is the game's
own "StickHookshot": the hookshot latches on to such a surface and pulls Link to it. The mod sets that bit and
changes nothing else. The entries live in two places, and both are patched:

  Phive/Shape/Dcc/<name>__Physical.Nin_Ounce_NVN2.bphsh.zs
      one object's own shape. The game reads it only for objects that are not part of the baked map.
  Phive/StaticCompoundBody/<Scene>/<Scene>[_Child|_Adult]_X<n>_Z<n>.Nin_Ounce_NVN2.bphsc.zs
      the baked collision of one square of a map: every placed object of that square (bridges, torch stands, trees,
      chests ...) with its own run of entries. This is what the game uses for almost everything that stands in a
      map, so a mod that only ships the loose shape of a bridge does nothing.

  N64 targets   the wood of bridges, beams, scaffolds, awnings, large crates and Kakariko's houses (their roofs),
                and every torch stand (stone and metal too: on the N64 a torch stand pulls Link whatever it is
                made of)
  trees         the wood of trees, stumps and fallen logs. The N64 game does not latch on to trees: an extra.

Both go into ONE mod folder: emulators and Hookshot disagree about which of two mods wins a file both ship, so two
folders that share map squares cannot be made to work everywhere.

The files are made from the player's own game and are never part of this project. Needs the zstandard package.
"""
import json
import os
import re
import struct
from concurrent.futures import ThreadPoolExecutor

NAME = 'OoT Mods - Hookshot Targets'
STAMP = 'ootmods-files.json'
# Earlier mods whose files this one has too (with the same changes): they are switched off beside it.
SUPERSEDED = ['Hookshot Crates', 'Hookshot N64 Targets', 'Hookshot Trees']

SHAPE_DIR = 'Phive/Shape/Dcc/'
CELL_DIR = 'Phive/StaticCompoundBody/'
SHAPE_SUFFIX = '__Physical.Nin_Ounce_NVN2.bphsh.zs'
WOOD = (0xe, 0x2c)        # Wood, WoodSlip
NOT_SOLID = (0x0, 0x1b)   # no material (sensor shapes), AirWall: never marked
TARGETS, TREES = 'targets', 'trees'

# (the wood entries of these)
BRIDGES = """Land_Kokiri_FieldProp_Bridge_A_01 Land_Kokiri_FieldProp_LogBridge_A_01 Land_Kokiri_FieldProp_LogBridge_A_02
Land_LakeHrl_Bridge_A_01 Land_LakeHrl_Bridge_A_02 Land_LakeHrl_Bridge_A_03 Land_LakeHrl_FishingPondBridge_A_01
Land_GerudoValley_LogBridge_A_01 Land_GerudoValley_BridgeGate_A_01 Obj_GerudoValley_Bridge_A_01
Obj_GerudoValley_Bridge_A_02 Obj_GerudoValley_Bridge_A_03 Land_HrlField_DrawBridge_A_01 Land_HrlField_DrawBridge_A_02
Land_HrlField_DrawBridgeBroken_A_01 Land_Desert_Jetty_A_01 Land_Desert_HookTarget_A_01"""
BEAMS = """Land_Gerudo_FortressAbandonWood_A_01 Land_Gerudo_FortressAbandonWood_A_02 Land_Gerudo_FortressAbandonWood_A_03
Land_Gerudo_FortressAbandonWood_A_04 Land_Gerudo_FortressAbandonWood_A_05 Land_Gerudo_FortressHouseHSScaffold_A_01
Land_Gerudo_FortressPotRoom_Beam_A_01 Land_Gerudo_FortressHouseBeam_A_01 Land_Gerudo_FortressExteriorAwning_A_01
Land_Gerudo_FortressExteriorAwning_A_02 Land_Gerudo_FortressExteriorAwning_A_03 Land_Gerudo_FortressExteriorAwning_A_04
Land_Gerudo_FortressExteriorAwning_A_06 Land_Gerudo_FortressExteriorAwning_A_07 Land_Gerudo_FortressHouseTop_A_01
Land_Gerudo_FortressHouseTop_A_02 Land_Gerudo_FortressHouseTop_A_04 Land_Gerudo_FortressHouseTop_A_05
Land_LakeHrl_FishingPondScaffold_A_01 Land_SpiritTemple_MineTimber_A_01"""
# (the large crates: the three of the Gerudo Fortress and the ones that break when Link rolls into them)
CRATES = """Land_Gerudo_FortressLargeCrate_A_01 Land_Gerudo_FortressLargeCrate_A_02 Land_Gerudo_WoodenBox_A_01
Obj_BrokenBox_A_01 Obj_BrokenBox_A_01_Dream Obj_BrokenBox_A_02 Obj_BrokenBox_A_06"""
STRUCTURES = frozenset((BRIDGES + ' ' + BEAMS + ' ' + CRATES).split())
# (the wood of Kakariko's houses: on the N64 adult Link hookshots on to their roofs)
HOUSE = re.compile(r'^Land_Kakariko_House_A_\d+$')
# (every solid entry of these. Obj_CandleStick_A_03, the wooden stand, latches in the game as shipped)
TORCH = re.compile(r'^Obj_.*Candle(Stick|Stand)')
TREE = re.compile(r'Tree|Stump|Driftwood|Aerialroot')
NOT_TREE = re.compile(r'InsideTheDekuTree|^Land_Deku_|TreeRoot')


class FilesError(Exception):
    pass


def need(ok, what):
    if not ok:
        raise FilesError("the game's collision files are not laid out as this mod knows them (%s): "
                         "this may be a newer version of the game" % what)


def safe(rel):
    """A file's path below romfs as the game's files give it, checked: the same path is written below the mod's
    folder, and a dump is a file from somewhere, so no part of it may lead out of that folder."""
    need(all(p not in ('', '.', '..') and not set(p) & set('\\:') for p in rel.split('/')),
         'a file name: %r' % rel[:120])
    return rel


def rule(name):
    """(part, True: every solid entry / False: the wood entries only) for an object's name, or None."""
    if name in STRUCTURES or HOUSE.search(name):
        return TARGETS, False
    if TORCH.search(name):
        return TARGETS, True
    if TREE.search(name) and not NOT_TREE.search(name):
        return TREES, False
    return None


def wanted(material, flags, every):
    if flags & 1 << 44 or material in NOT_SOLID:        # StickHookshot is set already, or nothing to hit
        return False
    return every or material in WOOD


def sarc(data):
    """The files of a little-endian SARC archive, by name."""
    need(data[:4] == b'SARC' and data[6:8] == b'\xff\xfe', 'the dictionary archive')
    head, = struct.unpack_from('<H', data, 4)
    data_at, = struct.unpack_from('<I', data, 12)
    count, = struct.unpack_from('<H', data, head + 6)
    nodes = head + 12
    names = nodes + count * 16 + 8
    out = {}
    for i in range(count):
        _, attr, start, end = struct.unpack_from('<IIII', data, nodes + i * 16)
        at = names + (attr & 0xffff) * 4
        out[data[at:data.index(b'\0', at)].decode()] = data[data_at + start:data_at + end]
    return out


def frame(raw):
    """A zstd frame's header: (dictionary id, the header's first byte)."""
    need(raw[:4] == b'\x28\xb5\x2f\xfd', 'a packed file')
    first = raw[4]
    at = 5 + (0 if first & 0x20 else 1)
    size = [0, 1, 2, 4][first & 3]
    return int.from_bytes(raw[at:at + size], 'little'), first


class Zs:
    """The game's .zs files: zstd frames, most of them with one of the dictionaries of Pack/ZsDic.pack.zs.
    Every call makes its own zstd objects, so threads may share one Zs."""

    def __init__(self, romfs):
        import zstandard
        self.z = zstandard
        packed = zstandard.ZstdDecompressor().decompress(romfs.read('Pack/ZsDic.pack.zs'), max_output_size=1 << 28)
        self.blobs = {}
        for blob in sarc(packed).values():
            self.blobs[zstandard.ZstdCompressionDict(blob).dict_id()] = blob

    def _dict(self, dict_id):
        if not dict_id:
            return None
        need(dict_id in self.blobs, 'a dictionary the game does not ship')
        return self.z.ZstdCompressionDict(self.blobs[dict_id])

    def unpack(self, raw):
        return self.z.ZstdDecompressor(dict_data=self._dict(frame(raw)[0])).decompress(raw, max_output_size=1 << 30)

    def repack(self, data, stock_raw):
        """One frame as the game's own file: its dictionary, no checksum, the content's size in the header.
        None when the result does not open to the same content or its header has another form than the stock
        file's."""
        dict_id, first = frame(stock_raw)
        packer = self.z.ZstdCompressor(level=19, dict_data=self._dict(dict_id), write_checksum=False,
                                       write_content_size=True, write_dict_id=True)
        mod = packer.compress(data)
        if frame(mod) != (dict_id, first) or self.unpack(mod) != data:
            return None
        return mod


class Byml:
    """A little-endian BYML file (the placement lists), as Python values in .root."""

    def __init__(self, data):
        self.d = data
        keys, strings, root = struct.unpack_from('<III', data, 4)
        self.keys = self.table(keys) if keys else []
        self.strings = self.table(strings) if strings else []
        self.root = self.node(data[root], root) if root else None

    def u32(self, at):
        return struct.unpack_from('<I', self.d, at)[0]

    def table(self, at):
        out = []
        for i in range(self.u32(at) >> 8):
            start = at + self.u32(at + 4 + i * 4)
            out.append(self.d[start:self.d.index(b'\0', start)].decode('utf-8', 'replace'))
        return out

    def node(self, kind, value):
        d = self.d
        if kind == 0xa0:
            return self.strings[value]
        if kind == 0xd0:
            return bool(value)
        if kind == 0xd1:
            return value - (1 << 32) if value >> 31 else value
        if kind == 0xd2:
            return struct.unpack('<f', struct.pack('<I', value))[0]
        if kind == 0xd3:
            return value
        if kind in (0xd4, 0xd5, 0xd6):
            return struct.unpack_from({0xd4: '<q', 0xd5: '<Q', 0xd6: '<d'}[kind], d, value)[0]
        if kind == 0xc0:
            count = self.u32(value) >> 8
            kinds = d[value + 4:value + 4 + count]
            values = value + 4 + ((count + 3) & ~3)
            return [self.node(kinds[i], self.u32(values + i * 4)) for i in range(count)]
        if kind == 0xc1:
            out = {}
            for i in range(self.u32(value) >> 8):
                word = self.u32(value + 4 + i * 8)
                out[self.keys[word & 0xffffff]] = self.node(word >> 24, self.u32(value + 8 + i * 8))
            return out
        if kind in (0x20, 0x21):
            count = self.u32(value) >> 8
            key_size = 4 if kind == 0x20 else 8
            kinds = value + 4 + count * (key_size + 4)
            out = {}
            for i in range(count):
                at = value + 4 + i * (key_size + 4)
                out['#%x' % int.from_bytes(d[at:at + key_size], 'little')] = self.node(d[kinds + i],
                                                                                    self.u32(at + key_size))
            return out
        return None


def placements(romfs, zs):
    """{placement id: object name} of every object placed in a map (Banc/**: "Hash" and "Phive.Placement.ID")."""
    def actors(v):
        if isinstance(v, dict):
            if 'Gyaml' in v:
                yield v
            for x in v.values():
                yield from actors(x)
        elif isinstance(v, list):
            for x in v:
                yield from actors(x)

    ids = {}
    for rel in romfs.names('Banc/'):
        if not rel.endswith('.zs'):
            continue
        data = zs.unpack(romfs.read(rel))
        if data[:2] != b'YB':
            continue
        for a in actors(Byml(data).root):
            found = {a.get('Hash')}
            phive = a.get('Phive')
            placement = phive.get('Placement') if isinstance(phive, dict) else None
            if isinstance(placement, dict):
                found.add(placement.get('ID'))
            for i in found:
                if isinstance(i, int) and not isinstance(i, bool):
                    need(ids.setdefault(i, a['Gyaml']) == a['Gyaml'], 'one placement id for two objects')
    return ids


def shape_entries(shape):
    """Where a loose shape's material entries start, and how many there are."""
    table, after, size, tags = struct.unpack_from('<4I', shape, 0x10)
    table_size, rest = struct.unpack_from('<2I', shape, 0x20)
    need(shape[:5] == b'Phive' and size == len(shape) and after == table + table_size and after + rest == size
         and table_size % 16 == 0 and 0x30 + tags == table, 'a shape')
    return table, table_size // 16


def cell_marks(cell, ids):
    """The material entries to mark in one baked map square: (where the entries start, {part: set of entries}).

    The file starts with a list of offsets (at 0x10). [0] the placed objects, 0x20 bytes each: {u32 first shape,
    u32 last shape (first ffffffff: none), u64 placement id, ...}. [3] the shapes, 20 bytes each: {u32 its own
    number, ..., u32 first material entry, u32 count}. [4] the material entries, 16 bytes each, as in a loose
    shape, up to [5]."""
    need(cell[:5] == b'Phive', 'a map square')
    objects, lookup, _, shapes, table, after = struct.unpack_from('<6I', cell, 0x10)
    need(objects <= lookup <= shapes <= table <= after <= len(cell) and (after - table) % 16 == 0, 'a map square')
    n_shapes, n_entries = (table - shapes) // 20, (after - table) // 16
    marks = {TARGETS: set(), TREES: set()}
    for at in range(objects, lookup - 0x1f, 0x20):
        first, last, placement = struct.unpack_from('<IIQ', cell, at)
        if first == 0xffffffff:
            continue
        need(first <= last < n_shapes, 'a map square\'s objects')
        found = rule(ids.get(placement, ''))
        if not found:
            continue
        for shape in range(first, last + 1):
            number, = struct.unpack_from('<I', cell, shapes + 20 * shape)
            start, count = struct.unpack_from('<II', cell, shapes + 20 * shape + 12)
            need(number == shape and start + count <= n_entries, 'a map square\'s shapes')
            for entry in range(start, start + count):
                material, _, flags = struct.unpack_from('<IIQ', cell, table + 16 * entry)
                if wanted(material, flags, found[1]):
                    marks[found[0]].add(entry)
    return table, marks


def state(mods_dir):
    """What is in a copy's mods folder: None (no such mod), or its stamp ({'trees': bool, 'files': n, ...};
    {'broken': True} when the folder is there without a finished build)."""
    folder = os.path.join(mods_dir, NAME)
    if not os.path.isdir(folder):
        return None
    try:
        with open(os.path.join(folder, STAMP), encoding='utf-8') as f:
            stamp = json.load(f)
        return stamp if isinstance(stamp, dict) else dict(broken=True)
    except (OSError, ValueError):
        return dict(broken=True)


def marks_of(romfs, zs, parts, workers, log=print):
    """Read the game's files and say what to mark: ([(path below romfs, where its entries start, the entries to
    mark)], how many of them are loose shapes, how many map squares were read). Nothing is written."""
    jobs = []

    # (the loose shapes)
    for rel in romfs.names(SHAPE_DIR):
        name = rel[len(SHAPE_DIR):]
        found = rule(name[:-len(SHAPE_SUFFIX)]) if '/' not in name and name.endswith(SHAPE_SUFFIX) else None
        if not found or found[0] not in parts:
            continue
        stock = zs.unpack(romfs.read(safe(rel)))
        table, count = shape_entries(stock)
        entries = {i for i in range(count)
                   if wanted(*struct.unpack_from('<I4xQ', stock, table + 16 * i), found[1])}
        if entries:
            jobs.append((rel, table, entries))
    n_shapes = len(jobs)

    # (the baked map squares)
    ids = placements(romfs, zs)
    log('%d placed objects read' % len(ids))
    cells = [safe(rel) for rel in romfs.names(CELL_DIR) if rel.endswith('.bphsc.zs')]
    need(ids and cells, 'no maps')

    def scan(rel):
        return rel, cell_marks(zs.unpack(romfs.read(rel)), ids)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for rel, (table, marks) in pool.map(scan, cells):
            entries = set().union(*(marks[p] for p in parts))
            if entries:
                jobs.append((rel, table, entries))
    return jobs, n_shapes, len(cells)


def build(romfs, mods_dir, trees=False, log=print):
    """Build the mod from the game's files (a source.FolderRomfs or NupRomfs) into <mods_dir>/<NAME>.
    Returns the stamp it wrote."""
    try:
        import zstandard
    except ImportError:
        raise FilesError('building the hookshot targets needs the zstandard package: python -m pip install zstandard')
    parts = (TARGETS, TREES) if trees else (TARGETS,)
    workers = min(16, os.cpu_count() or 4)
    try:
        zs = Zs(romfs)
        jobs, n_shapes, n_cells = marks_of(romfs, zs, parts, workers, log)
    except (zstandard.ZstdError, struct.error, IndexError, KeyError, ValueError, OverflowError) as e:
        # (a file that is cut short or is not what its name says; need() names the ones that are merely new)
        raise FilesError("the game's files could not be read (%s: %s): a file may be damaged or only partly "
                         "copied, or this is a newer version of the game" % (type(e).__name__, e))
    log('%d map squares read; writing %d files ...' % (n_cells, len(jobs)))

    top = os.path.join(mods_dir, NAME, 'romfs')
    stamp_path = os.path.join(mods_dir, NAME, STAMP)
    if os.path.exists(stamp_path):
        os.remove(stamp_path)                   # until the new build is whole, the folder counts as unfinished

    def write(job):
        rel, table, entries = job
        raw = romfs.read(rel)
        data = bytearray(zs.unpack(raw))
        for entry in entries:
            data[table + 16 * entry + 13] |= 0x10      # bit 44 of the u64 at +8
        mod = zs.repack(bytes(data), raw)
        if mod is None:
            return rel, None
        path = os.path.join(top, *safe(rel).split('/'))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(mod)
        return rel, len(mod)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        done = list(pool.map(write, jobs))
    bad = [rel for rel, size in done if size is None]
    if bad:
        raise FilesError('%d files could not be packed the way the game packs them (the first: %s)'
                         % (len(bad), bad[0]))

    keep = {os.path.normcase(os.path.join(*rel.split('/'))) for rel, _ in done}
    for at, _, files in os.walk(top, topdown=False):
        for name in files:
            if os.path.normcase(os.path.relpath(os.path.join(at, name), top)) not in keep:
                os.remove(os.path.join(at, name))       # a file of an earlier build, not wanted now
        if at != top and not os.listdir(at):
            os.rmdir(at)
    stamp = dict(format=1, trees=bool(trees), files=len(done), shapes=n_shapes, squares=len(done) - n_shapes,
                 entries=sum(len(e) for _, _, e in jobs), bytes=sum(size for _, size in done))
    with open(stamp_path, 'w', encoding='utf-8') as f:
        json.dump(stamp, f, indent=1)
    log('%s: %d loose shapes, %d map squares, %d surfaces marked, %.0f MB'
        % (NAME, stamp['shapes'], stamp['squares'], stamp['entries'], stamp['bytes'] / 1e6))
    return stamp
