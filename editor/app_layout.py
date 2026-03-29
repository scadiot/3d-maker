"""AppLayoutMixin: panel, viewport, statusbar, and resize bars."""

import tkinter as tk

from editor.constants import PANEL_WIDTH, VIEW_WIDTH, HEIGHT
from editor.uv_selector          import UVSelector
from editor.group_panel          import GroupPanel
from editor.gizmo_position_panel import GizmoPositionPanel

_SEP_WIDTH           = 5
_PANEL_MIN_WIDTH     = 200
_PANEL_MAX_WIDTH     = 1500
_TOTAL_CONTENT_WIDTH = PANEL_WIDTH + VIEW_WIDTH


class AppLayoutMixin:

    # ── Panels ────────────────────────────────────────────────────────────────
    def _build_panel(self):
        self.panel = tk.Frame(self.root, width=self.panel_width, bg='#1a1a21')
        self.panel.pack(side=tk.LEFT, fill=tk.Y)
        self.panel.pack_propagate(False)

        self.uv_selector = UVSelector(self.panel, self.scene,
                                      on_uv_assigned=self._cmd_uv_assigned)
        self.uv_selector.pack(fill=tk.BOTH, expand=True)

    def _build_right_panel(self):
        self.right_panel = tk.Frame(self.root, width=self.right_panel_width, bg='#1a1a21')
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_panel.pack_propagate(False)

        self.gizmo_position_panel = GizmoPositionPanel(
            self.right_panel, self.state, self.gizmo, self.history)
        self.gizmo_position_panel.pack(fill=tk.X)

        self.group_panel = GroupPanel(self.right_panel, self.scene, self)
        self.group_panel.pack(fill=tk.BOTH, expand=True)

    # ── Statusbar ─────────────────────────────────────────────────────────────
    def _build_statusbar(self):
        BG    = '#111118'
        FG    = '#888899'
        FG_HI = '#c8c8d8'

        self._statusbar = tk.Frame(self.root, bg=BG, height=22)
        self._statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self._statusbar.pack_propagate(False)

        tk.Frame(self._statusbar, height=1, bg='#2a2a3a').pack(side=tk.TOP, fill=tk.X)

        self._status_sel_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG_HI,
                                        font=('Segoe UI', 8), anchor='w', padx=8)
        self._status_sel_lbl.pack(side=tk.LEFT)

        tk.Frame(self._statusbar, width=1, bg='#2a2a3a').pack(side=tk.LEFT, fill=tk.Y, pady=3)

        self._status_group_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG,
                                          font=('Segoe UI', 8), anchor='w', padx=8)
        self._status_group_lbl.pack(side=tk.LEFT)

        self._status_right_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG,
                                          font=('Segoe UI', 8), anchor='e', padx=8)
        self._status_right_lbl.pack(side=tk.RIGHT)

    def _update_statusbar(self):
        n = len(self.scene.selected_indices)
        if n == 0:
            sel_text = 'No selection'
        elif n == 1:
            sel_text = '1 polygon selected'
        else:
            sel_text = f'{n} polygons selected'
        self._status_sel_lbl.config(text=sel_text)

        grp = self.state.current_group
        grp_name = getattr(grp, 'name', None) or 'Root'
        self._status_group_lbl.config(text=f'Group: {grp_name}')

        mode_labels = {'translate': 'Translate', 'rotate': 'Rotate',
                       'scale': 'Scale', 'universal': 'Universal'}
        sel_mode_labels = {'polygon': 'Polygon', 'edge': 'Edge', 'vertex': 'Vertex'}
        right = (f"Gizmo: {mode_labels.get(self.gizmo.mode, self.gizmo.mode)}   "
                 f"Mode: {sel_mode_labels.get(self.state.selection_mode, self.state.selection_mode)}")
        self._status_right_lbl.config(text=right)

    # ── Viewport ──────────────────────────────────────────────────────────────
    def _build_viewport(self):
        vw = _TOTAL_CONTENT_WIDTH - self.panel_width - _SEP_WIDTH
        from editor.app import Viewport3D
        self.viewport = Viewport3D(self.root, self, width=vw, height=HEIGHT)
        self.viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.viewport.bind('<FocusIn>',  self._on_viewport_focus_in)
        self.viewport.bind('<FocusOut>', self._on_viewport_focus_out)

    # ── Left resize bar ───────────────────────────────────────────────────────
    def _build_resize_bar(self):
        self._sep = tk.Frame(self.root, width=_SEP_WIDTH, bg='#2a2a3a',
                             cursor='sb_h_double_arrow')
        self._sep.pack(side=tk.LEFT, fill=tk.Y)
        self._sep.bind('<ButtonPress-1>',   self._on_sep_press)
        self._sep.bind('<ButtonRelease-1>', self._on_sep_release)
        self._sep.bind('<Motion>',          self._on_sep_motion)
        self._sep.bind('<Enter>', lambda _: self._sep.config(bg='#3e3e5a'))
        self._sep.bind('<Leave>', lambda _: self._sep.config(bg='#2a2a3a'
                                            if not self._resizing else '#3e3e5a'))

    def _on_sep_press(self, event):
        self._resizing       = True
        self._resize_start_x  = event.x_root
        self._resize_start_pw = self.panel_width

    def _on_sep_release(self, _):
        self._resizing = False
        self._sep.config(bg='#2a2a3a')

    def _on_sep_motion(self, event):
        if not self._resizing:
            return
        dx = event.x_root - self._resize_start_x
        new_pw = max(_PANEL_MIN_WIDTH, min(_PANEL_MAX_WIDTH,
                                           self._resize_start_pw + dx))
        new_vw = self.root.winfo_width() - new_pw - _SEP_WIDTH * 2 - self.right_panel_width
        if new_vw < 200:
            return
        self.panel_width = new_pw
        self.panel.config(width=new_pw)
        self.viewport.config(width=new_vw)
        self.camera.vw = new_vw

    # ── Right resize bar ──────────────────────────────────────────────────────
    def _build_right_resize_bar(self):
        self._right_sep = tk.Frame(self.root, width=_SEP_WIDTH, bg='#2a2a3a',
                                   cursor='sb_h_double_arrow')
        self._right_sep.pack(side=tk.RIGHT, fill=tk.Y)
        self._right_sep.bind('<ButtonPress-1>',   self._on_right_sep_press)
        self._right_sep.bind('<ButtonRelease-1>', self._on_right_sep_release)
        self._right_sep.bind('<Motion>',          self._on_right_sep_motion)
        self._right_sep.bind('<Enter>', lambda _: self._right_sep.config(bg='#3e3e5a'))
        self._right_sep.bind('<Leave>', lambda _: self._right_sep.config(
            bg='#2a2a3a' if not self._right_resizing else '#3e3e5a'))

    def _on_right_sep_press(self, event):
        self._right_resizing        = True
        self._right_resize_start_x  = event.x_root
        self._right_resize_start_pw = self.right_panel_width

    def _on_right_sep_release(self, _):
        self._right_resizing = False
        self._right_sep.config(bg='#2a2a3a')

    def _on_right_sep_motion(self, event):
        if not self._right_resizing:
            return
        dx = self._right_resize_start_x - event.x_root
        new_pw = max(_PANEL_MIN_WIDTH, min(_PANEL_MAX_WIDTH,
                                           self._right_resize_start_pw + dx))
        new_vw = self.root.winfo_width() - self.panel_width - _SEP_WIDTH * 2 - new_pw
        if new_vw < 200:
            return
        self.right_panel_width = new_pw
        self.right_panel.config(width=new_pw)
        self.viewport.config(width=new_vw)
        self.camera.vw = new_vw
