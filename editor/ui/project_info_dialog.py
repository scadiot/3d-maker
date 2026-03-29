"""Dialog window for editing project information."""

import tkinter as tk


_BG       = '#16161f'
_BG_INPUT = '#1e1e2e'
_BG_BTN   = '#2a2a3a'
_FG       = '#c8c8d8'
_FG_DIM   = '#7878a0'
_ACCENT   = '#5a8aff'
_FONT     = ('Segoe UI', 9)
_FONT_LBL = ('Segoe UI', 9)


class ProjectInfoDialog(tk.Toplevel):
    """Modal dialog to view/edit project information."""

    def __init__(self, parent: tk.Widget, state):
        super().__init__(parent)
        self._state = state
        self._confirmed = False

        self.title("Project info")
        self.resizable(False, False)
        self.configure(bg=_BG)
        self.transient(parent)
        self.grab_set()

        self._build()
        self._center(parent)
        self.wait_window(self)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self):
        outer = tk.Frame(self, bg=_BG, padx=24, pady=20)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── Grid with two columns ──────────────────────────────────────────────
        grid = tk.Frame(outer, bg=_BG)
        grid.pack(fill=tk.X)
        grid.columnconfigure(0, minsize=110)
        grid.columnconfigure(1, weight=1)

        # Project path (read-only)
        tk.Label(grid, text="Project path", bg=_BG, fg=_FG_DIM,
                 font=_FONT_LBL, anchor='w').grid(
            row=0, column=0, sticky='w', pady=(0, 10))

        path_val = self._state.project_path or "—"
        tk.Label(grid, text=path_val, bg=_BG, fg=_FG,
                 font=_FONT, anchor='w', wraplength=340, justify='left').grid(
            row=0, column=1, sticky='w', pady=(0, 10), padx=(12, 0))

        # Name (editable)
        tk.Label(grid, text="Name", bg=_BG, fg=_FG_DIM,
                 font=_FONT_LBL, anchor='w').grid(
            row=1, column=0, sticky='w')

        self._name_var = tk.StringVar(value=self._state.project_name)
        name_entry = tk.Entry(
            grid,
            textvariable=self._name_var,
            bg=_BG_INPUT, fg=_FG,
            insertbackground=_FG,
            relief='flat',
            font=_FONT,
            bd=4,
        )
        name_entry.grid(row=1, column=1, sticky='ew', padx=(12, 0))
        name_entry.focus_set()
        name_entry.icursor(tk.END)

        # ── Separator ─────────────────────────────────────────────────────────
        tk.Frame(outer, bg=_BG_BTN, height=1).pack(fill=tk.X, pady=(20, 16))

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = tk.Frame(outer, bg=_BG)
        btn_row.pack(anchor='e')

        btn_cfg = dict(font=_FONT, relief='flat', bd=0,
                       padx=16, pady=6, cursor='hand2')

        tk.Button(btn_row, text="Cancel",
                  bg=_BG_BTN, fg=_FG,
                  activebackground='#35354a', activeforeground=_FG,
                  command=self._cancel,
                  **btn_cfg).pack(side=tk.LEFT, padx=(0, 8))

        tk.Button(btn_row, text="Validate",
                  bg=_ACCENT, fg='#ffffff',
                  activebackground='#4a7aee', activeforeground='#ffffff',
                  command=self._validate,
                  **btn_cfg).pack(side=tk.LEFT)

        # Keyboard shortcuts
        self.bind('<Return>', lambda _: self._validate())
        self.bind('<Escape>', lambda _: self._cancel())

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _center(self, parent: tk.Widget):
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width() // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w  = self.winfo_width()
        h  = self.winfo_height()
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")

    def _validate(self):
        self._state.project_name = self._name_var.get().strip()
        self._confirmed = True
        self.destroy()

    def _cancel(self):
        self.destroy()
