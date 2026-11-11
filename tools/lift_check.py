"""Ask the Hookshot recompiler's own translator about every instruction of the module.

The recompiler turns the module into C together with the game. An instruction it cannot translate becomes a
stop of the game when it is reached, and one it takes for the end of a block ends the build. This finds both
in a second, before a build of ten minutes.

    python tools/lift_check.py [the builder's tools/third_party/a64-kit/lift folder]
"""
import glob
import json
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lift_folder():
    if len(sys.argv) > 1:
        return sys.argv[1]
    found = sorted(glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'HookshotBuilder', 'versions', '*',
                                          'HookshotBuilder', 'tools', 'third_party', 'a64-kit', 'lift')))
    if not found:
        sys.exit('no Hookshot builder found: give the path of its a64-kit/lift folder')
    return found[-1]


def main():
    folder = lift_folder()
    sys.path.insert(0, folder)
    import a64_lift
    import a64emit

    man = json.load(open(os.path.join(ROOT, 'module', 'manifest.json')))
    image = open(os.path.join(ROOT, 'module', 'module.bin'), 'rb').read()
    start, size = man['text']
    base = 0x80020000 + man['nominal_base']         # where the recompiled game has the module
    items, kinds = [], {}
    for off in range(start, start + size, 4):
        if off == 4:                                # the offset of the module's header, not an instruction
            continue
        word = struct.unpack_from('<I', image, off)[0]
        kind = a64_lift.classify(word, base + off)[0]
        kinds[kind] = kinds.get(kind, 0) + 1
        if kind == 'op' and word:
            items.append((base + off, word))
    texts, flags = a64emit.translate(items)
    bad = 0
    for (pc, word), text, flag in zip(items, texts, flags):
        if flag & (a64emit.UNHANDLED | a64emit.TERMINATOR):
            bad += 1
            print('%s at module+0x%x: %08x' % ('not translated' if flag & a64emit.UNHANDLED else 'ends a block',
                                                pc - base, word))
    print('%d instructions (%s): %d the recompiler does not take' %
          (size // 4, ', '.join('%d %s' % (n, k) for k, n in sorted(kinds.items())), bad))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
