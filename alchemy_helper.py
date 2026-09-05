import json
import os
import time
import tkinter as tk
from tkinter import ttk, messagebox
from difflib import get_close_matches
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ALCHEMY_FILE = os.path.join(BASE_DIR, 'alchemy.json')
TRANSLATIONS_FILE = os.path.join(BASE_DIR, 'translations.json')
PROGRESS_FILE = os.path.join(BASE_DIR, 'progress.json')

# GTA event: every new 10-minute task starts with exactly four base elements.
# Newly discovered elements are added to the current Cabinet; Atlas persists separately.
DEFAULT_SHELF_NAMES = {'water', 'fire', 'earth', 'air'}
SESSION_SECONDS = 10 * 60

BG = '#07100e'
PANEL = '#0c1715'
PANEL2 = '#101d1a'
PANEL3 = '#0a1311'
BORDER = '#1b302b'
TEXT = '#d9e5e1'
MUTED = '#71817c'
ACCENT = '#49d6ad'
ACCENT2 = '#2fb88f'
WARN = '#e6c56a'
DANGER = '#e26d6d'


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


items = {str(k): v for k, v in load_json(ALCHEMY_FILE).items()}
translations = load_json(TRANSLATIONS_FILE)
name_to_id = {v.get('n', '').lower(): k for k, v in items.items() if v.get('n')}
id_to_name_ru = {k: translations.get(v.get('n', ''), v.get('n', k)) for k, v in items.items()}

recipes = defaultdict(list)
children = defaultdict(set)
for rid, data in items.items():
    for pair in data.get('p', []) or []:
        if len(pair) != 2:
            continue
        a, b = str(pair[0]), str(pair[1])
        if a in items and b in items:
            recipes[rid].append((a, b))
            children[a].add(rid)
            children[b].add(rid)


def rid_by_en(name):
    return name_to_id.get(name.lower())


DEFAULT_SHELF = {rid_by_en(n) for n in DEFAULT_SHELF_NAMES if rid_by_en(n)}
PRIME_IDS = {k for k, v in items.items() if v.get('prime')}


def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'atlas': [], 'sessions': []}
    try:
        data = load_json(PROGRESS_FILE)
        data.setdefault('atlas', [])
        data.setdefault('sessions', [])
        data['atlas'] = [str(x) for x in data['atlas'] if str(x) in items]
        return data
    except Exception:
        return {'atlas': [], 'sessions': []}


def save_progress(data):
    tmp = PROGRESS_FILE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PROGRESS_FILE)


progress = load_progress()


def normalize_query(q):
    return ' '.join(q.lower().strip().split())


def find_element(query):
    q = normalize_query(query)
    if not q:
        return None
    if q in name_to_id:
        return name_to_id[q]
    ru = {v.lower(): k for k, v in id_to_name_ru.items()}
    if q in ru:
        return ru[q]
    choices = list(name_to_id.keys()) + list(ru.keys())
    match = get_close_matches(q, choices, n=1, cutoff=0.55)
    if match:
        return name_to_id.get(match[0]) or ru.get(match[0])
    return None


def _relax_costs(start):
    """Calculate the cheapest known dependency level from a starting set.

    Reagents are not consumed. Cost is the number of new discoveries along the
    longest dependency branch. Parent recipes are retained for reconstruction.
    """
    start = set(start)
    cost = {rid: 0 for rid in start}
    parent = {}
    changed = True
    while changed:
        changed = False
        for rid, pairs in recipes.items():
            if rid in start:
                continue
            best = None
            best_pair = None
            for a, b in pairs:
                if a in cost and b in cost:
                    candidate = max(cost[a], cost[b]) + 1
                    if best is None or candidate < best:
                        best = candidate
                        best_pair = (a, b)
            if best is not None and (rid not in cost or best < cost[rid]):
                cost[rid] = best
                parent[rid] = best_pair
                changed = True
    return cost, parent


def build_plan(target, start):
    """Return a dependency-complete, deduplicated plan.

    The returned list is topologically ordered, so every ingredient that is not
    already in `start` appears before the reaction that needs it.
    """
    start = set(start)
    if target in start:
        return []

    cost, parent = _relax_costs(start)
    if target not in cost:
        return None

    ordered = []
    emitted = set()
    visiting = set()

    def visit(rid):
        if rid in start or rid in emitted:
            return True
        if rid in visiting:
            return False
        pair = parent.get(rid)
        if not pair:
            return False
        visiting.add(rid)
        a, b = pair
        if not visit(a) or not visit(b):
            visiting.remove(rid)
            return False
        visiting.remove(rid)
        if rid not in emitted:
            emitted.add(rid)
            ordered.append((a, b, rid))
        return True

    if not visit(target):
        return None
    return ordered


def full_plan(target):
    """Full route from the GTA starting shelf (not the current session shelf)."""
    return build_plan(target, DEFAULT_SHELF)


def format_time(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60:02d}:{seconds % 60:02d}'


class AlchemyApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Alchemy Helper')
        self.geometry('1240x790')
        self.minsize(1050, 700)
        self.configure(bg=BG)

        self.shelf = set(DEFAULT_SHELF)
        self.atlas = set(progress.get('atlas', []))
        self.session_start = None
        self.session_running = False
        self.target_id = None
        self.target_completed = False
        self.session_new = set()
        self.active_tab = 'shelf'
        self._build_styles()
        self._build_ui()
        self._refresh_all()
        self.after(250, self._tick)

    def _build_styles(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('TButton', font=('Segoe UI Semibold', 10), padding=(14, 9), background=PANEL2, foreground=TEXT, borderwidth=0)
        style.map('TButton', background=[('active', '#16332b'), ('pressed', '#1d493d')], foreground=[('active', ACCENT)])
        style.configure('Accent.TButton', background=ACCENT2, foreground='#06100d')
        style.map('Accent.TButton', background=[('active', ACCENT), ('pressed', '#239879')])
        style.configure('TEntry', fieldbackground=PANEL2, foreground=TEXT, insertcolor=ACCENT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=10)
        style.configure('TCheckbutton', background=PANEL, foreground=TEXT, font=('Segoe UI', 10))
        style.map('TCheckbutton', background=[('active', PANEL)], foreground=[('active', ACCENT)])

    def _label(self, parent, text, size=10, color=TEXT, bold=False):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Segoe UI Semibold' if bold else 'Segoe UI', size))

    def _build_ui(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill='x', padx=28, pady=(22, 12))
        title = tk.Label(top, text='⚗  ALCHEMY HELPER', bg=BG, fg=ACCENT, font=('Segoe UI Semibold', 25))
        title.pack(side='left')
        self.status_label = tk.Label(top, text='', bg=BG, fg=MUTED, font=('Segoe UI Semibold', 10))
        self.status_label.pack(side='right', pady=8)

        search = tk.Frame(self, bg=BG)
        search.pack(fill='x', padx=28, pady=(0, 14))
        self.query = tk.StringVar()
        self.entry = ttk.Entry(search, textvariable=self.query, font=('Segoe UI', 12))
        self.entry.pack(side='left', fill='x', expand=True, ipady=5)
        self.entry.bind('<Return>', lambda e: self.find_target())
        self.entry.bind('<Escape>', lambda e: self.query.set(''))
        ttk.Button(search, text='НАЙТИ', style='Accent.TButton', command=self.find_target).pack(side='left', padx=(10, 0))
        ttk.Button(search, text='ОТКРЫТ', command=self.mark_opened).pack(side='left', padx=(8, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill='both', expand=True, padx=28, pady=(0, 22))
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        left.grid(row=0, column=0, sticky='nsew', padx=(0, 9))
        right = tk.Frame(body, bg=PANEL, highlightthickness=1, highlightbackground=BORDER)
        right.grid(row=0, column=1, sticky='nsew', padx=(9, 0))

        self.target_header = tk.Label(left, text='ВЫБЕРИ ЦЕЛЬ', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 19), anchor='w')
        self.target_header.pack(fill='x', padx=22, pady=(20, 2))
        self.target_meta = tk.Label(left, text='Введите элемент и нажмите Enter', bg=PANEL, fg=MUTED, font=('Segoe UI', 10), anchor='w')
        self.target_meta.pack(fill='x', padx=22, pady=(0, 15))

        timer_bar = tk.Frame(left, bg=PANEL2)
        timer_bar.pack(fill='x', padx=22, pady=(0, 14))
        self.timer_label = tk.Label(timer_bar, text='10:00', bg=PANEL2, fg=ACCENT, font=('Consolas', 22, 'bold'))
        self.timer_label.pack(side='left', padx=14, pady=10)
        self.timer_state = tk.Label(timer_bar, text='СЕССИЯ НЕ ЗАПУЩЕНА', bg=PANEL2, fg=MUTED, font=('Segoe UI Semibold', 9))
        self.timer_state.pack(side='left')
        self.start_btn = ttk.Button(timer_bar, text='НАЧАТЬ 10 МИНУТ', style='Accent.TButton', command=self.start_session)
        self.start_btn.pack(side='right', padx=10)

        self.plan_title = tk.Label(left, text='КРАТЧАЙШИЙ ПУТЬ ИЗ ТЕКУЩЕГО ШКАФА', bg=PANEL, fg=MUTED, font=('Segoe UI Semibold', 9), anchor='w')
        self.plan_title.pack(fill='x', padx=22, pady=(4, 8))
        plan_frame = tk.Frame(left, bg=PANEL3)
        plan_frame.pack(fill='both', expand=True, padx=22, pady=(0, 12))
        self.plan_text = tk.Text(plan_frame, bg=PANEL3, fg=TEXT, insertbackground=ACCENT, relief='flat', bd=0, font=('Consolas', 11), padx=14, pady=12)
        self.plan_text.pack(side='left', fill='both', expand=True)
        plan_scroll = ttk.Scrollbar(plan_frame, orient='vertical', command=self.plan_text.yview)
        plan_scroll.pack(side='right', fill='y')
        self.plan_text.configure(yscrollcommand=plan_scroll.set, state='disabled')

        bottom = tk.Frame(left, bg=PANEL)
        bottom.pack(fill='x', padx=22, pady=(0, 20))
        ttk.Button(bottom, text='ЦЕЛЬ ПОЛУЧЕНА ✓', style='Accent.TButton', command=self.complete_target).pack(side='left')
        ttk.Button(bottom, text='СБРОСИТЬ СЕССИЮ', command=self.reset_session).pack(side='right')
        self._build_right_panel(right)

    def _build_right_panel(self, parent):
        tabs = tk.Frame(parent, bg=PANEL)
        tabs.pack(fill='x', padx=16, pady=(16, 10))
        self.tab_buttons = {}
        for key, text in [('shelf', 'ШКАФ'), ('atlas', 'АТЛАС 720')]:
            btn = tk.Button(tabs, text=text, bg=PANEL2, fg=TEXT, activebackground='#16332b', activeforeground=ACCENT,
                            relief='flat', bd=0, font=('Segoe UI Semibold', 10), padx=18, pady=9,
                            command=lambda k=key: self.switch_tab(k))
            btn.pack(side='left', padx=(0, 6))
            self.tab_buttons[key] = btn
        self.shelf_frame = tk.Frame(parent, bg=PANEL)
        self.atlas_frame = tk.Frame(parent, bg=PANEL)
        self._build_shelf_frame()
        self._build_atlas_frame()

    def _build_shelf_frame(self):
        frame = self.shelf_frame
        head = tk.Frame(frame, bg=PANEL)
        head.pack(fill='x', padx=18, pady=(4, 8))
        tk.Label(head, text='ШКАФ РЕАКТИВОВ', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 16)).pack(side='left')
        ttk.Button(head, text='БАЗОВЫЙ НАБОР', command=self.reset_shelf).pack(side='right')
        self.shelf_meta = tk.Label(frame, text='', bg=PANEL, fg=MUTED, font=('Segoe UI', 9), anchor='w')
        self.shelf_meta.pack(fill='x', padx=18, pady=(0, 8))
        self.shelf_search = tk.StringVar()
        ttk.Entry(frame, textvariable=self.shelf_search).pack(fill='x', padx=18, pady=(0, 8), ipady=3)
        self.shelf_search.trace_add('write', lambda *_: self.refresh_shelf())
        list_frame = tk.Frame(frame, bg=PANEL3)
        list_frame.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        self.shelf_list = tk.Listbox(list_frame, bg=PANEL3, fg=TEXT, selectbackground='#1d493d', selectforeground=TEXT,
                                     activestyle='none', relief='flat', bd=0, font=('Segoe UI', 10), highlightthickness=0)
        self.shelf_list.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.shelf_list.yview)
        sb.pack(side='right', fill='y')
        self.shelf_list.configure(yscrollcommand=sb.set)
        self.shelf_list.bind('<Double-Button-1>', self.use_shelf_item)
        tk.Label(frame, text='Двойной клик — поставить элемент целью', bg=PANEL, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=18, pady=(0, 18))

    def _build_atlas_frame(self):
        frame = self.atlas_frame
        head = tk.Frame(frame, bg=PANEL)
        head.pack(fill='x', padx=18, pady=(4, 8))
        tk.Label(head, text='АТЛАС 720', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 16)).pack(side='left')
        ttk.Button(head, text='НАСТРОИТЬ', command=self.open_atlas_editor).pack(side='right')
        ttk.Button(head, text='СБРОС', command=self.clear_atlas).pack(side='right', padx=(0, 6))
        self.atlas_meta = tk.Label(frame, text='', bg=PANEL, fg=MUTED, font=('Segoe UI', 9), anchor='w')
        self.atlas_meta.pack(fill='x', padx=18, pady=(0, 8))
        search_row = tk.Frame(frame, bg=PANEL)
        search_row.pack(fill='x', padx=18, pady=(0, 8))
        self.atlas_search = tk.StringVar()
        ttk.Entry(search_row, textvariable=self.atlas_search).pack(side='left', fill='x', expand=True, ipady=3)
        self.hide_opened = tk.BooleanVar(value=False)
        tk.Checkbutton(search_row, text='Только новые', variable=self.hide_opened, bg=PANEL, fg=TEXT,
                       selectcolor=PANEL2, activebackground=PANEL, activeforeground=ACCENT,
                       command=self.refresh_atlas).pack(side='right', padx=(8, 0))
        self.atlas_search.trace_add('write', lambda *_: self.refresh_atlas())
        list_frame = tk.Frame(frame, bg=PANEL3)
        list_frame.pack(fill='both', expand=True, padx=18, pady=(0, 12))
        self.atlas_list = tk.Listbox(list_frame, bg=PANEL3, fg=TEXT, selectbackground='#1d493d', selectforeground=TEXT,
                                     activestyle='none', relief='flat', bd=0, font=('Segoe UI', 10), highlightthickness=0)
        self.atlas_list.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(list_frame, orient='vertical', command=self.atlas_list.yview)
        sb.pack(side='right', fill='y')
        self.atlas_list.configure(yscrollcommand=sb.set)
        self.atlas_list.bind('<Double-Button-1>', self.use_atlas_item)
        tk.Label(frame, text='Двойной клик — полный путь от Вода + Пламя + Земля + Воздух', bg=PANEL, fg=MUTED, font=('Segoe UI', 9)).pack(anchor='w', padx=18, pady=(0, 18))

    def switch_tab(self, key):
        self.active_tab = key
        if key == 'shelf':
            self.atlas_frame.pack_forget()
            self.shelf_frame.pack(fill='both', expand=True)
        else:
            self.shelf_frame.pack_forget()
            self.atlas_frame.pack(fill='both', expand=True)
        self._update_tab_buttons()

    def _update_tab_buttons(self):
        for key, btn in self.tab_buttons.items():
            btn.config(bg=ACCENT2 if key == self.active_tab else PANEL2, fg='#06100d' if key == self.active_tab else TEXT)

    def _refresh_all(self):
        self.switch_tab(self.active_tab)
        self.refresh_shelf()
        self.refresh_atlas()
        self._update_target_ui()
        self._update_progress_ui()

    def _update_progress_ui(self):
        self.status_label.config(text=f'АТЛАС  {len(self.atlas)} / 720')

    def _show_plan(self, plan, base_start=None):
        self.plan_text.configure(state='normal')
        self.plan_text.delete('1.0', 'end')
        if plan is None:
            self.plan_text.insert('end', 'Путь не найден из текущего шкафа.')
        elif not plan:
            self.plan_text.insert('end', 'Элемент уже есть в текущем шкафу.')
        else:
            for i, (a, b, rid) in enumerate(plan, 1):
                self.plan_text.insert('end', f'{i:02d}.  {id_to_name_ru[a]} + {id_to_name_ru[b]}  →  {id_to_name_ru[rid]}\n')
        self.plan_text.configure(state='disabled')

    def _update_target_ui(self):
        if not self.target_id:
            self.target_header.config(text='ВЫБЕРИ ЦЕЛЬ')
            self.target_meta.config(text='Введите элемент и нажмите Enter')
            self.plan_title.config(text='КРАТЧАЙШИЙ ПУТЬ ИЗ ТЕКУЩЕГО ШКАФА')
            self._show_plan([])
            return
        rid = self.target_id
        plan = build_plan(rid, self.shelf)
        self.target_header.config(text=id_to_name_ru[rid].upper())
        if rid in self.shelf:
            self.target_meta.config(text='Элемент уже открыт в текущем шкафу ✓')
        elif plan is None:
            self.target_meta.config(text='Нет доступного пути из текущего шкафа')
        else:
            self.target_meta.config(text=f'Кратчайший путь  ·  {len(plan)} шагов')
        self.plan_title.config(text='КРАТЧАЙШИЙ ПУТЬ ИЗ ТЕКУЩЕГО ШКАФА')
        self._show_plan(plan, base_start=self.shelf)

    def _show_full_plan(self, rid):
        plan = full_plan(rid)
        self.target_id = rid
        self.query.set(id_to_name_ru[rid])
        self.target_header.config(text=id_to_name_ru[rid].upper())
        if rid in DEFAULT_SHELF:
            self.target_meta.config(text='Элемент входит в стартовый шкаф')
        elif plan is None:
            self.target_meta.config(text='Полный путь от стартового шкафа не найден')
        else:
            self.target_meta.config(text=f'Полный путь от стартового шкафа  ·  {len(plan)} шагов')
        self.plan_title.config(text='ПОЛНЫЙ ПУТЬ ОТ СТАРТОВОГО ШКАФА')
        self._show_plan(plan, base_start=DEFAULT_SHELF)
        self._animate_plan()

    def find_target(self):
        rid = find_element(self.query.get())
        if not rid:
            messagebox.showinfo('Alchemy Helper', 'Элемент не найден. Проверь название.')
            return
        self.target_id = rid
        self._update_target_ui()
        self._animate_plan()

    def _animate_plan(self):
        original = self.target_header.cget('fg')
        self.target_header.config(fg=ACCENT)
        self.after(180, lambda: self.target_header.config(fg=original))

    def start_session(self):
        self.session_start = time.monotonic()
        self.session_running = True
        self.target_completed = False
        self.session_new = set()
        self.shelf = set(DEFAULT_SHELF)
        self.timer_label.config(text='10:00', fg=ACCENT)
        self.timer_state.config(text='СМЕНА ИДЁТ', fg=ACCENT)
        self.start_btn.config(text='СМЕНА ИДЁТ', state='disabled')
        self.refresh_shelf()
        self.refresh_atlas()
        self.refresh_target_after_session()

    def refresh_target_after_session(self):
        self._update_target_ui()
        self.refresh_shelf()

    def reset_session(self):
        self.session_running = False
        self.session_start = None
        self.target_completed = False
        self.session_new.clear()
        self.shelf = set(DEFAULT_SHELF)
        self.timer_label.config(text='10:00', fg=ACCENT)
        self.timer_state.config(text='СЕССИЯ НЕ ЗАПУЩЕНА', fg=MUTED)
        self.start_btn.config(text='НАЧАТЬ 10 МИНУТ', state='normal')
        self.refresh_shelf()
        self._update_target_ui()

    def complete_target(self):
        if not self.target_id:
            return
        plan = build_plan(self.target_id, self.shelf)
        if self.target_id in self.shelf:
            self.target_completed = True
            return
        if plan is None:
            messagebox.showwarning('Alchemy Helper', 'Сначала нужно получить все элементы по пути.')
            return
        for _, _, rid in plan:
            self._mark_opened_id(rid)
        self.target_completed = True
        self.target_meta.config(text=f'{id_to_name_ru[self.target_id]} получен ✓  ·  можно продолжать исследование')
        self.refresh_shelf()
        self.refresh_atlas()
        self._update_progress_ui()

    def _mark_opened_id(self, rid):
        if rid not in items:
            return
        self.shelf.add(rid)
        if rid not in self.atlas:
            self.atlas.add(rid)
            self.session_new.add(rid)
            progress['atlas'] = sorted(self.atlas, key=lambda x: int(x))
            save_progress(progress)
        self._update_progress_ui()

    def mark_opened(self):
        rid = find_element(self.query.get())
        if not rid:
            messagebox.showinfo('Alchemy Helper', 'Элемент не найден.')
            return
        self._mark_opened_id(rid)
        self.query.set('')
        self.refresh_shelf()
        self.refresh_atlas()
        self._update_target_ui()

    def refresh_shelf(self):
        if not hasattr(self, 'shelf_list'):
            return
        self.shelf_list.delete(0, 'end')
        q = normalize_query(self.shelf_search.get())
        rows = []
        for rid in self.shelf:
            name = id_to_name_ru[rid]
            if q and q not in name.lower() and q not in items[rid].get('n', '').lower():
                continue
            rows.append((name.lower(), rid))
        for _, rid in sorted(rows):
            tag = '  ✓  ' if rid in self.session_new else '  •  '
            self.shelf_list.insert('end', tag + id_to_name_ru[rid])
        self.shelf_meta.config(text=f'Доступно сейчас: {len(self.shelf)}    ·    Новых в этой сессии: {len(self.session_new)}')

    def reset_shelf(self):
        self.shelf = set(DEFAULT_SHELF)
        self.session_new.clear()
        self.refresh_shelf()
        self._update_target_ui()

    def use_shelf_item(self, _event=None):
        idx = self.shelf_list.curselection()
        if not idx:
            return
        text = self.shelf_list.get(idx[0]).strip()[3:].strip()
        rid = find_element(text)
        if rid:
            self.target_id = rid
            self.query.set(id_to_name_ru[rid])
            self._update_target_ui()

    def refresh_atlas(self):
        if not hasattr(self, 'atlas_list'):
            return
        self.atlas_list.delete(0, 'end')
        q = normalize_query(self.atlas_search.get())
        rows = []
        for rid in items:
            opened = rid in self.atlas
            if self.hide_opened.get() and opened:
                continue
            name = id_to_name_ru[rid]
            if q and q not in name.lower() and q not in items[rid].get('n', '').lower():
                continue
            rows.append((name.lower(), rid, opened))
        for _, rid, opened in sorted(rows):
            mark = '✓' if opened else '○'
            self.atlas_list.insert('end', f' {mark}  {id_to_name_ru[rid]}')
        self.atlas_meta.config(text=f'Открыто: {len(self.atlas)}    ·    Осталось: {720-len(self.atlas)}')
        self._update_progress_ui()

    def use_atlas_item(self, _event=None):
        idx = self.atlas_list.curselection()
        if not idx:
            return
        text = self.atlas_list.get(idx[0]).strip()
        if text.startswith('✓') or text.startswith('○'):
            text = text[1:].strip()
        rid = find_element(text)
        if rid:
            self._show_full_plan(rid)

    def open_atlas_editor(self):
        win = tk.Toplevel(self)
        win.title('Настройка Атласа')
        win.geometry('760x650')
        win.minsize(650, 520)
        win.configure(bg=PANEL)
        win.transient(self)

        head = tk.Frame(win, bg=PANEL)
        head.pack(fill='x', padx=18, pady=15)
        tk.Label(head, text='НАСТРОЙКА АТЛАСА', bg=PANEL, fg=TEXT, font=('Segoe UI Semibold', 17)).pack(side='left')
        count_label = tk.Label(head, text='', bg=PANEL, fg=ACCENT, font=('Segoe UI Semibold', 10))
        count_label.pack(side='right')

        search_var = tk.StringVar()
        ent = ttk.Entry(win, textvariable=search_var, font=('Segoe UI', 11))
        ent.pack(fill='x', padx=18, pady=(0, 10), ipady=3)

        frame = tk.Frame(win, bg=PANEL)
        frame.pack(fill='both', expand=True, padx=18)
        canvas = tk.Canvas(frame, bg=PANEL2, highlightthickness=0)
        canvas.pack(side='left', fill='both', expand=True)
        sb = ttk.Scrollbar(frame, orient='vertical', command=canvas.yview)
        sb.pack(side='right', fill='y')
        inner = tk.Frame(canvas, bg=PANEL2)
        canvas.create_window((0, 0), window=inner, anchor='nw')
        inner.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.configure(yscrollcommand=sb.set)

        vars_by_id = {}
        for rid in sorted(items, key=lambda x: id_to_name_ru[x].lower()):
            var = tk.BooleanVar(value=rid in self.atlas)
            vars_by_id[rid] = var

        def rebuild(*_):
            for child in inner.winfo_children():
                child.destroy()
            q = normalize_query(search_var.get())
            shown = 0
            for rid in sorted(items, key=lambda x: id_to_name_ru[x].lower()):
                name = id_to_name_ru[rid]
                if q and q not in name.lower() and q not in items[rid].get('n', '').lower():
                    continue
                cb = tk.Checkbutton(inner, text=name, variable=vars_by_id[rid], anchor='w', bg=PANEL2, fg=TEXT,
                                    selectcolor='#15392f', activebackground=PANEL2, activeforeground=ACCENT,
                                    font=('Segoe UI', 10), padx=12, pady=5)
                cb.pack(fill='x')
                shown += 1
            selected = sum(v.get() for v in vars_by_id.values())
            count_label.config(text=f'{selected} / 720')
            canvas.update_idletasks()

        def save_editor():
            self.atlas = {rid for rid, var in vars_by_id.items() if var.get()}
            progress['atlas'] = sorted(self.atlas, key=lambda x: int(x))
            save_progress(progress)
            self._refresh_all()
            win.destroy()

        search_var.trace_add('write', rebuild)
        rebuild()
        buttons = tk.Frame(win, bg=PANEL)
        buttons.pack(fill='x', padx=18, pady=15)
        ttk.Button(buttons, text='СОХРАНИТЬ', style='Accent.TButton', command=save_editor).pack(side='right')
        ttk.Button(buttons, text='ОТМЕНА', command=win.destroy).pack(side='right', padx=(0, 8))

    def clear_atlas(self):
        if not messagebox.askyesno('Сбросить Атлас', 'Удалить весь сохранённый прогресс 720/720?'):
            return
        self.atlas.clear()
        progress['atlas'] = []
        save_progress(progress)
        self._refresh_all()

    def _tick(self):
        if self.session_running and self.session_start is not None:
            left = SESSION_SECONDS - (time.monotonic() - self.session_start)
            if left <= 0:
                self.session_running = False
                self.timer_label.config(text='00:00', fg=WARN)
                self.timer_state.config(text='СМЕНА ЗАВЕРШЕНА', fg=WARN)
                self.start_btn.config(text='НАЧАТЬ НОВУЮ СМЕНУ', state='normal')
            else:
                self.timer_label.config(text=format_time(left), fg=WARN if left < 60 else ACCENT)
        self.after(250, self._tick)


if __name__ == '__main__':
    app = AlchemyApp()
    app.mainloop()
