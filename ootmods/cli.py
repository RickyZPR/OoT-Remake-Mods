"""The installer's command line: python install.py <command>. The Mods window runs its long jobs through it."""
import argparse
import os
import subprocess
import sys
import time

from . import __version__, install, live, nso, options, settings, targets
from . import source as sources
from .nup import NupError

ASK = 3                 # exit code: the command needs a yes from the player first (given with --other-builder)
NEED_GAME = 4           # exit code: the command needs the game's own files (given with --game)
COMMAND = {'Install': 'install', 'Update': 'install', 'Repair': 'install', 'Build': 'build'}


def say(text='', to=None):
    """Print a line. When nobody reads it any more (the pipe was closed: `| more` was left, the Mods window is
    gone) the job goes on without a word: an install or a build that stops half way is worse than a silent
    one."""
    out = to or sys.stdout
    try:
        print(text, file=out, flush=True)
    except OSError:
        try:                    # (what is still to be flushed as Python ends goes nowhere, without a complaint)
            os.dup2(os.open(os.devnull, os.O_WRONLY), out.fileno())
        except (OSError, ValueError, AttributeError):
            pass


def stopped(raw, mark, text, hint=''):
    """Say why a command stopped. raw (for the Mods window): a line that names the kind of stop, then the
    text."""
    if raw:
        say('@@' + mark)
        say(text)
    else:
        say('%s%s%s' % ('Error: ' if mark != 'ask' else '', text, hint), sys.stderr)


def remember(source):
    """Keep where the game's files were read from, for the next time. The settings are read again first: the
    Mods window may have saved switches while this command ran."""
    config = targets.Config()
    config.source = source
    config.save()


class Progress:
    """Takes the lines of a job. The builder's progress lines are shown as a person reads them; raw: as they
    are, for the Mods window."""

    def __init__(self, raw):
        self.raw = raw
        self.tenths = 0

    def __call__(self, line):
        got = targets.progress_of(line) if line.startswith('@@') else None
        if got is None or self.raw:
            say(line)
        elif got[0] == 'stage':
            self.tenths = 0
            say('  ' + got[1])
        elif int(got[1] * 10) > self.tenths:
            self.tenths = int(got[1] * 10)
            say('    %d%%' % (self.tenths * 10))


def pick(config, copies, text):
    """The copy of the game a player names: its number in the list, its name, or its folder."""
    copy = targets.find_copy(copies, text)
    if copy is None and os.path.isdir(text):
        copy = targets.add_copy(config, text)
    if copy is None:
        raise install.InstallError('there is no copy of the game "%s". "install.py status" lists them; a Hookshot '
                                   'game folder or an emulator\'s data folder can be given in its place' % text)
    return copy


def show(n, copy):
    st = targets.status(copy)
    say('%d. %s: %s' % (n, copy.title(), st['text']))
    say('     %s' % copy.path)
    if st['missing']:
        say('     Not in this version of the game: %s' % ', '.join(st['missing']))
    if st['action']:
        say('     %s: install.py %s %d' % (st['action'], COMMAND[st['action']], n))
    files = targets.files_state(copy)
    if files is not None:
        say('     Hookshot targets: %s' % ('half made (make them again: install.py files %d)' % n
                                           if files == 'broken' else targets.FILES_TEXT[files]))
    bad = copy.conflicts()
    for name, on in copy.mods():
        if on and name in bad:
            say('     Turn off the mod "%s" (install.py mods %d "%s" off): %s' % (name, n, name, bad[name]))


def cmd_status(args, config, copies, log):
    say('OoT Mods %s' % __version__)
    if not copies:
        say('No copy of the game was found. Add one: install.py add <a Hookshot game folder, or the data folder '
            'of an emulator>')
    for n, copy in enumerate(copies, 1):
        show(n, copy)


def cmd_install(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    values = targets.start_values(config, copies)
    if copy.kind == 'hookshot':
        if args.game:
            raise install.InstallError('a Hookshot game folder is fitted to the game code it keeps itself: leave '
                                       '--game away')
        if copy.state()[0] == 'ok' and not args.force:
            say('%s: the mod is installed and the game is built with it. Nothing to do (--force does it again).'
                % copy.title())
            return
        copy.install(values, log, build=not args.no_build, other_builder=args.other_builder)
    else:
        game = None
        if args.game:
            src = sources.open_source(args.game)
            game = src.game()
            if game is None:
                raise install.InstallError('%s holds none of the game\'s code (its exefs)' % args.game)
        try:
            copy.install(values, game, log, copies)
        except targets.NeedsGame:
            game = targets.remembered_game(config, copy)
            if game is None:
                raise
            log('Fitting the mod to the game files you gave the last time (%s).' % config.source)
            copy.install(values, game, log, copies)
        if args.game:
            remember(src.text)
    say('%s: %s' % (copy.title(), targets.status(copy)['text']))


def cmd_remove(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    if copy.kind == 'hookshot':
        copy.remove(log, build=not args.no_build, other_builder=args.other_builder)
    else:
        copy.remove()
    say('%s: %s' % (copy.title(), targets.status(copy)['text']))
    if targets.files_state(copy) is not None:
        say('The hookshot targets are a mod of their own and still there. To remove them: install.py files %s '
            '--off (in the window: Off under Hookshot targets).' % subprocess.list2cmdline([args.copy]))


def cmd_build(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    if copy.kind != 'hookshot':
        raise install.InstallError('only a Hookshot game folder is built; an emulator takes the mod as it is')
    copy.build(log, other_builder=args.other_builder)
    say('%s: %s' % (copy.title(), targets.status(copy)['text']))


def cmd_set(args, config, copies, log):
    values = targets.start_values(config, copies)
    for item in args.switch:
        key, sep, text = item.partition('=')
        if not sep or key not in options.INDEX:
            raise install.InstallError('"%s": write a switch as name=value. The switches: %s'
                                       % (item, ', '.join(o['key'] for o in options.OPTIONS)))
        o = options.OPTIONS[options.INDEX[key]]
        try:
            values[options.INDEX[key]] = options.parse_value(o, text)
        except ValueError:
            raise install.InstallError('%s cannot be "%s": it is %s' % (key, text, options.choices(o)))
    games = live.Live(config.programs)
    games.poll()
    done = targets.give_values(config, copies, values, games)
    for line in done:
        say(line)
    if not done:
        say('Saved. No copy of the game has the mod yet: it is installed with these switches.')
    if any(line.endswith(targets.UNSAVED) for line in done):
        raise install.InstallError('not every copy took the switches. They are kept, and are given again the '
                                   'next time a switch is set or the window opens')
    for line in options.clashes(values):
        say('Careful: ' + line)
    for line in options.notes(values):
        say('Note: ' + line)


def cmd_get(args, config, copies, log):
    for o, v in zip(options.OPTIONS, targets.start_values(config, copies)):
        say('%-14s %-6s %s (%s)' % (o['key'], options.show_value(o, v), o['text'], options.choices(o)))


def cmd_files(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    if args.off:
        targets.remove_files(copy)
        say('%s: the hookshot targets are removed.' % copy.title())
        return
    romfs, where = targets.files_source(copy, copies, args.game or '', config.source)
    say('The game\'s files are read from %s' % where)
    targets.build_files(copy, romfs, args.trees, log)
    if args.game:
        remember(where)
    say('%s: %s' % (copy.title(), targets.FILES_TEXT[bool(args.trees)]))


def cmd_mods(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    if args.name:
        if args.to not in ('on', 'off'):
            raise install.InstallError('say what the mod "%s" is to be: on or off' % args.name)
        copy.switch(args.name, args.to == 'on')
    bad = copy.conflicts()
    mods = copy.mods()
    if not mods:
        say('%s has no other mods for the game.' % copy.title())
    for name, on in mods:
        say('%-3s  %s%s' % ('on' if on else 'off', name,
                            '   (turn it off: %s)' % bad[name] if on and name in bad else ''))


def cmd_add(args, config, copies, log):
    copy = targets.add_copy(config, args.folder)
    show(1 + [os.path.normcase(c.path) for c in targets.discover(config)].index(os.path.normcase(copy.path)), copy)


def cmd_forget(args, config, copies, log):
    copy = pick(config, copies, args.copy)
    if not targets.forget_copy(config, copy):
        raise install.InstallError('%s was found by itself, not added: it stays in the list' % copy.title())
    say('%s is out of the list. Nothing in its folder was changed.' % copy.title())


def cmd_live(args, config, copies, log):
    games = live.Live(config.programs)
    if not games.poll(deep=args.deep):
        say('No emulator and no Hookshot game is running.' if live.WINDOWS
            else 'Running games are only looked into on Windows.')
        return
    time.sleep(1.0)                     # a game that runs the mod shows it by counting on
    found = games.poll()
    for r in found:
        say(r.text())
        if r.found() and r.count:
            say('     ' + ' '.join('%s=%s' % (o['key'], options.show_value(o, v))
                                   for i, (o, v) in enumerate(zip(options.OPTIONS, r.opt)) if settings.fits(i, v)))
    targets.adopt_running(config, found)


def parser():
    p = argparse.ArgumentParser(
        prog='install.py', description='OoT Remake Mods %s: puts the mod into the copies of the game on this PC '
        '(emulators and Hookshot game folders), and sets its switches. Without a command: status. A <copy> is '
        'its number in the status list, its name, or its folder.' % __version__)
    p.add_argument('--raw', action='store_true', help=argparse.SUPPRESS)
    sub = p.add_subparsers(dest='command', metavar='command')

    def add(name, fn, text):
        s = sub.add_parser(name, help=text, description=text)
        s.set_defaults(fn=fn)
        return s

    add('status', cmd_status, 'list the copies of the game and how the mod stands in each')
    s = add('install', cmd_install, 'put the mod into a copy, or update or repair it there')
    s.add_argument('copy')
    s.add_argument('--game', metavar='PATH', help='for an emulator: the game\'s own files to fit the mod to (your '
                   '.nup dump, a folder with the game\'s exefs, or a Hookshot game folder). Needed only when the '
                   'game is another version than the mod was made for')
    s.add_argument('--no-build', action='store_true', help='Hookshot: do not build the game now')
    s.add_argument('--other-builder', action='store_true', help='Hookshot: build with the Hookshot Builder on '
                   'this PC even when the game was built with another version (the game is updated to it)')
    s.add_argument('--force', action='store_true', help='Hookshot: install and build even when all is in order')
    s = add('remove', cmd_remove, 'take the mod out of a copy')
    s.add_argument('copy')
    s.add_argument('--no-build', action='store_true', help='Hookshot: do not build the game now')
    s.add_argument('--other-builder', action='store_true', help=argparse.SUPPRESS)
    s = add('build', cmd_build, 'build a Hookshot game folder again from the code it keeps')
    s.add_argument('copy')
    s.add_argument('--other-builder', action='store_true', help='build with the Hookshot Builder on this PC even '
                   'when the game was built with another version')
    s = add('set', cmd_set, 'set switches, in every copy and in the running game: set sprint=R3 hero=on')
    s.add_argument('switch', nargs='+', metavar='name=value')
    add('get', cmd_get, 'show the switches and what each can be')
    s = add('files', cmd_files, 'make the N64 hookshot targets (a mod of game files) from your own game')
    s.add_argument('copy')
    s.add_argument('--trees', action='store_true', help='trees take the hookshot too')
    s.add_argument('--off', action='store_true', help='remove the hookshot targets')
    s.add_argument('--game', metavar='PATH', help='the game\'s files to make them from: your .nup dump, a folder '
                   'with the game\'s romfs, or a Hookshot game folder')
    s = add('mods', cmd_mods, 'list a copy\'s other mods, or turn one on or off: mods 1 "Dungeon Blood" off')
    s.add_argument('copy')
    s.add_argument('name', nargs='?')
    s.add_argument('to', nargs='?', metavar='on|off')
    s = add('add', cmd_add, 'add a copy that was not found by itself: a Hookshot game folder, or the data folder '
            'of an emulator')
    s.add_argument('folder')
    s = add('forget', cmd_forget, 'take an added copy out of the list (its folder is not touched)')
    s.add_argument('copy')
    s = add('live', cmd_live, 'say which running games have the mod')
    s.add_argument('--deep', action='store_true', help='search all the memory of a running emulator (slow)')
    return p


def other_python(args, argv):
    """Run the command under a Python that has what this one lacks (the zstandard package, which reading a dump
    and making the hookshot targets need): the one a Hookshot Builder brings. Returns its exit code, or None
    when this Python does the job."""
    dump = getattr(args, 'game', None)
    needed = (args.command == 'files' and not args.off) or bool(dump and os.path.isfile(dump))
    if not needed or os.environ.get('OOTMODS_HELPER'):
        return None
    try:
        import zstandard    # noqa: F401
        return None
    except ImportError:
        pass
    python = targets.helper_python()
    if not python:
        return None             # the job itself says which package to install
    script = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'install.py')
    return subprocess.call([python, '-I', script] + list(argv), env=dict(os.environ, OOTMODS_HELPER='1'))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    args = parser().parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            if args.raw:
                stream.reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
            else:
                stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass
    code = other_python(args, argv)
    if code is not None:
        return code
    try:
        config = targets.Config()
        fn = getattr(args, 'fn', cmd_status)
        fn(args, config, targets.discover(config), Progress(args.raw))
    except targets.OtherBuilder as e:
        stopped(args.raw, 'ask', '%s.' % e, ' To do that, give the command again with --other-builder.')
        return ASK
    except targets.NeedsGame as e:
        stopped(args.raw, 'game', '%s.' % e, ' Give them with --game <path>.')
        return NEED_GAME
    except (install.InstallError, nso.NsoError, NupError, OSError) as e:
        stopped(args.raw, 'error', str(e))
        return 1
    except KeyboardInterrupt:
        return 130
    return 0
