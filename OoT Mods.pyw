#!/usr/bin/env python3
"""OoT Remake Mods: the Mods window.

It lists the copies of the game on this PC (emulators and Hookshot game folders), puts the mod into them, and
sets its switches: in every copy, and at once in a game that is running. Long jobs (an install, a build) run as
the command line does them (install.py); the window shows how they go."""
import os
import queue
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

APP = 'OoT Mods'


def stop(text):
    """Say why the window cannot open, where a player sees it."""
    if os.name == 'nt':
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP, 0x10)
    elif sys.stderr:
        sys.stderr.write(text + '\n')
    sys.exit(1)


if sys.version_info < (3, 8):
    stop('OoT Mods needs Python 3.8 or newer. This is Python %d.%d.' % sys.version_info[:2])
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter import font as tkfont
except ImportError:
    stop('This Python has no tkinter, which the window is made with. Install Python from python.org (its '
         'installer brings tkinter), or use the command line: python install.py')

from ootmods import __version__, cli, install, live, options, settings, targets    # noqa: E402

POLL = 2.0              # seconds between two looks at the running games
DELAY = 350             # ms from a change of a switch to saving it
TICK = 100              # ms between two looks at what the threads have to say
REFRESH = 10.0          # seconds at least between two looks at the copies when the window comes to the front
LOG_LINES = 600
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DUMPS = [('Game dump', '*.nup'), ('All files', '*.*')]
FILES = [('off', None, 'Off'), ('n64', False, 'As on the N64'), ('trees', True, 'As on the N64, and trees too')]
DOING = {'Install': 'Installing the mod in %s', 'Update': 'Updating the mod in %s',
         'Repair': 'Repairing the mod in %s', 'Build': 'Building %s'}
QUARTER = 'That takes about a quarter of an hour, and the game must stay closed meanwhile.'


def job_python():
    """The Python that runs a job: this one, as the program that opens no window of its own."""
    exe = sys.executable or 'python'
    folder, name = os.path.split(exe)
    plain = os.path.join(folder, 'python.exe')
    return plain if name.lower() == 'pythonw.exe' and os.path.isfile(plain) else exe


class App:
    def __init__(self, root):
        self.root = root
        self.unit = root.winfo_fpixels('1i') / 96.0
        self.config = targets.Config()
        self.copies, self.stats = [], []
        self.values = settings.defaults()
        self.have = {}                  # the parts of the mod: does a copy that has the mod have them?
        self.job = None                 # the job that is going on: dict(proc, title, copy, args, mark, said)
        self.held = set()               # the copies a job works on: no switches are written there meanwhile
        self.files = threading.Lock()   # held while switches are written to the copies
        self.todo = queue.Queue()       # for the thread that watches the running games
        self.news = queue.Queue()       # from the threads, for the window
        self.pending = None             # a change of the switches that is not saved yet (an after() id)
        self.loading = False
        self.running = None             # the games that run now, as the copies were last checked against
        self.looked = 0.0               # when the copies were last looked at
        self.griped = ''
        root.title('%s %s' % (APP, __version__))
        root.report_callback_exception = self.trouble
        self.rows = self.others_key = self.files_key = None     # what the lists show now
        self.build()
        self.reload(first=True)
        root.update_idletasks()
        wide, high = root.winfo_reqwidth(), root.winfo_reqheight()
        spare = max(0, self.log.winfo_reqheight() - self.px(30))    # the lines at the bottom may shrink to one
        root.minsize(wide, high - spare)
        room = root.winfo_screenheight() - self.px(96)              # (less the taskbar and the window's title)
        if high > room:                                             # a small screen
            root.geometry('%dx%d' % (wide, max(high - spare, room)))
        self.todo.put(('look', False))
        # The switches the window shows, into every copy that has the mod: a copy may have missed the last
        # change (its file was in use, or the window closed before the change was written). Copies that have
        # them already are left alone.
        self.todo.put(('give', list(self.values), list(self.copies), True))
        self.watcher = threading.Thread(target=self.watch, args=(list(self.config.programs),), daemon=True)
        self.watcher.start()
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.bind('<FocusIn>', self.front)
        root.after(TICK, self.tick)

    def px(self, n):
        return int(round(n * self.unit))

    # ---- the window's parts ----

    def build(self):
        px = self.px
        style = ttk.Style()
        style.configure('Treeview', rowheight=px(24))
        for option in ('foreground', 'background'):     # (Tk 8.6.9 drops the colours of rows without this)
            style.map('Treeview', **{option: [e for e in style.map('Treeview', query_opt=option)
                                              if e[:2] != ('!disabled', '!selected')]})
        style.configure('Help.TLabel', foreground='#5f5f5f')
        style.configure('Warn.TLabel', foreground='#b3261e')
        base = tkfont.nametofont('TkDefaultFont')
        size = base.cget('size')
        self.small = base.copy()
        self.small.configure(size=size - 1 if size > 8 else size)
        self.bold = base.copy()
        self.bold.configure(weight='bold')

        outer = ttk.Frame(self.root, padding=px(10))
        outer.pack(fill='both', expand=True)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)                 # (a taller window has more lines at the bottom)
        left = ttk.LabelFrame(outer, text='Switches', padding=px(10))
        left.grid(row=0, column=0, sticky='nsew', padx=(0, px(10)))
        right = ttk.Frame(outer)
        right.grid(row=0, column=1, sticky='nsew')
        bottom = ttk.Frame(outer)
        bottom.grid(row=1, column=0, columnspan=2, sticky='nsew', pady=(px(10), 0))
        self.build_switches(left)
        self.build_copies(right)
        self.build_bottom(bottom)

    def build_switches(self, box):
        px = self.px
        box.columnconfigure(1, weight=1)
        self.vars, self.inputs, self.greyed, self.parents, self.shown = [], [], [], [], {}
        first = {}                      # part of the mod -> its main switch
        row = 0
        for i, o in enumerate(options.OPTIONS):
            parent = first.get(o['feature'])
            first.setdefault(o['feature'], i)
            self.parents.append(parent)
            indent = px(20) if parent is not None else 0
            gap = px(3) if parent is not None else (px(8) if i else 0)
            change = lambda *_, i=i: self.changed(i)        # noqa: E731
            if o['kind'] == 'switch':
                var = tk.IntVar()
                w = ttk.Checkbutton(box, text=o['text'], variable=var, command=change)
                w.grid(row=row, column=0, columnspan=2, sticky='w', padx=(indent, 0), pady=(gap, 0))
                greyed = [w]
            else:
                label = ttk.Label(box, text=o['text'])
                label.grid(row=row, column=0, sticky='w', padx=(indent, px(10)), pady=(gap, 0))
                if o['kind'] == 'button':
                    var = tk.StringVar()
                    w = ttk.Combobox(box, textvariable=var, state='readonly', width=24,
                                     values=[options.button_text(b) for b in o['buttons']])
                    w.bind('<<ComboboxSelected>>', change)
                    w.grid(row=row, column=1, sticky='w', pady=(gap, 0))
                    greyed = [label, w]
                else:
                    var = tk.DoubleVar()
                    frame = ttk.Frame(box)
                    frame.grid(row=row, column=1, sticky='w', pady=(gap, 0))
                    w = ttk.Scale(frame, from_=o['least'], to=o['most'], variable=var, length=px(130),
                                  command=change)
                    w.pack(side='left')
                    self.shown[i] = ttk.Label(frame, width=7)
                    self.shown[i].pack(side='left', padx=(px(8), 0))
                    greyed = [label, w, self.shown[i]]
            self.vars.append(var)
            self.inputs.append(w)
            self.greyed.append(greyed)
            text = ttk.Label(box, text=o['help'], style='Help.TLabel', font=self.small, wraplength=px(370),
                             justify='left')
            text.grid(row=row + 1, column=0, columnspan=2, sticky='w',
                      padx=(indent + (px(20) if o['kind'] == 'switch' else 0), 0))
            row += 2
        self.clash = ttk.Label(box, style='Warn.TLabel', font=self.small, wraplength=px(390), justify='left')
        self.clash.grid(row=row, column=0, columnspan=2, sticky='w', pady=(px(8), 0))
        self.note = ttk.Label(box, font=self.small, wraplength=px(390), justify='left')
        self.note.grid(row=row + 1, column=0, columnspan=2, sticky='w')
        box.rowconfigure(row + 2, weight=1)
        self.b_start = ttk.Button(box, text='Starting values', command=self.starting)
        self.b_start.grid(row=row + 3, column=0, columnspan=2, sticky='w', pady=(px(6), 0))

    def build_copies(self, box):
        px = self.px
        games = ttk.LabelFrame(box, text='Your copies of the game', padding=px(10))
        games.pack(fill='both', expand=True)
        ttk.Label(games, style='Help.TLabel', font=self.small, wraplength=px(560), justify='left',
                  text='Pick a copy and install the mod in it. The switches on the left are then the same in every '
                       'copy, and a change shows at once in a game that is running.').pack(anchor='w')
        self.tree = ttk.Treeview(games, columns=('name', 'state'), show='headings', height=5, selectmode='browse')
        self.tree.heading('name', text='Game', anchor='w')
        self.tree.heading('state', text='The mod', anchor='w')
        self.tree.column('name', width=px(190), stretch=False)
        self.tree.column('state', width=px(370), stretch=True)
        self.tree.tag_configure('ok', foreground='#0b6a0b')
        self.tree.tag_configure('todo', foreground='#9a5b00')
        self.tree.pack(fill='both', expand=True, pady=(px(6), 0))
        self.tree.bind('<<TreeviewSelect>>', lambda e: self.show_copy())
        row = ttk.Frame(games)
        row.pack(fill='x', pady=(px(8), 0))
        self.b_act = ttk.Button(row, text='Install', command=self.act)
        self.b_fit = ttk.Button(row, text='Fit to a game dump...', command=self.fit)
        self.b_remove = ttk.Button(row, text='Remove', command=self.remove)
        self.b_refresh = ttk.Button(row, text='Refresh', command=self.reload)
        self.b_forget = ttk.Button(row, text='Forget', command=self.forget)
        self.b_add = ttk.Button(row, text='Add a copy...', command=self.add)
        for b in (self.b_act, self.b_fit, self.b_remove):
            b.pack(side='left', padx=(0, px(6)))
        for b in (self.b_refresh, self.b_forget, self.b_add):
            b.pack(side='right', padx=(px(6), 0))
        hold = ttk.Frame(games, height=px(72))          # (a fixed height: the window does not jump)
        hold.pack(fill='x', pady=(px(8), 0))
        hold.pack_propagate(False)
        self.detail = ttk.Label(hold, wraplength=px(560), justify='left', anchor='nw')
        self.detail.pack(fill='both', expand=True)

        self.others = ttk.LabelFrame(box, text='Other mods', padding=px(10))
        self.others.pack(fill='x', pady=(px(10), 0))
        self.others_body = ttk.Frame(self.others)
        self.others_body.pack(fill='x')
        self.others_note = ttk.Label(self.others, style='Warn.TLabel', wraplength=px(560), justify='left')

        targets_box = self.targets_box = ttk.LabelFrame(box, text='Hookshot targets', padding=px(10))
        targets_box.pack(fill='x', pady=(px(10), 0))
        row = ttk.Frame(targets_box)
        row.pack(fill='x')
        self.files_var = tk.StringVar(value='off')
        self.files_now = None
        self.radios = []
        for key, _, text in FILES:
            b = ttk.Radiobutton(row, text=text, value=key, variable=self.files_var, command=self.files_choice)
            b.pack(side='left', padx=(0, px(14)))
            self.radios.append(b)
        self.b_files = ttk.Button(row, text='Apply', command=self.apply_files)
        self.b_files.pack(side='right')
        self.files_note = ttk.Label(targets_box, style='Help.TLabel', font=self.small, wraplength=px(560),
                                    justify='left')
        self.files_note.pack(anchor='w', pady=(px(4), 0))

    def build_bottom(self, box):
        px = self.px
        box.columnconfigure(0, weight=1)
        box.rowconfigure(2, weight=1)
        top = ttk.Frame(box)
        top.grid(row=0, column=0, sticky='ew')
        ttk.Label(top, text='Running now:', font=self.bold).pack(side='left', anchor='n')
        self.live = ttk.Label(top, text='Looking ...', justify='left', wraplength=px(700))
        self.live.pack(side='left', anchor='n', padx=(px(8), 0))
        self.b_deep = ttk.Button(top, text='Search the running emulator', command=self.deep)    # (shown when needed)
        mid = ttk.Frame(box)
        mid.grid(row=1, column=0, sticky='ew', pady=(px(8), 0))
        self.bar = ttk.Progressbar(mid, mode='determinate', maximum=1000, length=px(240))
        self.bar.pack(side='left')
        self.stage = ttk.Label(mid)
        self.stage.pack(side='left', padx=(px(8), 0))
        frame = ttk.Frame(box)
        frame.grid(row=2, column=0, sticky='nsew', pady=(px(6), 0))
        self.log = tk.Text(frame, height=4, wrap='word', state='disabled', font='TkDefaultFont', relief='solid',
                           borderwidth=1, padx=px(6), pady=px(4))
        bar = ttk.Scrollbar(frame, command=self.log.yview)
        self.log.config(yscrollcommand=bar.set)
        bar.pack(side='right', fill='y')
        self.log.pack(side='left', fill='both', expand=True)

    # ---- saying things ----

    def say(self, text):
        self.log.config(state='normal')
        self.log.insert('end', text + '\n')
        if int(self.log.index('end-1c').split('.')[0]) > LOG_LINES:
            self.log.delete('1.0', '%d.0' % (LOG_LINES // 3))
        self.log.see('end')
        self.log.config(state='disabled')

    def trouble(self, exc, value, tb):
        """An error in the window's own code: keep it, and show it."""
        text = ''.join(traceback.format_exception(exc, value, tb))
        try:
            os.makedirs(targets.config_dir(), exist_ok=True)
            with open(os.path.join(targets.config_dir(), 'window-errors.log'), 'a', encoding='utf-8') as f:
                f.write('%s\n%s\n' % (time.strftime('%Y-%m-%d %H:%M:%S'), text))
        except OSError:
            pass
        messagebox.showerror(APP, 'Something went wrong in the window itself:\n\n%s' % text[-1200:],
                             parent=self.root)

    def error(self, text):
        messagebox.showerror(APP, text, parent=self.root)

    # ---- the copies of the game ----

    @staticmethod
    def status(copy):
        try:
            return targets.status(copy)
        except (OSError, ValueError, install.InstallError) as e:
            return dict(state='unread', rec=None, text='Cannot be read: %s' % e, action='', missing=[])

    def selected(self):
        """(the copy that is picked, how the mod stands in it), or (None, None)."""
        picked = self.tree.selection()
        n = int(picked[0]) if picked else -1
        return (self.copies[n], self.stats[n]) if 0 <= n < len(self.copies) else (None, None)

    def reload(self, pick=None, first=False):
        """Look at the copies of the game again."""
        self.looked = time.monotonic()
        if pick is None and self.selected()[0]:
            pick = self.selected()[0].path
        self.copies = targets.discover(self.config)
        self.stats = [self.status(c) for c in self.copies]
        if first:
            self.values = targets.start_values(self.config, self.copies)
            self.show_values()
        rows = [(os.path.normcase(c.path), c.title(), st['text'],
                 'ok' if st['state'] == 'ok' else 'todo' if st['action'] and st['state'] != 'absent' else '')
                for c, st in zip(self.copies, self.stats)]
        keys = [r[0] for r in rows]
        if rows != self.rows:           # (the list is made again only when it has something else to say)
            self.rows = rows
            self.tree.delete(*self.tree.get_children())
            for n, (_, title, text, tag) in enumerate(rows):
                self.tree.insert('', 'end', iid=str(n), values=(title, text), tags=(tag,))
        todo = [n for n, st in enumerate(self.stats) if st['action']]
        if pick and os.path.normcase(pick) in keys:
            n = keys.index(os.path.normcase(pick))
        else:
            n = todo[0] if todo else 0
        if self.copies and tuple(self.tree.selection()) != (str(n),):
            self.tree.selection_set(str(n))
            self.tree.see(str(n))
        have = {}
        for st in self.stats:
            parts = st['rec'].get('features') if isinstance(st['rec'], dict) else None
            if st['state'] not in ('absent', 'nofolder', 'unread') and isinstance(parts, dict):
                for part, there in parts.items():
                    have[part] = have.get(part, False) or bool(there)
        self.have = have
        self.show_copy()
        self.sync()

    def show_copy(self):
        """The buttons and the lists for the copy that is picked."""
        copy, st = self.selected()
        free = not self.job

        def state(on):
            return 'normal' if on and free else 'disabled'

        self.b_add.config(state=state(True))
        self.b_refresh.config(state=state(True))
        if copy is None:
            for b in (self.b_act, self.b_fit, self.b_remove, self.b_forget, self.b_files):
                b.config(state='disabled')
            self.b_act.config(text='Install')
            self.detail.config(text='No copy of the game was found. "Add a copy..." takes a Hookshot game folder, '
                                    'or the data folder of an emulator (the emulator opens it from its File menu).')
            self.show_others(None)
            self.show_files(None)
            return
        self.b_act.config(text=st['action'] or 'Install', state=state(st['action']))
        self.b_fit.config(state=state(copy.kind == 'emulator'))
        self.b_remove.config(state=state(st['state'] not in ('absent', 'nofolder', 'unread')))
        self.b_forget.config(state=state(copy.by_hand))
        lines = [copy.path]
        if st['missing']:
            lines.append('Not in this version of the game, and left out: %s.' % ', '.join(st['missing']))
        if copy.kind == 'emulator' and st['state'] == 'ok':
            lines.append('The game starts with the mod the next time it is started in %s.' % copy.title())
        elif copy.kind == 'emulator' and st['state'] == 'refit':
            lines.append('Repair fits it to the version of the game that %s runs now.' % copy.title())
        elif copy.kind == 'hookshot' and st['action']:
            lines.append('%s builds the game again with Hookshot Builder (about a quarter of an hour).'
                         % st['action'])
        self.detail.config(text='\n'.join(lines))
        self.show_others(copy)
        self.show_files(copy)

    def show_others(self, copy):
        mods, bad, wrong = [], {}, ''
        if copy is not None:
            try:
                mods, bad = copy.mods(), copy.conflicts()
            except (OSError, install.InstallError) as e:
                wrong = str(e)
        key = (copy.path if copy else None, tuple(mods), tuple(sorted(bad.items())), wrong, bool(self.job))
        if key == self.others_key:      # (made again only when there is something else to show)
            return
        self.others_key = key
        for w in self.others_body.winfo_children():
            w.destroy()
        self.others_note.pack_forget()
        self.others.config(text='Other mods in %s' % copy.title() if copy else 'Other mods')
        if wrong:
            ttk.Label(self.others_body, text='They cannot be read: %s' % wrong, style='Warn.TLabel').grid(sticky='w')
        elif not mods:
            ttk.Label(self.others_body, text='None.' if copy else '', style='Help.TLabel').grid(sticky='w')
        state = 'disabled' if self.job else 'normal'
        for n, (name, on) in enumerate(mods):
            var = tk.IntVar(value=1 if on else 0)
            b = ttk.Checkbutton(self.others_body, text=name, variable=var, state=state,
                                command=lambda name=name, var=var: self.switch_mod(name, var))
            b.var = var                                 # (kept alive with the button)
            b.grid(row=n // 2, column=n % 2, sticky='w', padx=(0, self.px(24)))
        clashing = ['Turn off "%s": %s.' % (name, bad[name]) for name, on in mods if on and name in bad]
        if clashing:
            self.others_note.config(text='\n'.join(clashing))
            self.others_note.pack(anchor='w', pady=(self.px(4), 0))

    def switch_mod(self, name, var):
        copy = self.selected()[0]
        if copy is None:
            return
        try:
            copy.switch(name, bool(var.get()))
        except (install.InstallError, OSError) as e:
            self.error(str(e))
        self.show_copy()

    def show_files(self, copy):
        now = None
        if copy is not None:
            try:
                now = targets.files_state(copy)
            except OSError:
                now = None
        self.files_now = now
        key = (copy.path if copy else None, now)
        if key != self.files_key:       # (a choice that is not applied yet stays as the player made it)
            self.files_key = key
            self.files_var.set('trees' if now is True else 'off' if now is None else 'n64')
        self.targets_box.config(text='Hookshot targets in %s' % copy.title() if copy else 'Hookshot targets')
        text = ('Wood takes the hookshot as on the N64: bridges, beams, large crates, the roofs of Kakariko, '
                'and every torch stand. A mod of game files that is made from your own game in about a minute, '
                'and used the next time the game starts.')
        if now == 'broken':
            text = 'The files are only half made: apply once more.'
        self.files_note.config(text=text)
        for b in self.radios:
            b.config(state='normal' if copy is not None and not self.job else 'disabled')
        self.files_choice()

    def files_choice(self):
        copy = self.selected()[0]
        want = {key: value for key, value, _ in FILES}[self.files_var.get()]
        differs = self.files_now == 'broken' or want is not self.files_now
        self.b_files.config(state='normal' if copy is not None and differs and not self.job else 'disabled')

    # ---- the switches ----

    def show_values(self):
        self.loading = True
        for i, (o, v) in enumerate(zip(options.OPTIONS, self.values)):
            if o['kind'] == 'button':
                self.inputs[i].current(v)
            else:
                self.vars[i].set(v)
        self.loading = False
        self.sync()

    def read(self):
        out = []
        for o, var, w in zip(options.OPTIONS, self.vars, self.inputs):
            if o['kind'] == 'switch':
                out.append(1 if var.get() else 0)
            elif o['kind'] == 'button':
                out.append(max(0, w.current()))
            else:
                step = o.get('step', 1)
                v = o['least'] + int(round((float(var.get()) - o['least']) / step)) * step
                out.append(min(o['most'], max(o['least'], v)))
        return out

    def changed(self, i=None):
        """A switch was moved: show what follows from it, and save it a moment later."""
        if self.loading:
            return
        values = self.read()
        if i is not None and options.OPTIONS[i]['kind'] == 'button':
            self.inputs[i].selection_clear()            # (the choice is not left looking marked)
        if i is not None and options.OPTIONS[i]['kind'] == 'number':
            self.loading = True
            self.vars[i].set(values[i])                 # the slider stops only at whole steps
            self.loading = False
        if values == self.values:
            return
        self.values = values
        self.sync()
        if self.pending:
            self.root.after_cancel(self.pending)
        self.pending = self.root.after(DELAY, self.give)

    def sync(self):
        """Grey the switches that do nothing as things stand, and say what does not go together."""
        v = self.values
        lacking = []
        for i, o in enumerate(options.OPTIONS):
            absent = self.have.get(o['feature']) is False
            if absent and self.parents[i] is None:
                lacking.append(o['text'])
            off = absent or (self.parents[i] is not None and not v[self.parents[i]])
            for w in self.greyed[i]:
                w.state(['disabled' if off else '!disabled'])
            if i in self.shown:
                self.shown[i].config(text=options.show_value(o, v[i]).replace('%', ' %'))
        self.clash.config(text='\n'.join(options.clashes(v)))
        notes = options.notes(v)
        if lacking:
            notes.append('Not in your version of the game: %s.' % ', '.join(lacking))
        self.note.config(text='\n'.join(notes))

    def give(self, quiet=False):
        """Save the switches, and give them to every copy of the game and to the games that run now. quiet: say
        nothing about it when it goes well (the player changed nothing)."""
        if self.pending:
            self.root.after_cancel(self.pending)
            self.pending = None
        self.config.set_values(self.values)
        try:
            self.config.save()
        except OSError as e:
            self.say('The switches could not be saved: %s' % e)
        self.todo.put(('give', list(self.values), list(self.copies), quiet))

    def starting(self):
        self.values = settings.defaults()
        self.show_values()
        self.give()

    def given(self, done, quiet):
        saved = [t.rpartition(': ')[0] for t in done if t.endswith(': saved')]
        live_ = [t.rpartition(': ')[0] for t in done if t.endswith(': changed in the running game')]
        failed = [t.rpartition(': ')[0] for t in done if t.endswith('could not be changed')]
        unsaved = [t[:-len(targets.UNSAVED) - 2] for t in done if t.endswith(': ' + targets.UNSAVED)]
        if quiet and not failed and not unsaved:
            return
        parts = []
        if live_:
            parts.append('changed in the running game (%s)' % ', '.join(live_))
        if saved:
            parts.append('saved in %s' % ', '.join(saved))
        if failed:
            parts.append('the running game could not be changed (%s)' % ', '.join(failed))
        if unsaved:
            parts.append('NOT saved in %s (is a file of the mod in use, or write-protected?)' % ', '.join(unsaved))
        text = 'Switches: ' + '; '.join(parts) if parts else \
            'Switches saved. No copy of the game has the mod yet: it is installed with them.'
        if not self.job:
            self.stage.config(text=text)

    # ---- what the buttons do ----

    def act(self):
        copy, st = self.selected()
        if copy is None or not st['action']:
            return
        command = cli.COMMAND[st['action']]
        if copy.kind == 'hookshot':
            what = ('Hookshot Builder builds %s again from the code it keeps, with the mod in it.' if command == 'build'
                    else 'The mod goes into the code that %s is built from, and Hookshot Builder then builds the '
                         'game again.') % copy.title()
            if not messagebox.askokcancel(APP, '%s %s' % (what, QUARTER), parent=self.root):
                return
        elif not self.clear_way(copy):
            return
        self.start(DOING[st['action']] % copy.title(), copy, [command, copy.path])

    def clear_way(self, copy):
        """Before the mod goes into an emulator: offer to turn off the mods that get in its way. False when the
        player calls the whole thing off."""
        try:
            bad = copy.conflicts()
            clashing = [name for name, on in copy.mods() if on and name in bad]
        except (OSError, install.InstallError):
            return True
        if not clashing:
            return True
        answer = messagebox.askyesnocancel(
            APP, '%s\n\nTurn %s off first? Nothing is deleted: a mod that is off can be turned on again here.'
            % ('\n'.join('"%s" gets in the way of this mod: %s.' % (name, bad[name]) for name in clashing),
               'it' if len(clashing) == 1 else 'them'), parent=self.root)
        if answer is None:
            return False
        if answer:
            try:
                for name in clashing:
                    copy.switch(name, False)
            except (install.InstallError, OSError) as e:
                self.error(str(e))
                return False
        return True

    def fit(self):
        copy = self.selected()[0]
        if copy is None or copy.kind != 'emulator' or not self.clear_way(copy):
            return
        path = self.ask_dump()
        if path:
            self.start('Fitting the mod in %s to your game dump' % copy.title(), copy,
                       ['install', copy.path, '--game', path])

    def ask_dump(self):
        folder = os.path.dirname(self.config.source) if self.config.source else ''
        path = filedialog.askopenfilename(parent=self.root, title='Your dump of the game', filetypes=DUMPS,
                                          initialdir=folder if os.path.isdir(folder) else None)
        return os.path.normpath(path) if path else ''

    def remove(self):
        copy = self.selected()[0]
        if copy is None:
            return
        text = 'Take the mod out of %s?' % copy.title()
        if copy.kind == 'hookshot':
            text += ' Hookshot Builder then builds the game again without it. ' + QUARTER
        if messagebox.askokcancel(APP, text, parent=self.root):
            self.start('Removing the mod from %s' % copy.title(), copy, ['remove', copy.path])

    def add(self):
        folder = filedialog.askdirectory(parent=self.root, mustexist=True,
                                         title='A Hookshot game folder, or the data folder of an emulator')
        if not folder:
            return
        try:
            copy = targets.add_copy(self.config, os.path.normpath(folder))
        except (install.InstallError, OSError) as e:
            self.error(str(e))
            return
        self.reload(pick=copy.path)

    def forget(self):
        copy = self.selected()[0]
        if copy is not None and targets.forget_copy(self.config, copy):
            self.say('%s is out of the list. Nothing in its folder was changed.' % copy.title())
            self.reload()

    def apply_files(self):
        copy = self.selected()[0]
        if copy is None:
            return
        want = self.files_var.get()
        if want == 'off':
            self.start('Removing the hookshot targets from %s' % copy.title(), copy, ['files', copy.path, '--off'])
        else:
            self.start('Making the hookshot targets in %s' % copy.title(), copy,
                       ['files', copy.path] + (['--trees'] if want == 'trees' else []))

    # ---- a job ----

    def start(self, title, copy, args):
        """Run a job as the command line does it, and show how it goes."""
        if self.job:
            return
        if self.pending:
            self.give()                 # the job installs with the switches as they are now
        cmd = [job_python(), os.path.join(HERE, 'install.py'), '--raw'] + args
        try:
            with self.files:            # (no switches are being written to this copy now, and none will be)
                proc = subprocess.Popen(cmd, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, creationflags=NO_WINDOW)
                self.held.add(os.path.normcase(copy.path))
        except OSError as e:
            self.error('The job could not be started: %s' % e)
            return
        self.job = dict(proc=proc, title=title, copy=copy, args=args, mark='', said=[])
        threading.Thread(target=self.read_job, args=(proc,), daemon=True).start()
        self.say(title + ' ...')
        self.stage.config(text=title)
        self.bar_show(None)
        self.show_copy()

    def read_job(self, proc):
        """(a thread of its own) Pass on what the job says, and how it ended."""
        for raw in proc.stdout:
            self.news.put(('line', proc, raw.decode('utf-8', 'replace').rstrip('\r\n')))
        self.news.put(('done', proc, proc.wait()))

    def bar_show(self, part):
        """The progress bar: a part of the way (0 to 1), or None for 'busy'."""
        if part is None:
            if str(self.bar.cget('mode')) != 'indeterminate':
                self.bar.config(mode='indeterminate')
                self.bar.start(30)
        else:
            if str(self.bar.cget('mode')) != 'determinate':
                self.bar.stop()
                self.bar.config(mode='determinate')
            self.bar.config(value=part * 1000)

    def job_line(self, line):
        job = self.job
        if line.startswith('@@'):
            got = targets.progress_of(line)
            if got is None:
                if line[2:].strip() in ('ask', 'game', 'error'):    # why the job stopped: the text follows
                    job['mark'] = line[2:].strip()
            elif got[0] == 'stage':
                self.stage.config(text='%s: %s' % (job['title'], got[1]))
                self.bar_show(None)
                self.say('  ' + got[1])
            else:
                self.bar_show(got[1])
            return
        if job['mark']:
            job['said'].append(line)
            if job['mark'] != 'error':
                return                  # (asked in a window of its own)
        self.say(line)

    def job_done(self, code):
        job, self.job = self.job, None
        with self.files:
            self.held.discard(os.path.normcase(job['copy'].path))
        self.bar.stop()
        self.bar.config(mode='determinate', value=0)
        self.stage.config(text='')
        text = '\n'.join(job['said']).strip()
        again = None
        if code == 0:
            self.say('Done.')
        elif code == cli.ASK and job['mark'] == 'ask':
            if messagebox.askyesno(APP, text[:1].upper() + text[1:] + '\n\nBuild the game with the builder on this '
                                   'PC?', parent=self.root):
                again = job['args'] + ['--other-builder']
        elif code == cli.NEED_GAME and job['mark'] == 'game':
            messagebox.showinfo(APP, text[:1].upper() + text[1:] + '\n\nChoose your dump of the game in the next '
                                'window.', parent=self.root)
            path = self.ask_dump()
            if path:
                again = job['args'] + ['--game', path]
        else:
            self.error('%s did not work.\n\n%s' % (job['title'], text[:1].upper() + text[1:] if text else
                                                  'The lines at the bottom of the window say more.'))
        if again:
            self.start(job['title'], job['copy'], again)
            return
        if code:
            self.say('Not done.')
        self.config = targets.Config()      # the job may have written to the settings
        self.reload()
        self.give(quiet=True)               # the switches as they are now, into what the job made

    # ---- the running games ----

    def watch(self, programs):
        """(a thread of its own) Look at the running games every two seconds, and write the switches to the
        copies and to the running games when the window asks. Whatever reads or writes a running game happens
        here, one thing at a time."""
        games = live.Live(programs)
        while True:
            try:
                what = self.todo.get(timeout=POLL)
            except queue.Empty:
                what = ('look', False)
            if what[0] == 'stop':
                return
            try:
                if what[0] == 'give':
                    with self.files:
                        done = targets.spread_values(what[2], what[1], games, set(self.held))
                    self.news.put(('given', done, what[3]))
                else:
                    self.news.put(('games', games.poll(deep=what[1])))
            except Exception:           # (the thread lives on: the next look may go well)
                self.news.put(('trouble', traceback.format_exc()))

    def show_games(self, found):
        if not live.WINDOWS:
            text = 'Running games are only looked into on Windows. Changes are used the next time a game starts.'
        elif not found:
            text = 'No game. Changes are used the next time a game starts.'
        else:
            text = '\n'.join(r.text() for r in found)
        self.live.config(text=text)
        if any(r.kind == 'emulator' and not r.found() and not r.error for r in found):
            self.b_deep.config(state='normal')
            self.b_deep.pack(side='right', anchor='n')
        else:
            self.b_deep.pack_forget()
        now = sorted((r.pid, r.found()) for r in found)
        if now != self.running:         # a game started or ended: is it a copy that is not in the list yet?
            self.running = now
            if targets.adopt_running(self.config, found):
                self.reload()

    def deep(self):
        self.b_deep.config(state='disabled')
        self.live.config(text='Searching the memory of the running emulator. This takes some seconds ...')
        self.todo.put(('look', True))

    def tick(self):
        """Take what the threads have to say."""
        try:
            while True:
                item = self.news.get_nowait()
                if item[0] == 'line':
                    if self.job and item[1] is self.job['proc']:
                        self.job_line(item[2])
                elif item[0] == 'done':
                    if self.job and item[1] is self.job['proc']:
                        self.job_done(item[2])
                elif item[0] == 'given':
                    self.given(item[1], item[2])
                elif item[0] == 'games':
                    self.show_games(item[1])
                elif item[1] != self.griped:
                    self.griped = item[1]
                    self.say(item[1])
        except queue.Empty:
            pass
        finally:
            self.root.after(TICK, self.tick)

    def front(self, event):
        """The window comes to the front: the copies may have changed meanwhile."""
        if event.widget is self.root and not self.job and time.monotonic() - self.looked > REFRESH:
            self.reload()

    def close(self):
        if self.job:
            messagebox.showinfo(APP, '%s is still going on. The window stays open until that is done: stopping in '
                                'the middle could leave the game half built.' % self.job['title'], parent=self.root)
            return
        if self.pending:
            self.give()
        self.todo.put(('stop',))
        self.root.destroy()


def main():
    if os.name == 'nt':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)      # sharp text on a scaled screen
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('RickyZPR.OoTMods')
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    app = App(root)
    root.mainloop()
    app.watcher.join(10)                # (it may still be writing the last change)


if __name__ == '__main__':
    main()
