"""The game while it runs: find the mod's settings block in the memory of a running emulator or Hookshot game
and change the switches there, so that a change in the Mods window shows in the game at once. Windows only:
elsewhere nothing is found, and a change takes effect when the game is started the next time.

The block starts the module's data, so it starts a stretch of writable memory: finding it takes one small read
per stretch, and reads nothing else of the program. A Hookshot game keeps the game's memory at a fixed place, so
there it is one read."""
import ctypes
import itertools
import os
import struct
import sys
import time

from . import install, settings

MAGIC = settings.MAGIC
PAGE = 0x1000
HOOKSHOT_GUEST = 0x100000000000         # Hookshot maps the game's memory here ...
HOOKSHOT_IMAGE = 0x80000000             # ... and image.bin is the game's memory from this address of the game on
SEARCH_EVERY = 5.0                      # seconds between two searches of a program that has no block (yet)

# Programs that run the game, by the name of their exe. An emulator this list does not know is still recognised
# by the files beside its exe (SIBLINGS); the settings file can name more ("programs").
PROGRAMS = ['hookshot', 'fritchii', 'lichii', 'eglantine', 'eden', 'eden-cli', 'citron', 'yuzu', 'suyu',
            'sudachi', 'torzu', 'sumi']
SIBLINGS = ['eden-cli.exe', 'yuzu-cmd.exe', 'suyu-cmd.exe', 'citron-cmd.exe', 'sudachi-cmd.exe']
LABELS = {'lichii': 'Fritchii', 'eden-cli': 'Eden'}     # an emulator whose exe has another name than it has itself

WINDOWS = sys.platform == 'win32' and ctypes.sizeof(ctypes.c_void_p) == 8

if WINDOWS:
    import ctypes.wintypes as wt

    k32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class MBI(ctypes.Structure):
        _fields_ = [('BaseAddress', ctypes.c_void_p), ('AllocationBase', ctypes.c_void_p),
                    ('AllocationProtect', wt.DWORD), ('PartitionId', wt.WORD), ('RegionSize', ctypes.c_size_t),
                    ('State', wt.DWORD), ('Protect', wt.DWORD), ('Type', wt.DWORD)]

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [('dwSize', wt.DWORD), ('cntUsage', wt.DWORD), ('th32ProcessID', wt.DWORD),
                    ('th32DefaultHeapID', ctypes.c_size_t), ('th32ModuleID', wt.DWORD), ('cntThreads', wt.DWORD),
                    ('th32ParentProcessID', wt.DWORD), ('pcPriClassBase', wt.LONG), ('dwFlags', wt.DWORD),
                    ('szExeFile', wt.WCHAR * 260)]

    k32.OpenProcess.restype = wt.HANDLE
    k32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    k32.VirtualQueryEx.restype = ctypes.c_size_t
    k32.VirtualQueryEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(MBI), ctypes.c_size_t]
    k32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                      ctypes.POINTER(ctypes.c_size_t)]
    k32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.POINTER(ctypes.c_size_t)]
    k32.CreateToolhelp32Snapshot.restype = wt.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wt.DWORD, wt.DWORD]
    k32.Process32FirstW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.Process32NextW.argtypes = [wt.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    k32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
    k32.K32QueryWorkingSetEx.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD]
    k32.CloseHandle.argtypes = [wt.HANDLE]


def processes():
    """[(pid, exe name)] of everything running."""
    out = []
    if not WINDOWS:
        return out
    snap = k32.CreateToolhelp32Snapshot(2, 0)
    if not snap or snap == wt.HANDLE(-1).value:
        return out
    e = PROCESSENTRY32W()
    e.dwSize = ctypes.sizeof(e)
    ok = k32.Process32FirstW(snap, ctypes.byref(e))
    while ok:
        out.append((e.th32ProcessID, e.szExeFile))
        ok = k32.Process32NextW(snap, ctypes.byref(e))
    k32.CloseHandle(snap)
    return out


def exe_path(pid):
    """The full path of a running program's exe, or None when it cannot be asked."""
    if not WINDOWS:
        return None
    h = k32.OpenProcess(0x1000, False, pid)             # query limited information
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(len(buf))
        return buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
    finally:
        k32.CloseHandle(h)


def stem(name):
    low = name.lower()
    return low[:-4] if low.endswith('.exe') else low


def hookshot_folder(path):
    """The game folder a hookshot.exe belongs to: the exe sits in it, or in its bin."""
    folder = os.path.dirname(path)
    return os.path.dirname(folder) if os.path.basename(folder).lower() == 'bin' else folder


def hookshot_running(folder):
    """The pids of the Hookshot game of one game folder that is running now."""
    want = os.path.normcase(os.path.abspath(folder))
    out = []
    for pid, name in processes():
        if stem(name) == 'hookshot':
            path = exe_path(pid)
            if path and os.path.normcase(os.path.abspath(hookshot_folder(path))) == want:
                out.append(pid)
    return out


class Process:
    def __init__(self, pid, write=False):
        self.pid = pid
        access = 0x0410 | (0x0028 if write else 0)      # query + read (+ write + operation)
        self.h = k32.OpenProcess(access, False, pid) if WINDOWS else None
        if not self.h:
            raise OSError('cannot open process %d' % pid)

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def read(self, addr, size):
        """`size` bytes at an address, or None when not all of them can be read."""
        buf = ctypes.create_string_buffer(size)
        got = ctypes.c_size_t()
        if not k32.ReadProcessMemory(self.h, ctypes.c_void_p(addr), buf, size, ctypes.byref(got)):
            return None
        return buf.raw if got.value == size else None

    def write(self, addr, data):
        data = bytes(data)
        got = ctypes.c_size_t()
        return bool(k32.WriteProcessMemory(self.h, ctypes.c_void_p(addr), data, len(data), ctypes.byref(got))
                    and got.value == len(data))

    def regions(self):
        """The stretches of memory the program can write to: (address, size)."""
        addr, mbi = 0, MBI()
        while k32.VirtualQueryEx(self.h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)):
            base, size = mbi.BaseAddress or 0, mbi.RegionSize
            if mbi.State == 0x1000 and mbi.Protect in (0x04, 0x40):     # committed; read-write (or +execute)
                yield base, size
            if not size:
                break
            addr = base + size
            if addr >= 1 << 47:
                break

    def block(self, addr):
        """The settings block at an address, or None when there is none."""
        raw = self.read(addr, settings.SIZE)
        return settings.parse(raw) if raw and settings.check(raw) else None

    def quick(self):
        """Blocks that start a stretch of writable memory, as the module's data does in an emulator."""
        return [base for base, size in self.regions()
                if size >= PAGE and self.read(base, 8) == MAGIC and self.block(base)]

    def resident(self, base, size):
        """The parts of a stretch that are in memory now: (address, size). Reading only these never makes the
        program load or create pages it has not touched itself (an emulator holds many gigabytes of them)."""
        step = 65536                                    # pages asked about at once
        buf = ctypes.create_string_buffer(step * 16)    # PSAPI_WORKING_SET_EX_INFORMATION: address, attributes
        pages = size // PAGE
        run_at = run = 0
        for first in range(0, pages, step):
            n = min(step, pages - first)
            start = base + first * PAGE
            asked = zip(range(start, start + n * PAGE, PAGE), itertools.repeat(0))
            struct.pack_into('<%dQ' % (2 * n), buf, 0, *itertools.chain.from_iterable(asked))
            if k32.K32QueryWorkingSetEx(self.h, buf, n * 16):
                here = bytes(v & 1 for v in struct.unpack_from('<%dQ' % (2 * n), buf)[1::2])   # 1: in memory
            else:
                here = bytes(n)
            pos = here.find(1)
            while pos >= 0:
                end = here.find(0, pos)
                end = n if end < 0 else end
                at, length = start + pos * PAGE, (end - pos) * PAGE
                if run and run_at + run == at:
                    run += length
                else:
                    if run:
                        yield run_at, run
                    run_at, run = at, length
                pos = here.find(1, end)
        if run:
            yield run_at, run

    def deep(self):
        """Blocks anywhere in the program's writable memory (at the start of a page, as the module's data always
        is). For an emulator that keeps the game's memory in one piece; takes seconds."""
        found = []
        piece = 4 << 20
        for base, size in self.regions():
            for at, length in self.resident(base, size):
                for off in range(0, length, piece):
                    chunk = self.read(at + off, min(piece, length - off))
                    if not chunk:
                        continue
                    pos = chunk.find(MAGIC)
                    while pos >= 0:
                        if pos % PAGE == 0 and self.block(at + off + pos):
                            found.append(at + off + pos)
                        pos = chunk.find(MAGIC, pos + 1)
        return found


class Running:
    """One running program that can hold the game."""

    def __init__(self, pid, name, path):
        self.pid, self.name, self.path = pid, name, path
        self.kind = 'hookshot' if stem(name) == 'hookshot' else 'emulator'
        self.folder = hookshot_folder(path) if path and self.kind == 'hookshot' else None
        self.addrs = []             # where the settings block is in it
        self.count = 0              # the switches its module knows
        self.opt = []               # the switches as the game has them now
        self.avail = []
        self.beats = {}
        self.moved = 0.0            # when the game last showed that it reads the controller
        self.searched = None
        self.error = ''

    def found(self):
        return bool(self.addrs)

    def label(self):
        """The program as a player knows it."""
        if self.kind == 'hookshot':
            return 'Hookshot: %s' % os.path.basename(self.folder) if self.folder else 'Hookshot'
        return LABELS.get(stem(self.name)) or stem(self.name).capitalize()

    def active(self, now=None):
        """True when the game is running the mod: it read the controller in the last seconds."""
        return bool(self.addrs and self.moved) and (now or time.monotonic()) - self.moved < 4.0

    def text(self):
        name = self.label()
        if self.error:
            return '%s: %s' % (name, self.error)
        if not self.addrs:
            return '%s is running; no game with the mod in it' % name
        if not self.count:
            return '%s: the game runs an early test version of the mod, which has no live settings' % name
        if self.active():
            return '%s: the game is running with the mod; changes show at once' % name
        return '%s: the mod is loaded; the game is not reading the controller with it (yet)' % name


class Live:
    """The running games, looked at again with every poll()."""

    def __init__(self, programs=()):
        self.names = {stem(n) for n in PROGRAMS} | {stem(n) for n in programs}
        self.seen = {}              # pid -> Running
        self.judged = {}            # (pid, exe name) -> can it hold the game?

    def candidate(self, pid, name):
        if stem(name) in self.names:
            return True
        key = (pid, name.lower())
        if key not in self.judged:                      # an emulator of another name: by the files beside it
            path = exe_path(pid) if pid > 4 else None
            folder = os.path.dirname(path) if path else None
            self.judged[key] = bool(folder) and any(os.path.isfile(os.path.join(folder, s)) for s in SIBLINGS)
        return self.judged[key]

    def poll(self, deep=False):
        """Look at what is running: [Running]. deep=True also searches all the memory of a program that has no
        block where one is expected (slow: for the one time a player asks for it)."""
        now = time.monotonic()
        alive = []
        listed = processes()
        for pid, name in listed:
            if not self.candidate(pid, name):
                continue
            r = self.seen.get(pid)
            if r is None or r.name != name:
                r = self.seen[pid] = Running(pid, name, exe_path(pid))
            alive.append(pid)
            self.look(r, now, deep)
        for pid in [p for p in self.seen if p not in alive]:
            del self.seen[pid]
        gone = set(self.judged) - {(pid, name.lower()) for pid, name in listed}
        for key in gone:
            del self.judged[key]
        return [self.seen[pid] for pid in alive]

    def look(self, r, now, deep):
        try:
            proc = Process(r.pid)
        except OSError:
            r.addrs, r.error = [], 'cannot be read (is it running as administrator?)'
            return
        r.error = ''
        try:
            addrs = [a for a in r.addrs if proc.block(a)]
            if not addrs and (deep or r.searched is None or now - r.searched >= SEARCH_EVERY):
                r.searched = now
                addrs = self.find(proc, r, deep)
            blocks = [(a, proc.block(a)) for a in addrs]
        finally:
            proc.close()
        blocks = [(a, b) for a, b in blocks if b]
        r.addrs = [a for a, b in blocks]
        if not blocks:
            r.count, r.opt, r.avail, r.beats = 0, [], [], {}
            return
        best = max(blocks, key=lambda ab: ab[1]['beat'])[1]         # a stale copy of the block stands still
        r.count, r.opt, r.avail = best['count'], best['opt'][:best['count']], best['avail']
        beats = {a: b['beat'] for a, b in blocks}
        if any(a in r.beats and r.beats[a] != beat for a, beat in beats.items()):
            r.moved = now
        r.beats = beats

    def find(self, proc, r, deep):
        if r.folder:                                    # a Hookshot game: the block's place follows from its files
            where = install.image_module(r.folder)
            if where:
                addr = HOOKSHOT_GUEST + HOOKSHOT_IMAGE + where[1]
                if proc.block(addr):
                    return [addr]
        return proc.quick() or (proc.deep() if deep else [])

    def push(self, values):
        """Give the switches to every running game that has the mod: [(Running, written?)]."""
        vals = settings.clean(values)
        out = []
        for r in list(self.seen.values()):
            if not r.addrs:
                continue
            ok = False
            try:
                with Process(r.pid, write=True) as proc:
                    for addr in r.addrs:
                        b = proc.block(addr)
                        if b and b['count']:            # a module is given only the switches it knows
                            ok = proc.write(addr + settings.OPT, bytes(vals[:b['count']])) or ok
            except OSError:
                pass
            out.append((r, ok))
        return out
