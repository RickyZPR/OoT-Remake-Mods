"""Where the game's own files are read from: a .nup dump, a folder with the game's exefs and romfs in it, or a
Hookshot game folder. Nothing is ever written to any of them."""
import os

from . import install, place
from .nup import Nup, NupError


class FolderRomfs:
    """The game's files as a folder. Paths are given with forward slashes, from the romfs down."""

    def __init__(self, root):
        self.root = root

    def read(self, rel):
        with open(os.path.join(self.root, *rel.split('/')), 'rb') as f:
            return f.read()

    def names(self, prefix):
        """Every file below a folder ('Banc/'), sorted."""
        top = os.path.join(self.root, *prefix.strip('/').split('/'))
        out = []
        for folder, _, files in os.walk(top):
            rel = os.path.relpath(folder, self.root).replace(os.sep, '/')
            out += ['%s/%s' % (rel, name) for name in files]
        return sorted(out)


class NupRomfs:
    """The game's files inside a .nup dump."""

    def __init__(self, nup):
        self.nup = nup

    def read(self, rel):
        try:
            return self.nup.read('romfs/' + rel)
        except KeyError:
            raise install.InstallError('the dump has no file %s' % rel)
        except NupError as e:
            raise install.InstallError(str(e))

    def names(self, prefix):
        return [p[len('romfs/'):] for p in self.nup.names('romfs/' + prefix.strip('/') + '/')]


class Source:
    """One place the game is read from. .romfs is its files (or None), .game() its code (or None)."""

    def __init__(self, text, romfs=None, game=None):
        self.text = text
        self.romfs = romfs
        self._game = game

    def game(self):
        return self._game() if self._game else None


def nup_game(nup):
    def read():
        try:
            return install.Game({name: nup.read('exefs/' + name) for name in place.ORDER
                                 if nup.find('exefs/' + name)})
        except NupError as e:
            raise install.InstallError(str(e))
    return read


def open_source(path):
    """A dump file or a folder of the game, as a Source. Raises install.InstallError if it is neither."""
    path = os.path.abspath(path)
    if os.path.isfile(path):
        try:
            nup = Nup(path)
        except (NupError, OSError) as e:
            raise install.InstallError(str(e))
        return Source(path, NupRomfs(nup), nup_game(nup))

    def romfs_of(folder):
        return FolderRomfs(folder) if os.path.isdir(os.path.join(folder, 'Phive')) else None

    if os.path.isfile(os.path.join(path, install.KEPT, 'main')):        # a Hookshot game folder
        return Source(path, romfs_of(os.path.join(path, 'romfs')), lambda: install.hookshot_read(path))
    if os.path.isfile(os.path.join(path, 'exefs', 'main')):             # an unpacked game: exefs and romfs
        return Source(path, romfs_of(os.path.join(path, 'romfs')),
                      lambda: install.read_exefs(os.path.join(path, 'exefs')))
    if os.path.isfile(os.path.join(path, 'main')):                      # the exefs folder itself
        return Source(path, romfs_of(os.path.join(os.path.dirname(path), 'romfs')),
                      lambda: install.read_exefs(path))
    if romfs_of(path):                                                  # the romfs folder itself
        return Source(path, romfs_of(path))
    if romfs_of(os.path.join(path, 'romfs')):
        return Source(path, romfs_of(os.path.join(path, 'romfs')))
    raise install.InstallError('%s is not a .nup dump, a folder with the game\'s exefs and romfs, or a Hookshot '
                               'game folder' % path)
