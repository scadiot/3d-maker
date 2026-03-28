"""GizmoPositionPanel — Tkinter widget showing and editing the gizmo XYZ position."""

import tkinter as tk

from editor import math3d


class GizmoPositionPanel(tk.Frame):
    """Displays the gizmo's current XYZ position and lets the user type new values.

    Subscribes to ``selection_changed`` and ``polygon_transformed`` events on
    *state* to stay in sync with scene changes.  When the user commits a value
    (Return key or focus-out), all selected vertices are translated so the
    gizmo moves to the requested position, and the action is recorded in
    *history*.
    """

    _BG        = '#1a1a21'
    _BG_HEADER = '#14141b'
    _FG        = '#c8c8d8'
    _FG_DIM    = '#6a6a8a'
    _BG_ENTRY  = '#0e0e16'
    _COLORS    = {'X': '#e05555', 'Y': '#55b855', 'Z': '#5599e0'}

    def __init__(self, master, state, gizmo, history, **kw):
        super().__init__(master, bg=self._BG, **kw)
        self._state   = state
        self._gizmo   = gizmo
        self._history = history
        self._updating = False   # guard against feedback loop

        self._vars = {}   # axis -> tk.StringVar
        self._entries = {}

        self._build()

        state.subscribe('selection_changed',  lambda **_: self._refresh())
        state.subscribe('polygon_transformed', lambda **_: self._refresh())

    # ── UI construction ───────────────────────────────────────────────────────

    def _build(self):
        # Header
        hdr = tk.Frame(self, bg=self._BG_HEADER)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text='Position', bg=self._BG_HEADER, fg=self._FG_DIM,
                 font=('TkDefaultFont', 8), anchor='w',
                 padx=6, pady=3).pack(fill=tk.X)

        # X / Y / Z rows
        body = tk.Frame(self, bg=self._BG, padx=6, pady=4)
        body.pack(fill=tk.X)

        for col, axis in enumerate(('X', 'Y', 'Z')):
            body.columnconfigure(col * 2 + 1, weight=1)
            color = self._COLORS[axis]
            tk.Label(body, text=axis, bg=self._BG, fg=color,
                     font=('TkDefaultFont', 9, 'bold'),
                     anchor='e').grid(row=0, column=col * 2, padx=(8 if col else 0, 3))

            var = tk.StringVar(value='—')
            self._vars[axis] = var

            entry = tk.Entry(
                body, textvariable=var,
                bg=self._BG_ENTRY, fg=self._FG,
                insertbackground=self._FG,
                relief='flat', bd=1,
                font=('TkDefaultFont', 9),
                width=6,
            )
            entry.grid(row=0, column=col * 2 + 1, sticky='ew', pady=4)
            self._entries[axis] = entry

            entry.bind('<Return>',   lambda e, a=axis: self._on_commit(a))
            entry.bind('<FocusOut>', lambda e, a=axis: self._on_commit(a))
            entry.bind('<Escape>',   lambda e: self._refresh())

        # Initial display
        self._refresh()

    # ── Event handlers ────────────────────────────────────────────────────────

    def _refresh(self):
        """Update displayed values from the current gizmo position."""
        self._updating = True
        pos = self._gizmo.get_position(self._state)
        if pos is None:
            for axis in ('X', 'Y', 'Z'):
                self._vars[axis].set('—')
                self._entries[axis].config(state='disabled')
        else:
            for i, axis in enumerate(('X', 'Y', 'Z')):
                self._entries[axis].config(state='normal')
                # Only update if the entry doesn't currently have focus
                # (avoids interrupting the user mid-type)
                if self.focus_get() is not self._entries[axis]:
                    self._vars[axis].set(f'{pos[i]:.4g}')
        self._updating = False

    def _on_commit(self, axis):
        """Called when the user confirms a new value for *axis*."""
        if self._updating:
            return
        raw = self._vars[axis].get().strip()
        try:
            new_val = float(raw)
        except ValueError:
            self._refresh()   # revert to current value
            return

        pos = self._gizmo.get_position(self._state)
        if pos is None:
            self._refresh()
            return

        axis_index = ('X', 'Y', 'Z').index(axis)
        if abs(pos[axis_index] - new_val) < 1e-9:
            return   # no change

        delta = [0.0, 0.0, 0.0]
        delta[axis_index] = new_val - pos[axis_index]
        delta = tuple(delta)

        self._apply_translation(delta)

    # ── Translation logic ─────────────────────────────────────────────────────

    def _apply_translation(self, delta):
        """Translate all selected elements by *delta* and record in history."""
        state   = self._state
        history = self._history

        before = {}   # {Polygon: list[vertex]}

        if state.selected_vertices:
            poly_updates = {}
            for poly, vi in state.selected_vertices:
                q = poly.vertices
                if vi >= len(q):
                    continue
                before.setdefault(poly, list(q))
                poly_updates.setdefault(poly, {})[vi] = math3d.vadd(tuple(q[vi]), delta)
            for poly, vi_map in poly_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_map.items():
                    q[vi] = new_v
                poly.vertices = q

        elif state.selected_edges:
            poly_updates = {}
            for poly, ei in state.selected_edges:
                q = poly.vertices
                n = len(q)
                before.setdefault(poly, list(q))
                poly_updates.setdefault(poly, {})[ei]           = math3d.vadd(tuple(q[ei]), delta)
                poly_updates.setdefault(poly, {})[(ei+1) % n]  = math3d.vadd(tuple(q[(ei+1) % n]), delta)
            for poly, vi_map in poly_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_map.items():
                    q[vi] = new_v
                poly.vertices = q

        else:
            polys = self._gizmo._effective_polys(state)
            if not polys:
                return
            for poly in polys:
                before[poly] = list(poly.vertices)
                poly.vertices = [math3d.vadd(tuple(v), delta) for v in poly.vertices]

        if not before:
            return

        after = {p: list(p.vertices) for p in before}
        state.notify_polygon_transformed(list(before.keys()))

        from editor.history import TransformCommand
        history.record(TransformCommand(state, before, after))
