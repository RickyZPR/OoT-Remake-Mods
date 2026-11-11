"""The copies of the game on a PC: an emulator's mod folder for the game, or a Hookshot game folder. Finding
them, saying how the mod stands in each, putting it in, repairing and removing it, building a Hookshot folder
again, and turning a copy's other mods on and off."""
import glob
import mmap
import os
import re
import shutil
import subprocess

from . import hookshot_files, install, live, nso, options, place, settings
from . import source as sources

TITLE = '0400486024DEC000'
OFF_DIR = 'load-disabled'           # beside an emulator's "load" folder: the mods that are turned off
APP = 'OoT Mods'
OURS = (install.MOD_NAME, hookshot_files.NAME)
TAIL = 15                           # lines of the builder's output kept for an error message

EMULATOR_TEXT = {
    'absent': ('Not installed', 'Install'),
    'ok': ('Installed', ''),
    'old': ('An older version of the mod is installed', 'Update'),
    'broken': ('Files of the mod are missing', 'Repair'),
    'refit': ('The game was updated after the mod was installed: the mod must be fitted to it', 'Repair'),
}
HOOKSHOT_TEXT = {
    'nofolder': ('Not a game folder that Hookshot Builder can build again (it keeps no game code)', ''),
    'absent': ('Not installed', 'Install'),
    'dropped': ('The game was built again from the dump, and the mod went with the old code', 'Repair'),
    'broken': ('Only a part of the mod is there', 'Repair'),
    'old': ('An older version of the mod is installed', 'Update'),
    'unbuilt': ('The mod is in the code; the game has not been built with it yet', 'Build'),
    'ok': ('Installed', ''),
}


class OtherBuilder(install.InstallError):
    """The Hookshot Builder on this PC is another version than the one a game folder was built with. Building
    with it also brings the game to that version, and that is for the player to say."""


class NeedsGame(install.InstallError):
    """The job needs the game's own files (the player's dump), and none were given."""


class BuildElsewhere(install.InstallError):
    """A game folder cannot be built again from here, and Hookshot Builder itself can do it (.how: the way).
    What an install or a remove changes in the code the folder keeps is done all the same; that build takes
    it up, because the builder keeps the folder's code as long as it is given the same game files."""

    def __init__(self, why, how):
        install.InstallError.__init__(self, '%s: %s' % (why, how))
        self.why, self.how = why, how


def end_tree(proc):
    """End a program and the ones it started."""
    try:
        subprocess.call(['taskkill', '/F', '/T', '/PID', str(proc.pid)], stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except OSError:
        pass
    try:
        proc.kill()
    except OSError:
        pass


def config_dir():
    if os.name == 'nt':
        base = os.environ.get('APPDATA') or os.path.expanduser('~')
    else:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
    return os.path.join(base, APP)


def subdirs(folder):
    try:
        return sorted(n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n)))
    except OSError:
        return []


def first_line(path):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.readline().strip()
    except OSError:
        return ''


def same_id(a, b):
    """True when two build ids name the same build of the game (an emulator's log leaves the zeros at the end
    of one away)."""
    a, b = a.upper().rstrip('0'), b.upper().rstrip('0')
    return bool(a) and a == b


def plain_name(name):
    if not name or name in ('.', '..') or any(c in name for c in '/\\:*?"<>|'):
        raise install.InstallError('"%s" is not the name of a mod folder' % name)
    return name


# ---- the Hookshot Builder on this PC ----

def builder_home():
    base = os.environ.get('LOCALAPPDATA') if os.name == 'nt' else None
    return os.path.join(base, 'HookshotBuilder') if base else None


def usable(tools):
    return (os.path.isfile(os.path.join(tools, 'nx2', 'make_game.py'))
            and os.path.isfile(os.path.join(tools, 'python', 'python.exe')))


def builder_tools():
    """The tools folders of the Hookshot Builders on this PC, the current one first."""
    home = builder_home()
    if not home:
        return []
    versions = os.path.join(home, 'versions')
    current = first_line(os.path.join(versions, 'current.txt'))
    names = sorted(subdirs(versions), reverse=True)
    names.sort(key=lambda n: n != current)
    found = [os.path.join(versions, n, 'HookshotBuilder', 'tools') for n in names]
    return [t for t in found if usable(t)]


def helper_python():
    """A Python that has the packages this one may lack (zstandard): the one a Hookshot Builder brings."""
    for tools in builder_tools():
        return os.path.join(tools, 'python', 'python.exe')
    return None


# A Hookshot Builder brings a reader for the packed code of a game dump: nso.py uses it when the zbic package
# is not installed.
nso.ZBIC_DLLS[:] = [os.path.join(t, 'third_party', 'zbic', 'zbic.dll') for t in builder_tools()]


def kept_build(folder):
    """The build of the game whose code a Hookshot game folder keeps ('' when it keeps none)."""
    try:
        with open(os.path.join(folder, install.KEPT, 'main'), 'rb') as f:
            head = f.read(0x60)
    except OSError:
        return ''
    return head[0x40:0x54].hex().upper() if len(head) == 0x60 and head[:4] == b'NSO0' else ''


# ---- what the player set ----

class Config:
    """The player's own settings, in one file apart from the games: the switches, the copies of the game they
    added by hand, where the game's files were read from last."""

    def __init__(self, path=None):
        self.path = path or os.path.join(config_dir(), 'config.json')
        data = install.read_json(self.path) or {}
        copies = data.get('copies') if isinstance(data.get('copies'), list) else []
        self.copies = [dict(kind=c['kind'], path=c['path']) for c in copies
                       if isinstance(c, dict) and c.get('kind') in ('emulator', 'hookshot')
                       and isinstance(c.get('path'), str) and c['path']]
        self.options = data.get('options') if isinstance(data.get('options'), dict) else {}
        self.source = data.get('source') if isinstance(data.get('source'), str) else ''
        programs = data.get('programs') if isinstance(data.get('programs'), list) else []
        self.programs = [p for p in programs if isinstance(p, str) and p]

    def values(self):
        """The switches as the player set them; None when they never set any."""
        if not self.options:
            return None
        out = settings.defaults()
        for i, o in enumerate(options.OPTIONS):
            v = self.options.get(o['key'])
            if type(v) is int and settings.fits(i, v):
                out[i] = v
        return out

    def set_values(self, values):
        self.options = {o['key']: v for o, v in zip(options.OPTIONS, settings.clean(values))}

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        install.write_json(self.path, dict(format=1, options=self.options, copies=self.copies, source=self.source,
                                           programs=self.programs))


# ---- an emulator ----

EXEFS_LINE = re.compile(rb'Patching ExeFS for title_id=([0-9A-Fa-f]{16})')
MAIN_LINE = re.compile(rb'build_id=([0-9A-Fa-f]{8,64}), name=main\b|name=main, build_id=([0-9A-Fa-f]{8,64})')


_logs = {}                          # log file -> (its time, its size, the build it names)


def logged_build(path):
    """The build of the game an emulator ran last, as its log says it ('' when it does not say)."""
    try:
        st = os.stat(path)
    except OSError:
        return ''
    had = _logs.get(path)
    if not had or had[:2] != (st.st_mtime_ns, st.st_size):
        _logs[path] = had = (st.st_mtime_ns, st.st_size, read_log(path))
    return had[2]


def read_log(path):
    try:
        with open(path, 'rb') as f:
            with mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as log:
                starts = [(m.start(), m.group(1).decode().upper()) for m in EXEFS_LINE.finditer(log)]
                for i in range(len(starts) - 1, -1, -1):
                    if starts[i][1] != TITLE:
                        continue
                    end = starts[i + 1][0] if i + 1 < len(starts) else len(log)
                    m = MAIN_LINE.search(log, starts[i][0], end)
                    return (m.group(1) or m.group(2)).decode().upper() if m else ''
    except (OSError, ValueError):               # no log, or an empty one
        pass
    return ''


def changed(path):
    """When a file was last written; 0 for one that is gone (an emulator renames its log as it starts)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


class Emulator:
    """The game in an emulator of the yuzu family (Fritchii, Eden ...): its folder of mods for the game."""
    kind = 'emulator'

    def __init__(self, path, by_hand=False):
        self.path = os.path.abspath(path)                   # <the emulator's data>/load/<the game's id>
        self.data = os.path.dirname(os.path.dirname(self.path))
        name = os.path.basename(self.data)
        if name.lower() == 'user':                          # a portable emulator keeps its data beside its exe
            name = os.path.basename(os.path.dirname(self.data))
        self.name = name[:1].upper() + name[1:]
        self.mods_dir = self.path
        self.by_hand = by_hand

    def title(self):
        return self.name

    def module(self):
        return os.path.join(self.path, install.MOD_NAME, 'exefs', place.MODULE_NAME)

    def game_build(self):
        """The build of the game this emulator ran last ('' when its log does not say)."""
        logs = [p for p in glob.glob(os.path.join(glob.escape(self.data), 'log', '*log*.txt')) if os.path.isfile(p)]
        logs.sort(key=changed, reverse=True)
        for path in logs:
            build = logged_build(path)
            if build:
                return build
        return ''

    def state(self):
        """(state, record): the states of install.emulator_state, and 'refit' when the emulator has since run
        another version of the game than the one the mod was fitted to."""
        state, rec = install.emulator_state(self.path)
        if state in ('ok', 'old') and rec and isinstance(rec.get('build_id'), str):
            ran = self.game_build()         # (rec['ran']: what the log said when the mod was installed)
            if ran and not same_id(ran, rec['build_id']) and not same_id(ran, str(rec.get('ran') or '')):
                return 'refit', rec
        return state, rec

    def values(self):
        """The switches the game starts with here; None when the mod is not here."""
        got = settings.read_file(self.module())
        if not got or not got[1]['count']:
            return None
        return settings.clean(got[1]['opt'], got[1]['count'])

    def save(self, values):
        if self.values() is None:
            return False
        try:
            return install.emulator_save(self.path, values)
        except OSError:
            return False

    def install(self, values=None, game=None, log=print, copies=()):
        """Put the mod in, or replace the one that is there. `game`: the game's code to fit it to; without it
        the mod is installed for the version it was made for, or fitted to the code a Hookshot game folder
        among `copies` keeps when the emulator runs another version."""
        ran = self.game_build()
        known = nominal()[1]
        if game is None and ran and not same_id(ran, known):
            game = kept_game(ran, copies)
            if game is None:
                raise NeedsGame(
                    'the game in %s is another version (build %s) than the one this mod was made for (build %s). '
                    'With the game\'s own files, your dump of that version, the mod can be fitted to it'
                    % (self.name, ran[:16], known[:16]))
            log('Fitting the mod to the game code that a Hookshot game folder keeps (build %s).' % ran[:16])
        fit = install.Fit(game)
        if ran and not same_id(ran, fit.build_id):
            log('Note: %s last ran the game as build %s, and these game files are build %s. If the mod does not '
                'show in the game, fit it to the files of the version you play.' % (self.name, ran[:16],
                                                                                   fit.build_id[:16]))
        os.makedirs(self.path, exist_ok=True)
        install.write_emulator(fit, self.path, values, ran)
        report(fit, log)
        if not ran:
            log('Which version of the game %s has could not be checked (it has not run the game yet, or keeps '
                'no log).' % self.name)
        for mod, why in install.conflicts(self.path, fit.sites(), fit.build_id):
            log('Note: turn off the mod "%s": %s.' % (mod, why))
        return fit

    def remove(self):
        install.remove_emulator(self.path)

    def conflicts(self):
        """Other mods here that get in this one's way: {name: why}."""
        rec = install.emulator_state(self.path)[1] or {}
        sites, build = nominal()
        if isinstance(rec.get('sites'), list) and isinstance(rec.get('build_id'), str):
            sites, build = rec['sites'], rec['build_id']
        out = {}
        for mod, why in install.conflicts(self.path, sites, build):
            out.setdefault(mod, why)
        return out

    def off_dir(self):
        return os.path.join(self.data, OFF_DIR, TITLE)

    def mods(self):
        """The other mods of the game here: [(name, is it on)]."""
        out = {n: False for n in subdirs(self.off_dir())}
        out.update((n, True) for n in subdirs(self.path))
        return sorted(((n, on) for n, on in out.items() if n not in OURS), key=lambda m: m[0].lower())

    def switch(self, name, on):
        """Turn another mod on or off: its folder moves between the emulator's mod folder and one beside it."""
        plain_name(name)
        here, away = os.path.join(self.path, name), os.path.join(self.off_dir(), name)
        src, dst = (away, here) if on else (here, away)
        if not os.path.isdir(src):
            if os.path.isdir(dst):
                return
            raise install.InstallError('%s has no mod "%s"' % (self.name, name))
        if os.path.exists(dst):
            raise install.InstallError('the mod "%s" is there twice, on and off: remove one of %s and %s'
                                       % (name, here, away))
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            # A rename and nothing else: it moves the whole folder or leaves it as it is. (shutil.move would
            # answer a refused rename, which is what a file held open by the running game gives, with a copy
            # and a delete that stops half way.)
            os.rename(src, dst)
        except OSError as e:
            raise install.InstallError('the mod "%s" cannot be moved (is the game running?): %s' % (name, e))

    def romfs(self):
        return None

    def running(self):
        return []


# ---- a Hookshot game folder ----

class Hookshot:
    """The game as Hookshot Builder made it for the PC: a folder with the game, and the code it was built from."""
    kind = 'hookshot'

    def __init__(self, path, by_hand=False):
        self.path = os.path.abspath(path)
        self.name = os.path.basename(self.path) or self.path
        self.mods_dir = os.path.join(self.path, 'mods')
        self.by_hand = by_hand

    def title(self):
        return 'Hookshot: ' + self.name

    def module(self):
        return os.path.join(self.path, install.KEPT, place.MODULE_NAME)

    def state(self):
        return install.hookshot_state(self.path)

    def values(self):
        got = settings.read_file(self.module())
        if not got or not got[1]['count']:
            return None
        return settings.clean(got[1]['opt'], got[1]['count'])

    def save(self, values):
        """Set the switches the game starts with: in the code it is built from, and in the built game."""
        kept, image = install.hookshot_save(self.path, values)
        return kept or image

    def running(self):
        return live.hookshot_running(self.path)

    def romfs(self):
        folder = os.path.join(self.path, 'romfs')
        return sources.FolderRomfs(folder) if os.path.isdir(os.path.join(folder, 'Phive')) else None

    def version(self):
        """What the folder says about the builder that made it: {'version': ..., 'builder': ...}."""
        out = {}
        try:
            with open(os.path.join(self.path, 'hookshot_version.txt'), encoding='utf-8', errors='replace') as f:
                for line in f:
                    key, sep, value = line.strip().partition('=')
                    if sep:
                        out[key.strip()] = value.strip()
        except OSError:
            pass
        return out

    def tools(self):
        """The builder that can build this folder: (its tools folder, its version, True when that is the
        version the folder was built with)."""
        ver = self.version()
        want = ver.get('version', '')
        tried = []
        if ver.get('builder'):
            tried.append(os.path.join(os.path.dirname(ver['builder']), 'tools'))
        home = builder_home()
        if home and want:
            tried.append(os.path.join(home, 'versions', want, 'HookshotBuilder', 'tools'))
        for tools in tried + builder_tools():
            if usable(tools):
                have = first_line(os.path.join(tools, 'version.txt'))
                return tools, have, bool(have) and have == want
        raise BuildElsewhere('no Hookshot Builder was found on this PC to build %s with' % self.path,
                             'build the game again with Hookshot Builder itself, from the same game files and '
                             'into the same folder')

    def build_plan(self, other_builder=False):
        """What building this folder again runs: (command, the folder to run it in, its environment, the file
        the builder writes its output to). Raises when the folder cannot be built, or should not be."""
        if self.running():
            raise install.InstallError('the game in %s is running: close it first' % self.path)
        if not os.path.isfile(os.path.join(self.path, install.KEPT, 'main')) \
                or not os.path.isdir(os.path.join(self.path, 'romfs')):
            raise install.InstallError('%s does not keep what a build needs (the game\'s code and files): build '
                                       'the game from your dump with Hookshot Builder first' % self.path)
        tools, have, same = self.tools()
        ver = self.version()
        if not same and not other_builder:
            raise OtherBuilder('this game was built with Hookshot Builder %s, and the builder on this PC is %s: '
                               'building the game again also updates it to %s'
                               % (ver.get('version') or 'of an unknown version', have or 'another version',
                                  have or 'that version'))
        env = dict(os.environ, HOOKSHOT_NO_UPDATE_CHECK='1')
        # The game's own update offer starts the builder named in hookshot_version.txt, and a build writes that
        # line only from these two variables.
        exe, args = ver.get('builder', ''), ver.get('builder_args', '')
        if exe and not os.path.isfile(exe):                 # that builder is gone: the one that builds it now
            exe, args = os.path.join(os.path.dirname(tools), 'HookshotBuilder.exe'), ''
            if not os.path.isfile(exe):
                exe = ''
        for key, value in (('HOOKSHOT_BUILDER_EXE', exe), ('HOOKSHOT_BUILDER_ARGS', args)):
            if value:
                env[key] = value
            else:
                env.pop(key, None)
        # A game built with NVIDIA DLSS keeps it only when the build is given NVIDIA's files again.
        if os.path.isfile(os.path.join(self.path, 'ngx', 'nvngx_dlss.dll')) and not env.get('HOOKSHOT_NGX_SDK'):
            sdk = dlss_sdk(tools)
            if not sdk:
                raise BuildElsewhere(
                    'this game was built with NVIDIA DLSS, and a build from here would leave DLSS out',
                    'build the game again in Hookshot Builder itself, from the same game files and into the same '
                    'folder, with DLSS ticked')
            env['HOOKSHOT_NGX_SDK'] = sdk
        os.makedirs(config_dir(), exist_ok=True)
        out = os.path.join(config_dir(), 'hookshot-build.log')
        cmd = [os.path.join(tools, 'python', 'python.exe'), '-I', '-u', 'nx2/make_game.py', '--update', self.path,
               '--log', out]
        return cmd, tools, env, out

    def run_build(self, plan, log=print):
        cmd, cwd, env, out = plan
        log('Building the game in %s again with Hookshot Builder. This takes about a quarter of an hour.'
            % self.path)
        tail = []
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as e:
            raise install.InstallError('Hookshot Builder could not be started: %s' % e)
        with proc:
            asked = False               # (Ctrl+C on the command line. The builder has no console to hear it.)
            while True:
                try:
                    for raw in proc.stdout:
                        line = raw.decode('utf-8', 'replace').rstrip()
                        if line.startswith('@@'):
                            if progress_of(line):
                                log(line)
                        elif line:
                            tail = (tail + [line])[-TAIL:]
                    break
                except KeyboardInterrupt:
                    if asked:
                        end_tree(proc)
                        raise install.InstallError(
                            'the build was stopped before it was done. The game in %s may be half built: build '
                            'it again before you play ("build" here, or in Hookshot Builder)' % self.path)
                    asked = True
                    log('The build goes on: a build that is stopped can leave the game folder half made. Press '
                        'Ctrl+C once more to stop it all the same.')
        if proc.returncode:
            raise install.InstallError('the build stopped with an error. The builder\'s last lines:\n  %s\n'
                                       'All of its output is in %s' % ('\n  '.join(tail), out))

    def build(self, log=print, other_builder=False):
        """Build the game again from the code the folder keeps."""
        self.run_build(self.build_plan(other_builder), log)

    def install(self, values=None, log=print, build=True, other_builder=False):
        """Put the mod into the code the folder is built from, fitted to that code, and build the game."""
        plan = later = None
        if build:
            try:
                plan = self.build_plan(other_builder)
            except BuildElsewhere as e:     # the mod goes into the code all the same: the next build has it
                later = e
        game = install.hookshot_read(self.path)
        fit = install.Fit(game)
        install.write_hookshot(fit, self.path, values)
        report(fit, log)
        if later:
            raise install.InstallError('%s. The mod is now in the code this game folder is built from: %s, and '
                                       'it will be in the game' % (later.why, later.how))
        if not build:
            if self.state()[0] != 'ok':     # (it is 'ok' when the built game holds this very mod already)
                log('The mod is in the code this game folder is built from. It gets into the game with the next '
                    'build: "build" here, or an update of the game in Hookshot Builder.')
            return fit
        self.run_build(plan, log)
        state = self.state()[0]
        if state != 'ok':
            raise install.InstallError('the build finished, but the game it made does not hold the mod (%s). '
                                       'The builder\'s output is in %s' % (HOOKSHOT_TEXT[state][0], plan[3]))
        return fit

    def remove(self, log=print, build=True, other_builder=False):
        """Take the mod out of the code the folder is built from, and build the game without it."""
        built = settings.read_file(os.path.join(self.path, 'image.bin')) is not None
        plan = later = None
        if build and built:
            try:
                plan = self.build_plan(other_builder)
            except BuildElsewhere as e:     # the mod leaves the code all the same: the next build is without it
                later = e
        install.remove_hookshot(self.path)
        if later:
            raise install.InstallError('%s. The mod is out of the code this game folder is built from, and the '
                                       'built game has it until the next build: %s' % (later.why, later.how))
        if plan:
            self.run_build(plan, log)
        elif built:
            log('The mod is out of the code this game folder is built from. The built game has it until the '
                'folder is built again.')

    def conflicts(self):
        return {}

    def mods(self):
        """The other mods in the game folder: [(name, is it on)]. Hookshot skips a mod whose folder name starts
        with - or _."""
        out = {}
        for n in subdirs(self.mods_dir):
            on = n[:1] not in ('-', '_')
            name = n if on else n[1:]
            if name and name not in OURS:
                out[name] = out.get(name, False) or on
        return sorted(out.items(), key=lambda m: m[0].lower())

    def switch(self, name, on):
        plain_name(name)
        have = subdirs(self.mods_dir)
        offs = [n for n in have if n[:1] in ('-', '_') and n[1:] == name]
        if on:
            if name in have:
                return
            if not offs:
                raise install.InstallError('%s has no mod "%s"' % (self.title(), name))
            src, dst = offs[0], name
        else:
            if name not in have:
                if offs:
                    return
                raise install.InstallError('%s has no mod "%s"' % (self.title(), name))
            if offs:
                raise install.InstallError('the mod "%s" is there twice, on and off: remove one of the two '
                                           'folders in %s' % (name, self.mods_dir))
            src, dst = name, '_' + name
        try:
            os.rename(os.path.join(self.mods_dir, src), os.path.join(self.mods_dir, dst))
        except OSError as e:
            raise install.InstallError('the mod "%s" cannot be renamed (is the game running?): %s' % (name, e))


def dlss_sdk(tools):
    """The folder with NVIDIA's DLSS files that a Hookshot Builder fetched, or None."""
    home = builder_home()
    tried = [os.path.join(os.path.dirname(tools), 'ngx-sdk'), os.path.join(tools, 'ngx-sdk')]
    if home:
        tried += [os.path.join(home, 'ngx-sdk'), os.path.join(home, 'versions', 'ngx-sdk')]
    for folder in tried:
        for at, _, files in os.walk(folder):
            if 'nvngx_dlss.dll' in files:
                return folder
    return None


def progress_of(line):
    """('stage', its text) or ('progress', 0..1 within the stage) for a progress line of the builder; None for
    any other line."""
    word, _, rest = line.partition(' ')
    if word == '@@stage' and rest:
        return 'stage', rest.partition(' ')[2] or rest
    if word == '@@progress':
        try:
            return 'progress', min(1.0, max(0.0, float(rest)))
        except ValueError:
            return None
    return None


_nominal = None


def nominal():
    """(where the mod branches out of the game's code, the game build) for the version the mod was made for."""
    global _nominal
    if _nominal is None:
        fit = install.Fit()
        _nominal = (fit.sites(), fit.build_id)
    return _nominal


def kept_game(build_id, copies):
    """The game's code of one build, from a Hookshot game folder that keeps it; None when none of them does."""
    for c in copies:
        if c.kind == 'hookshot' and same_id(kept_build(c.path), build_id):
            try:
                return install.hookshot_read(c.path)
            except install.InstallError:
                continue
    return None


def report(fit, log):
    if fit.known:
        log('Game build %s: the version this mod was made for.' % fit.build_id[:16])
    else:
        log('Game build %s: another version than the mod was made for. It was fitted to it.' % fit.build_id[:16])
    missing = fit.missing()
    if missing:
        log('Not found in this version of the game, and left out: %s.'
            % ', '.join(options.feature_text(f) for f in missing))


# ---- the copies on this PC ----

def data_roots():
    """The folders emulators keep their data folders in."""
    if os.name == 'nt':
        return [p for p in (os.environ.get('APPDATA'),) if p]
    return [os.environ.get('XDG_DATA_HOME') or os.path.join(os.path.expanduser('~'), '.local', 'share')]


def classify(folder, by_hand=True):
    """The copy of the game a folder is. Raises install.InstallError when it is none."""
    p = os.path.abspath(folder)
    base = os.path.basename(p).lower()
    if base == 'bin' and os.path.isfile(os.path.join(p, 'hookshot.exe')):
        p = os.path.dirname(p)
        base = os.path.basename(p).lower()
    if os.path.isfile(os.path.join(p, install.KEPT, 'main')) or os.path.isfile(os.path.join(p, 'hookshot.exe')) \
            or os.path.isfile(os.path.join(p, 'bin', 'hookshot.exe')):
        return Hookshot(p, by_hand)
    if base == TITLE.lower() and os.path.basename(os.path.dirname(p)).lower() == 'load':
        return Emulator(p, by_hand)
    if base == 'load':
        return Emulator(os.path.join(p, TITLE), by_hand)
    for data in (p, os.path.join(p, 'user')):
        if os.path.isdir(os.path.join(data, 'load')):
            return Emulator(os.path.join(data, 'load', TITLE), by_hand)
    raise install.InstallError('%s is not a Hookshot game folder, and not an emulator\'s data folder (the one with '
                               '"load" and "nand" in it; the emulator opens it from its File menu)' % p)


def discover(config):
    """Every copy of the game: the emulators found on this PC, then the copies the player added."""
    out, seen = [], set()

    def add(copy):
        key = os.path.normcase(copy.path)
        if key not in seen:
            seen.add(key)
            out.append(copy)

    for root in data_roots():
        for load in sorted(glob.glob(os.path.join(glob.escape(root), '*', 'load'))):
            emu = Emulator(os.path.join(load, TITLE))
            if os.path.isdir(emu.path) or os.path.isdir(emu.off_dir()) or emu.game_build():
                add(emu)                # it has mods for this game, or has run it
    for c in config.copies:
        add(Hookshot(c['path'], True) if c['kind'] == 'hookshot' else Emulator(c['path'], True))
    return out


def find_copy(copies, text):
    """The copy a player names: by its number in the list, its name or its folder. None when it is none."""
    if text.isdigit() and 1 <= int(text) <= len(copies):
        return copies[int(text) - 1]
    named = [c for c in copies if text.lower() in (c.name.lower(), c.title().lower())]
    if len(named) == 1:
        return named[0]
    key = os.path.normcase(os.path.abspath(text))
    for c in copies:
        if key in (os.path.normcase(c.path), os.path.normcase(getattr(c, 'data', c.path))):
            return c
    return None


def add_copy(config, folder):
    """Add a folder to the player's copies (when it is not found by itself): the copy."""
    copy = classify(folder)
    for c in discover(config):
        if os.path.normcase(c.path) == os.path.normcase(copy.path):
            return c
    config.copies.append(dict(kind=copy.kind, path=copy.path))
    config.save()
    return copy


def forget_copy(config, copy):
    """Take a copy the player added out of the list. False when it is not one of those: a copy that was found
    by itself stays in the list (a line the settings may still hold for it goes all the same)."""
    keep = [c for c in config.copies if os.path.normcase(c['path']) != os.path.normcase(copy.path)]
    if len(keep) == len(config.copies):
        return False
    config.copies = keep
    config.save()
    return bool(copy.by_hand)


def adopt_running(config, games):
    """Add the copies of the game that run now and are not in the list yet (games: what live.Live.poll gave):
    a Hookshot game's folder, and the data folder a portable emulator keeps beside its exe. True when one was
    added."""
    known = {os.path.normcase(c.path) for c in discover(config)}
    new = []
    for r in games:
        if r.kind == 'hookshot' and r.folder and os.path.isfile(os.path.join(r.folder, install.KEPT, 'main')):
            new.append(dict(kind='hookshot', path=os.path.abspath(r.folder)))
        elif r.kind == 'emulator' and r.path and r.found():
            load = os.path.join(os.path.dirname(os.path.abspath(r.path)), 'user', 'load')
            if os.path.isdir(load):
                new.append(dict(kind='emulator', path=os.path.join(load, TITLE)))
    new = [c for c in new if os.path.normcase(c['path']) not in known]
    if new:
        config.copies += new
        config.save()
    return bool(new)


def status(copy):
    """How the mod stands in a copy: dict(state, rec, text, action, missing). `action` names what brings it in
    order ('' when nothing is needed), `missing` the parts that could not be fitted to this copy's game."""
    state, rec = copy.state()
    text, action = (EMULATOR_TEXT if copy.kind == 'emulator' else HOOKSHOT_TEXT)[state]
    features = rec.get('features') if rec and isinstance(rec.get('features'), dict) else {}
    missing = [options.feature_text(f) for f, ok in features.items() if not ok]
    return dict(state=state, rec=rec, text=text, action=action, missing=missing)


def installed(copy):
    return copy.values() is not None


# ---- the switches ----

def start_values(config, copies):
    """The switches to show and to install with: the player's, else those of a copy that has the mod, else the
    starting ones."""
    values = config.values()
    if values:
        return values
    for c in copies:
        values = c.values()
        if values:
            return values
    return settings.defaults()


UNSAVED = 'the switches could not be saved (is a file of the mod in use, or write-protected?)'


def spread_values(copies, values, running=None, skip=()):
    """Set the switches in every copy that has the mod (but those whose folder, as os.path.normcase gives it,
    is in `skip`), and (running: a live.Live that was polled) in the games that run now. Returns what was
    done: [text]."""
    values = settings.clean(values)
    done = []
    for c in copies:
        if os.path.normcase(c.path) in skip:
            continue
        if c.save(values):
            done.append('%s: saved' % c.title())
        elif c.values() is not None:        # the mod is there, and its file did not take them
            done.append('%s: %s' % (c.title(), UNSAVED))
    if running is not None:
        for r, ok in running.push(values):
            done.append('%s: %s' % (r.label(), 'changed in the running game' if ok
                                    else 'the running game could not be changed'))
    return done


def give_values(config, copies, values, running=None):
    """Set the switches everywhere: in the player's settings, in every copy that has the mod, and (running: a
    live.Live that was polled) in the games that run now. Returns what was done: [text]."""
    values = settings.clean(values)
    config.set_values(values)
    config.save()
    return spread_values(copies, values, running)


def remembered_game(config, copy):
    """The game's code from the dump or folder the player gave the last time, when that is the version of the
    game this emulator runs; None when it is not."""
    ran = copy.game_build()
    if not (ran and config.source and os.path.exists(config.source)):
        return None
    try:
        game = sources.open_source(config.source).game()
    except (install.InstallError, nso.NsoError, OSError):
        return None
    return game if game is not None and same_id(game.build_id, ran) else None


# ---- the hookshot targets (a mod of game files, made from the player's own game) ----

FILES_TEXT = {None: 'Off', False: 'N64 hookshot targets', True: 'N64 hookshot targets, and trees'}


def files_state(copy):
    """None (off), False (the N64 targets), True (the targets and trees), or 'broken' (half made)."""
    stamp = hookshot_files.state(copy.mods_dir)
    if stamp is None:
        return None
    return 'broken' if stamp.get('broken') else stamp.get('trees') is True


def files_source(copy, copies, given='', remembered=''):
    """The game's files to make the hookshot targets from: (the files, where they are). In this order: the dump
    or folder that is given, the copy's own files, those of a Hookshot game folder among the copies (one with
    the version of the game the copy runs, if there is one), the dump or folder that was given the last time."""
    def opened(path):
        src = sources.open_source(path)
        if src.romfs is None:
            raise install.InstallError('%s does not hold the game\'s files (its romfs)' % path)
        return src.romfs, src.text

    if given:
        return opened(given)
    if copy.romfs():
        return copy.romfs(), copy.path
    ran = copy.game_build() if copy.kind == 'emulator' else ''
    others = [c for c in copies if c.kind == 'hookshot' and c.romfs()]
    others.sort(key=lambda c: not same_id(kept_build(c.path), ran))
    if others:
        return others[0].romfs(), others[0].path
    if remembered and os.path.exists(remembered):
        return opened(remembered)
    raise NeedsGame('the hookshot targets are made from the game\'s own files: your dump of the game (.nup), a '
                    'folder with its romfs, or a Hookshot game folder')


def build_files(copy, romfs, trees, log=print):
    """Make the hookshot targets in a copy, and turn off the earlier mods that the new folder replaces."""
    if copy.running():
        raise install.InstallError('the game in %s is running: close it first' % copy.path)
    try:
        os.makedirs(copy.mods_dir, exist_ok=True)
        stamp = hookshot_files.build(romfs, copy.mods_dir, trees, log)
    except hookshot_files.FilesError as e:
        raise install.InstallError(str(e))
    for name, on in copy.mods():
        if on and name in hookshot_files.SUPERSEDED:
            copy.switch(name, False)
            log('Turned off the mod "%s": the new folder does what it did.' % name)
    return stamp


def remove_files(copy):
    if copy.running():
        raise install.InstallError('the game in %s is running: close it first' % copy.path)
    folder = os.path.join(copy.mods_dir, hookshot_files.NAME)
    if os.path.isdir(folder):
        stamp = os.path.join(folder, hookshot_files.STAMP)
        if os.path.exists(stamp):
            os.remove(stamp)            # first: a folder that cannot be removed whole then counts as half made
        shutil.rmtree(folder)
