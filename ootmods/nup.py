"""Read a .nup game dump: the files of the game and of its update, by name. Nothing is ever written to it.

The layout is as read by nup_reader.py of REXCRAFT88's Manual Shield installer (GPL-3.0),
https://github.com/REXCRAFT88/OOT-Mods-by-rexcraft88, which this follows.
"""
import hashlib
import struct


class NupError(Exception):
    pass


class Nup:
    def __init__(self, path):
        self.path = path
        with open(path, 'rb') as f:
            head = f.read(128)
            if head[:4] != b'NUP\x01':
                raise NupError('%s is not a .nup game dump' % path)
            toc_at, toc_size = struct.unpack_from('<QQ', head, 8)
            if toc_size > 256 << 20:
                raise NupError('%s: its table of contents is too large' % path)
            f.seek(toc_at)
            toc = f.read(toc_size)
        if hashlib.sha256(toc).digest() != head[24:56]:
            raise NupError('%s is damaged (its table of contents does not match its checksum)' % path)
        magic, n_packages, n_dirs, n_files, names_at, _, _ = struct.unpack_from('<IIQQQQQ', toc)
        if magic != 0x01434f54:
            raise NupError('%s: unknown table of contents' % path)

        def name(at, size):
            return toc[names_at + at:names_at + at + size].decode('utf-8')

        pos = 48
        self.packages = []          # the game (kind 0) and its updates (kind 1)
        for i in range(n_packages):
            title, root, _, _, version = struct.unpack_from('<QIIII', toc, pos)
            self.packages.append(dict(index=i, title_id=title, root=root, version=version, kind=toc[pos + 24]))
            pos += 64
        dirs = []
        for _ in range(n_dirs):
            at, size, first, count = struct.unpack_from('<IIII', toc, pos)
            dirs.append((name(at, size), first, count))
            pos += 24
        files = []
        for _ in range(n_files):
            at, size, length, offset, stored = struct.unpack_from('<IIQQQ', toc, pos)
            files.append(dict(size=length, offset=offset, stored=stored, codec=toc[pos + 64], name=name(at, size)))
            pos += 80
        children = struct.unpack_from('<%dI' % ((names_at - pos) // 4), toc, pos)

        self.files = {}             # {(package, 'romfs/...'): entry}
        for p in self.packages:
            todo = [(p['root'], '', 0)]
            while todo:
                d, where, depth = todo.pop()
                if depth > 128:
                    raise NupError('%s: folders nested too deep' % path)
                _, first, count = dirs[d]
                for ch in children[first:first + count]:
                    if ch < n_dirs:
                        todo.append((ch, where + dirs[ch][0] + '/', depth + 1))
                    else:
                        entry = files[ch - n_dirs]
                        self.files[(p['index'], where + entry['name'])] = entry

    def order(self):
        """The packages, the newest update first and the game itself last: a file is taken from the first that
        has it."""
        return [p['index'] for p in sorted(self.packages, key=lambda p: (p['kind'], p['version']), reverse=True)]

    def find(self, path):
        path = path.replace('\\', '/').lstrip('/')
        for i in self.order():
            entry = self.files.get((i, path))
            if entry:
                return entry
        return None

    def read(self, path, package=None):
        entry = self.find(path) if package is None else self.files.get((package, path))
        if not entry:
            raise KeyError(path)
        with open(self.path, 'rb') as f:
            f.seek(entry['offset'])
            data = f.read(entry['stored'])
        if entry['codec']:
            try:
                import zstandard
            except ImportError:
                raise NupError('reading this game dump needs the zstandard package: python -m pip install zstandard '
                               'zbic')
            try:
                data = zstandard.ZstdDecompressor().decompress(data, max_output_size=entry['size'])
            except zstandard.ZstdError as e:
                raise NupError('%s: %s cannot be opened (%s)' % (self.path, path, e))
        if len(data) != entry['size']:
            raise NupError('%s: %s is cut short' % (self.path, path))
        return data

    def names(self, prefix):
        """Every file below a folder ('romfs/Banc/'), from all packages, each once."""
        prefix = prefix.replace('\\', '/').lstrip('/')
        return sorted({path for _, path in self.files if path.startswith(prefix)})
