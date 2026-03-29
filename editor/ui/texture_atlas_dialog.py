"""Dialog window for managing texture atlases."""

from __future__ import annotations

import copy
import os
import tkinter as tk
from tkinter import filedialog

from editor.utils.texture_atlas import TextureAtlas


_BG       = '#16161f'
_BG_INPUT = '#1e1e2e'
_BG_BTN   = '#2a2a3a'
_BG_LIST  = '#1e1e2e'
_FG       = '#c8c8d8'
_FG_DIM   = '#7878a0'
_ACCENT   = '#5a8aff'
_SEL_BG   = '#2a3a5a'
_FONT     = ('Segoe UI', 9)
_FONT_LBL = ('Segoe UI', 9)


class TextureAtlasDialog(tk.Toplevel):
    """Window for managing texture atlases."""

    def __init__(self, parent: tk.Widget, state) -> None:
        super().__init__(parent)
        self._state = state
        self._working_atlases: list[TextureAtlas] = copy.deepcopy(state.textures_atlases)
        self._selected_index: int | None = None
        self._updating = False

        self.title("Texture Atlases")
        self.resizable(True, True)
        self.configure(bg=_BG)
        self.transient(parent)

        self._build()
        self._refresh_list()
        self.geometry("800x300")
        self._center(parent)

    # ── Build ──────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        outer = tk.Frame(self, bg=_BG, padx=16, pady=16)
        outer.pack(fill=tk.BOTH, expand=True)

        # ── Left column: buttons + list ────────────────────────────────────────
        left = tk.Frame(outer, bg=_BG)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=False)

        btn_row = tk.Frame(left, bg=_BG)
        btn_row.pack(fill=tk.X, pady=(0, 6))

        btn_cfg = dict(font=_FONT, relief='flat', bd=0, padx=10, pady=5, cursor='hand2')

        tk.Button(btn_row, text="New",
                  bg=_ACCENT, fg='#ffffff',
                  activebackground='#4a7aee', activeforeground='#ffffff',
                  command=self._cmd_new,
                  **btn_cfg).pack(side=tk.LEFT, padx=(0, 6))

        tk.Button(btn_row, text="Delete",
                  bg=_BG_BTN, fg=_FG,
                  activebackground='#35354a', activeforeground=_FG,
                  command=self._cmd_delete,
                  **btn_cfg).pack(side=tk.LEFT)

        list_frame = tk.Frame(left, bg=_BG_LIST, bd=1, relief='flat')
        list_frame.pack(fill=tk.BOTH, expand=True)

        scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self._listbox = tk.Listbox(
            list_frame,
            yscrollcommand=scrollbar.set,
            bg=_BG_LIST, fg=_FG,
            selectbackground=_SEL_BG,
            selectforeground='#ffffff',
            font=_FONT,
            relief='flat',
            bd=0,
            width=30,
            activestyle='none',
            highlightthickness=0,
        )
        self._listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.config(command=self._listbox.yview)

        self._listbox.bind('<<ListboxSelect>>', self._on_select)

        # ── Vertical separator ─────────────────────────────────────────────────
        tk.Frame(outer, bg=_BG_BTN, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=16)

        # ── Right column: fields ───────────────────────────────────────────────
        right = tk.Frame(outer, bg=_BG)
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right.columnconfigure(1, weight=1)

        self._image_path_var = tk.StringVar()
        self._atlas_data_var = tk.StringVar()

        self._image_path_var.trace_add('write', self._on_image_path_changed)
        self._atlas_data_var.trace_add('write', self._on_atlas_data_changed)

        browse_cfg = dict(
            text='\U0001f4c2',  # 📂
            font=('Segoe UI', 10),
            bg=_BG_BTN, fg=_FG,
            activebackground='#35354a', activeforeground=_FG,
            relief='flat', bd=0,
            cursor='hand2',
            width=2, height=1,
        )

        tk.Label(right, text="Image path", bg=_BG, fg=_FG_DIM,
                 font=_FONT_LBL, anchor='w').grid(
            row=0, column=0, sticky='w', padx=(0, 12), pady=(0, 10))

        self._entry_image = tk.Entry(
            right,
            textvariable=self._image_path_var,
            bg=_BG_INPUT, fg=_FG,
            insertbackground=_FG,
            relief='flat', font=_FONT, bd=4,
        )
        self._entry_image.grid(row=0, column=1, sticky='ew', pady=(0, 10))

        self._btn_browse_image = tk.Button(
            right, command=self._browse_image_path, **browse_cfg)
        self._btn_browse_image.grid(row=0, column=2, padx=(6, 0), pady=(0, 10))

        tk.Label(right, text="Atlas data Path", bg=_BG, fg=_FG_DIM,
                 font=_FONT_LBL, anchor='w').grid(
            row=1, column=0, sticky='w', padx=(0, 12))

        self._entry_atlas = tk.Entry(
            right,
            textvariable=self._atlas_data_var,
            bg=_BG_INPUT, fg=_FG,
            insertbackground=_FG,
            relief='flat', font=_FONT, bd=4,
        )
        self._entry_atlas.grid(row=1, column=1, sticky='ew')

        self._btn_browse_atlas = tk.Button(
            right, command=self._browse_atlas_data_path, **browse_cfg)
        self._btn_browse_atlas.grid(row=1, column=2, padx=(6, 0))

        self._set_fields_enabled(False)

        # ── Horizontal separator ───────────────────────────────────────────────
        tk.Frame(self, bg=_BG_BTN, height=1).pack(fill=tk.X)

        # ── Bottom bar: Cancel / Save ──────────────────────────────────────────
        bottom = tk.Frame(self, bg=_BG, padx=16, pady=12)
        bottom.pack(fill=tk.X)

        btn_cfg = dict(font=_FONT, relief='flat', bd=0, padx=16, pady=6, cursor='hand2')

        tk.Button(bottom, text="Cancel",
                  bg=_BG_BTN, fg=_FG,
                  activebackground='#35354a', activeforeground=_FG,
                  command=self._cmd_cancel,
                  **btn_cfg).pack(side=tk.RIGHT, padx=(8, 0))

        tk.Button(bottom, text="Save",
                  bg=_ACCENT, fg='#ffffff',
                  activebackground='#4a7aee', activeforeground='#ffffff',
                  command=self._cmd_save,
                  **btn_cfg).pack(side=tk.RIGHT)

        self.bind('<Escape>', lambda _: self._cmd_cancel())

    # ── List management ────────────────────────────────────────────────────────

    def _refresh_list(self) -> None:
        self._listbox.delete(0, tk.END)
        for atlas in self._working_atlases:
            self._listbox.insert(tk.END, self._atlas_label(atlas))

    @staticmethod
    def _atlas_label(atlas: TextureAtlas) -> str:
        name = os.path.basename(atlas.image_path) if atlas.image_path else "(no image)"
        return f"[{atlas.id}]  {name}"

    def _on_select(self, _event=None) -> None:
        sel = self._listbox.curselection()
        if not sel:
            self._selected_index = None
            self._set_fields_enabled(False)
            return

        idx = sel[0]
        if idx >= len(self._working_atlases):
            return

        self._selected_index = idx
        atlas = self._working_atlases[idx]
        self._updating = True
        self._image_path_var.set(atlas.image_path or '')
        self._atlas_data_var.set(atlas.atlas_data or '')
        self._updating = False
        self._set_fields_enabled(True)

    def _set_fields_enabled(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        self._entry_image.config(state=state)
        self._entry_atlas.config(state=state)
        self._btn_browse_image.config(state=state)
        self._btn_browse_atlas.config(state=state)

    # ── Commands ───────────────────────────────────────────────────────────────

    def _cmd_new(self) -> None:
        new_id = max((a.id for a in self._working_atlases), default=0) + 1
        atlas = TextureAtlas(image_path='', atlas_data='')
        atlas.id = new_id
        self._working_atlases.append(atlas)
        self._refresh_list()
        new_idx = len(self._working_atlases) - 1
        self._listbox.selection_clear(0, tk.END)
        self._listbox.selection_set(new_idx)
        self._listbox.see(new_idx)
        self._on_select()
        self._entry_image.focus_set()

    def _cmd_delete(self) -> None:
        if self._selected_index is None:
            return
        idx = self._selected_index
        if idx >= len(self._working_atlases):
            return
        self._working_atlases.pop(idx)
        self._selected_index = None
        self._refresh_list()
        if self._working_atlases:
            new_idx = min(idx, len(self._working_atlases) - 1)
            self._listbox.selection_set(new_idx)
            self._on_select()
        else:
            self._set_fields_enabled(False)

    def _browse_image_path(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select image file",
            filetypes=[("Image files", "*.png *.jpg *.jpeg *.bmp *.tga *.tiff"), ("All files", "*.*")],
        )
        if path:
            self._image_path_var.set(path)

    def _browse_atlas_data_path(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select atlas data file",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if path:
            self._atlas_data_var.set(path)

    def _cmd_save(self) -> None:
        self._state.change_textures(self._working_atlases)
        self.destroy()

    def _cmd_cancel(self) -> None:
        self.destroy()

    # ── Field change handlers ──────────────────────────────────────────────────

    def _on_image_path_changed(self, *_) -> None:
        if self._updating or self._selected_index is None:
            return
        if self._selected_index >= len(self._working_atlases):
            return
        self._working_atlases[self._selected_index].image_path = self._image_path_var.get()
        self._listbox.delete(self._selected_index)
        self._listbox.insert(self._selected_index,
                             self._atlas_label(self._working_atlases[self._selected_index]))
        self._listbox.selection_set(self._selected_index)

    def _on_atlas_data_changed(self, *_) -> None:
        if self._updating or self._selected_index is None:
            return
        if self._selected_index >= len(self._working_atlases):
            return
        self._working_atlases[self._selected_index].atlas_data = self._atlas_data_var.get()

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _center(self, parent: tk.Widget) -> None:
        self.update_idletasks()
        pw = parent.winfo_rootx() + parent.winfo_width() // 2
        ph = parent.winfo_rooty() + parent.winfo_height() // 2
        w  = self.winfo_width()
        h  = self.winfo_height()
        self.geometry(f"+{pw - w // 2}+{ph - h // 2}")
