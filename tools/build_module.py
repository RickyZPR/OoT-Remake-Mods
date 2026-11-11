#!/usr/bin/env python3
"""Build the mod module from src/ into module/module.bin and module/manifest.json.

Players do not need this: the built module is in the repository. It needs clang and ld.lld (LLVM 17 or newer),
looked for in $OOTMODS_LLVM, in the Hookshot Builder's own toolchain, then on PATH.

  python tools/build_module.py                 build
  python tools/build_module.py --main <file>   also remake the patterns that find the game's code in other
                                               versions, from that copy of the game's main module
"""
import argparse
import glob
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from ootmods import options, place  # noqa: E402

BUILD =os.path.join(ROOT, 'build')
OUT = os.path.join(ROOT, 'module')

CFLAGS = ['--target=aarch64-none-elf', '-Oz', '-ffreestanding', '-fno-builtin', '-ffunction-sections',
          '-fdata-sections', '-fno-stack-protector', '-fno-jump-tables', '-fno-asynchronous-unwind-tables',
          '-fno-unwind-tables', '-fno-pic', '-mcmodel=small', '-Wall', '-Wextra', '-Werror',
          # The Hookshot recompiler lifts this module too. It needs every function to start at its lowest
          # address and to be left only by returns and calls: no tail calls, no outlined pieces.
          '-fno-optimize-sibling-calls', '-mno-outline',
          # ...and no vector code where the source has none.
          '-fno-vectorize', '-fno-slp-vectorize', '-mno-implicit-float', '-Wno-unused-command-line-argument']

# Relocations that do not depend on where the module is loaded, as long as they point inside the module.
R_INTERNAL = {261, 273, 274, 275, 276, 277, 278, 279, 280, 282, 283, 284, 285, 286, 299}
R_ABS = {257, 258}
R_JUMP26, R_CALL26 = 282, 283


def tool(name):
    places = [os.environ.get('OOTMODS_LLVM', '')]
    places += sorted(glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'HookshotBuilder', 'versions', '*',
                                            'HookshotBuilder', 'tools', 'llvm-mingw', 'bin')), reverse=True)
    for d in places:
        for ext in ('.exe', ''):
            p = os.path.join(d, name + ext)
            if d and os.path.isfile(p):
                return p
    p = shutil.which(name)
    if not p:
        sys.exit('%s not found: set OOTMODS_LLVM to the folder that holds clang and ld.lld' % name)
    return p


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        sys.exit('FAILED: %s\n%s%s' % (' '.join(cmd), r.stdout, r.stderr))
    if r.stderr.strip():
        print(r.stderr.strip())


def load_table():
    scope = {}
    with open(os.path.join(ROOT, 'game', 'table.py'), encoding='utf-8') as f:
        exec(compile(f.read(), 'game/table.py', 'exec'), scope)
    return scope


def code_address(t, name):
    spec = t['CODE'][name]
    if spec[0] == 'at':
        return spec[1]
    if spec[1] not in t['HOOKS']:
        sys.exit('%s: no hook %s' % (name, spec[1]))
    site, word = t['HOOKS'][spec[1]][:2]
    addr = place.code_address(spec, site, word)
    if addr is None:
        sys.exit('%s: the instruction at hook %s does not branch' % (name, spec[1]))
    return addr


def write_header(path, t, base):
    """The numbers the C and the assembly share: places in the settings block and in the game's table."""
    data, feats = list(t['DATA']), list(t['FEATURES'])
    with open(path, 'w') as f:
        f.write('// made by tools/build_module.py from game/table.py and ootmods/options.py\n')
        for i, n in enumerate(data):
            f.write('#define D_%s %d\n' % (n, i))
        f.write('#define D_COUNT %d\n' % len(data))
        for i, n in enumerate(feats):
            f.write('#define F_%s %d\n' % (n, i))
        f.write('#define F_COUNT %d\n' % len(feats))
        for i, o in enumerate(options.OPTIONS):
            f.write('#define O_%s %d\n' % (o['key'], i))
            if o['kind'] == 'button':
                f.write('#define BUTTONS_%s %s\n'
                        % (o['key'], ', '.join('0x%x' % options.button_mask(b) for b in o['buttons'])))
        f.write('#define O_COUNT %d\n' % len(options.OPTIONS))
        f.write('#define OPTIONS_START %s\n' % ', '.join(str(o['start']) for o in options.OPTIONS))
        f.write('#define NOMINAL_DELTA 0x%XLL\n' % base)
        f.write('#define NOMINAL_DATA %s\n' % ', '.join('0x%X' % t['DATA'][n][0] for n in data))


class Elf:
    def __init__(self, path):
        d = self.d = open(path, 'rb').read()
        shoff = struct.unpack_from('<Q', d, 0x28)[0]
        shentsize, shnum, shstrndx = struct.unpack_from('<HHH', d, 0x3a)
        self.sections = []
        for i in range(shnum):
            name, typ, flags, addr, off, size, link, info, align, entsize = struct.unpack_from(
                '<IIQQQQIIQQ', d, shoff + i * shentsize)
            self.sections.append(dict(name=name, type=typ, flags=flags, addr=addr, off=off, size=size, link=link,
                                      info=info))
        strs = self.sections[shstrndx]
        for s in self.sections:
            s['name'] = self._str(strs, s['name'])
        self.symbols = []
        for s in self.sections:
            if s['type'] == 2:      # SHT_SYMTAB
                names = self.sections[s['link']]
                for o in range(s['off'], s['off'] + s['size'], 24):
                    name, info, other, shndx, value, size = struct.unpack_from('<IBBHQQ', d, o)
                    self.symbols.append(dict(name=self._str(names, name), shndx=shndx, value=value, type=info & 15))
        self.sym = {s['name']: s['value'] for s in self.symbols if s['name']}

    def _str(self, sec, off):
        o = sec['off'] + off
        return self.d[o:self.d.index(b'\0', o)].decode()

    def relocs(self):
        for s in self.sections:
            if s['type'] == 4:      # SHT_RELA
                for o in range(s['off'], s['off'] + s['size'], 24):
                    r_off, r_info, addend = struct.unpack_from('<QQq', self.d, o)
                    yield r_off, r_info & 0xffffffff, self.symbols[r_info >> 32], addend


def build():
    ap = argparse.ArgumentParser()
    ap.add_argument('--main', help="the game's main module, to remake the patterns")
    args = ap.parse_args()

    t = load_table()
    base = t['MODULE_BASE']
    os.makedirs(BUILD, exist_ok=True)
    os.makedirs(OUT, exist_ok=True)

    code = {name: code_address(t, name) for name in t['CODE']}
    with open(os.path.join(BUILD, 'game_syms.ld'), 'w') as f:
        f.write('/* made by tools/build_module.py from game/table.py */\n')
        f.write('MODULE_BASE = 0x%X;\n' % base)
        f.write('MODULE_SIZE = 0x%X;\n' % t['MODULE_SIZE'])
        for name, addr in code.items():
            f.write('g_%s = 0x%X;\n' % (name, addr))
    data = list(t['DATA'])
    feats = list(t['FEATURES'])
    for what, feature in ([(n, h[4]) for n, h in t['HOOKS'].items()] + [(n, d[1]) for n, d in t['DATA'].items()]
                          + [(n, c[2]) for n, c in t['CODE'].items() if c[0] == 'at']
                          + [(o['key'], o['feature']) for o in options.OPTIONS] + list(t['NEEDS'].items())):
        if feature not in feats:
            sys.exit('%s: no feature %s' % (what, feature))
    write_header(os.path.join(BUILD, 'game_table.h'), t, base)

    clang, lld = tool('clang'), tool('ld.lld')
    objs = []
    for src in sorted(glob.glob(os.path.join(ROOT, 'src', '*.c')) + glob.glob(os.path.join(ROOT, 'src', '*.S'))):
        obj = os.path.join(BUILD, os.path.basename(src) + '.o')
        run([clang] + CFLAGS + ['-I', BUILD, '-I', os.path.join(ROOT, 'src'), '-c', src, '-o', obj])
        objs.append(obj)
    elf_path = os.path.join(BUILD, 'module.elf')
    run([lld, '-o', elf_path, '--emit-relocs', '--gc-sections', '-z', 'max-page-size=4096', '--no-undefined',
         '-T', os.path.join(BUILD, 'game_syms.ld'), '-T', os.path.join(ROOT, 'src', 'module.ld'),
         '-Map', os.path.join(BUILD, 'module.map')] + objs)

    elf = Elf(elf_path)
    sym = elf.sym
    end = sym['__bss_end']
    image = bytearray(sym['__data_end'] - base)
    for s in elf.sections:
        if s['flags'] & 2 and s['type'] == 1 and s['size']:        # allocated, has bytes
            image[s['addr'] - base:s['addr'] - base + s['size']] = elf.d[s['off']:s['off'] + s['size']]

    game = {'g_' + n for n in code}
    fixups, bad = [], []
    for r_off, r_type, s, addend in elf.relocs():
        name = s['name']
        inside = base <= s['value'] <= end and s['shndx'] != 0xfff1
        if name in game:
            if r_type not in (R_JUMP26, R_CALL26):
                bad.append('%s: relocation %d to game symbol at 0x%X (only b and bl can reach the game)'
                           % (name, r_type, r_off))
            fixups.append([r_off - base, name[2:], addend, 'bl' if r_type == R_CALL26 else 'b'])
        elif name.startswith('__off_') or (s['shndx'] == 0xfff1 and not inside and r_type in R_ABS):
            if name.startswith('__off_'):
                continue
            bad.append('%s: absolute relocation at 0x%X' % (name, r_off))
        elif inside or (s['type'] == 3 and base <= s['value'] <= end):
            if r_type not in R_INTERNAL:
                bad.append('%s: relocation %d at 0x%X ties the module to one address (a pointer in data?)'
                           % (name or 'section', r_type, r_off))
        else:
            bad.append('%s: relocation %d at 0x%X to something outside the module' % (name, r_type, r_off))
    if bad:
        sys.exit('The module cannot be moved:\n  ' + '\n  '.join(bad))

    text = (0, sym['__text_end'] - base)
    ro_start = [s for s in elf.sections if s['name'] == '.rodata'][0]['addr'] - base
    rodata = (ro_start, sym['__rodata_end'] - base - ro_start)
    da_start = [s for s in elf.sections if s['name'] == '.data'][0]['addr'] - base
    dat = (da_start, sym['__data_end'] - base - da_start)
    hooks = {}
    for name, (site, word, op, entry, feature) in t['HOOKS'].items():
        if entry not in sym:
            sys.exit('hook %s: no %s in the module' % (name, entry))
        if (op == 'bl') != (word >> 26 == 0x25):
            sys.exit('hook %s: a call replaces a call, and nothing else' % name)
        hooks[name] = dict(site=site, orig='%08x' % word, op=op, entry=sym[entry] - base, feature=feature)

    man_path = os.path.join(OUT, 'manifest.json')
    old = {}
    if os.path.exists(man_path):
        with open(man_path, encoding='utf-8') as f:
            old = json.load(f)
    man = dict(
        format=1,
        game_build_id=t['BUILD_ID'],
        nominal_base=base,
        text=text, rodata=rodata, data=dat, bss=end - sym['__data_end'],
        settings=sym['g_set'] - base, table=sym['g_tab'] - base,
        dynstr=[sym['__dynstr'] - base - ro_start, 1], dynsym=[sym['__dynsym'] - base - ro_start, 0x18],
        stub=sym['mods_stub'] - base,
        features=feats,
        needs=t['NEEDS'],
        starts=list(t.get('STARTS', [])),
        hooks=hooks,
        code={n: list(v) for n, v in t['CODE'].items()},
        data_names=data,
        data_at={n: t['DATA'][n][0] for n in data},
        data_feature={n: t['DATA'][n][1] for n in data},
        fixups=fixups,
        patterns=old.get('patterns', {}),
    )
    if args.main:
        from ootmods import nso, patterns
        with open(args.main, 'rb') as f:
            main = nso.Nso(f.read())
        if main.build_id != t['BUILD_ID']:
            sys.exit('--main: that is build %s of the game, and game/table.py is for %s' % (main.build_id, t['BUILD_ID']))
        man['patterns'] = patterns.make(man, main)
    man['module_sha256'] = hashlib.sha256(image).hexdigest()
    with open(os.path.join(OUT, 'module.bin'), 'wb') as f:
        f.write(image)
    with open(man_path, 'w', encoding='utf-8', newline='\n') as f:      # the same file on every system
        json.dump(man, f, indent=1)
    print('module: text 0x%X, rodata 0x%X, data 0x%X, bss 0x%X; %d fixups, %d hooks'
          % (text[1], rodata[1], dat[1], man['bss'], len(fixups), len(hooks)))


if __name__ == '__main__':
    build()
