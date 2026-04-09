import math
import tkinter as tk

from OpenGL.GL import (
    glEnable, glDisable, glBlendFunc, glBegin, glEnd, glVertex3f, glColor4f, glLineWidth,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_DEPTH_TEST,
    GL_QUADS, GL_LINE_LOOP, GL_LINE_STRIP,
)

from .tool import Tool
from ..utils.math3d import ray_plane_intersect


_N_DEFAULT   = 20    # default number of segments
_R_INNER     = 5.0   # default inner radius (m)
_R_OUTER     = 7.0   # default outer radius (m)
_ARC_DEFAULT = 360.0 # default arc angle (degrees)


def _make_ring_points(center, radius, angles, plane):
    """Generate 3D ring points on the given plane ('X', 'Y', or 'Z')."""
    cx, cy, cz = center
    pts = []
    for a in angles:
        c, s = math.cos(a), math.sin(a)
        if plane == 'Y':
            pts.append((cx + radius * c, cy, cz + radius * s))
        elif plane == 'X':
            pts.append((cx, cy + radius * c, cz + radius * s))
        else:  # Z
            pts.append((cx + radius * c, cy + radius * s, cz))
    return pts


class CircleTool(Tool):
    name = 'circle'
    captures_mouse_down = True

    def __init__(self, app):
        super().__init__(app)
        self._n         = _N_DEFAULT
        self._r_inner   = _R_INNER
        self._r_outer   = _R_OUTER
        self._arc_angle = _ARC_DEFAULT

    def activate(self) -> None:
        self._preview = None
        self._locked = False
        self.state.active_tool_name = self.name
        self.state.tool_active = True
        self.state.selection_enable = False
        self.state.gizmo_enable = False
        self.app._sync_toolbar2_btns()

    def deactivate(self) -> None:
        self._preview = None
        self._locked = False
        self.state.tool_active = False
        self.state.active_tool_name = ""
        self.state.selection_enable = True
        self.state.gizmo_enable = True
        self.app._sync_toolbar2_btns()

    def cancel(self) -> None:
        if self._locked:
            # Unlock: preview returns to following the mouse
            self._locked = False
        else:
            self.deactivate()

    def _is_full_circle(self):
        return abs(self._arc_angle - 360.0) < 0.01

    def _grid_plane(self):
        return self.app.grid_plane

    def _grid_offset(self):
        return self.app.grid_offset

    def _get_ring_points(self, center):
        n      = self._n
        plane  = self._grid_plane()
        full   = self._is_full_circle()
        if full:
            angles = [2 * math.pi * i / n for i in range(n)]
        else:
            arc_rad = math.radians(self._arc_angle)
            angles  = [arc_rad * i / n for i in range(n + 1)]
        return (_make_ring_points(center, self._r_inner, angles, plane),
                _make_ring_points(center, self._r_outer, angles, plane))

    def confirm(self) -> None:
        if self._preview is None:
            return
        n = self._n
        inner, outer = self._get_ring_points(self._preview)
        group = self.state.current_group
        if self._is_full_circle():
            for k in range(n):
                k1 = (k + 1) % n
                verts = [inner[k], outer[k], outer[k1], inner[k1]]
                uvs   = [(k/n, 0.0), (k/n, 1.0), ((k+1)/n, 1.0), ((k+1)/n, 0.0)]
                group.add_polygon(verts, uvs)
        else:
            for k in range(n):
                verts = [inner[k], outer[k], outer[k+1], inner[k+1]]
                uvs   = [(k/n, 0.0), (k/n, 1.0), ((k+1)/n, 1.0), ((k+1)/n, 0.0)]
                group.add_polygon(verts, uvs)
        self.scene._emit_scene_changed("polygon_added", polygon=None, group=group)
        self._locked = False
        self._preview = None

    def _compute_hit(self, mx: int, my: int):
        plane  = self._grid_plane()
        offset = self._grid_offset()
        pt_map = {'Y': (0, offset, 0), 'X': (offset, 0, 0), 'Z': (0, 0, offset)}
        n_map  = {'Y': (0, 1, 0),      'X': (1, 0, 0),      'Z': (0, 0, 1)}
        ray_o, ray_d = self.camera.pick_ray(mx, my)
        hit = ray_plane_intersect(ray_o, ray_d, pt_map[plane], n_map[plane])
        if hit is None:
            return None
        snap = float(self.app._snap_var.get())
        x, y, z = hit
        if plane == 'Y':
            return (round(x / snap) * snap, offset, round(z / snap) * snap)
        elif plane == 'X':
            return (offset, round(y / snap) * snap, round(z / snap) * snap)
        else:  # Z
            return (round(x / snap) * snap, round(y / snap) * snap, offset)

    def update(self, mx: int, my: int) -> None:
        if not self._locked:
            self._preview = self._compute_hit(mx, my)

    def on_mouse_down(self, mx: int, my: int) -> None:
        hit = self._compute_hit(mx, my)
        if hit is None:
            return
        self._preview = hit
        self._locked = True

    def draw(self) -> None:
        if self._preview is None:
            return
        n = self._n
        inner, outer = self._get_ring_points(self._preview)
        full = self._is_full_circle()

        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # Filled ring
        glColor4f(1.0, 0.5, 0.0, 0.35)
        glBegin(GL_QUADS)
        for k in range(n):
            k1 = (k + 1) % n if full else k + 1
            glVertex3f(*inner[k])
            glVertex3f(*outer[k])
            glVertex3f(*outer[k1])
            glVertex3f(*inner[k1])
        glEnd()

        # Outlines
        glColor4f(1.0, 0.5, 0.0, 0.9)
        glLineWidth(2.0)
        outline_mode = GL_LINE_LOOP if full else GL_LINE_STRIP
        glBegin(outline_mode)
        for v in inner:
            glVertex3f(*v)
        glEnd()
        glBegin(outline_mode)
        for v in outer:
            glVertex3f(*v)
        glEnd()
        if not full:
            # Draw the two radial edges closing the arc ends
            glBegin(GL_LINE_STRIP)
            glVertex3f(*inner[0])
            glVertex3f(*outer[0])
            glEnd()
            glBegin(GL_LINE_STRIP)
            glVertex3f(*inner[-1])
            glVertex3f(*outer[-1])
            glEnd()
        glLineWidth(1.0)

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)

    def build_panel(self, parent) -> bool:
        BG     = '#1a1a21'
        BG_HDR = '#111118'
        FG     = '#c8c8d8'
        FG_DIM = '#888899'
        SEP    = '#2a2a3a'

        # Header
        tk.Frame(parent, height=1, bg=SEP).pack(fill=tk.X)
        tk.Label(parent, text='Ring settings', bg=BG_HDR, fg=FG,
                 font=('Segoe UI', 8, 'bold'), anchor='w',
                 padx=8, pady=5).pack(fill=tk.X)
        tk.Frame(parent, height=1, bg=SEP).pack(fill=tk.X)

        body = tk.Frame(parent, bg=BG, padx=8, pady=6)
        body.pack(fill=tk.X)

        def add_field(label, get, set_):
            row = tk.Frame(body, bg=BG)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, bg=BG, fg=FG_DIM,
                     font=('Segoe UI', 8), width=13, anchor='w').pack(side=tk.LEFT)
            var = tk.StringVar(value=str(get()))

            def on_change(*_):
                try:
                    v = float(var.get())
                    if v > 0:
                        set_(v)
                except ValueError:
                    pass

            var.trace_add('write', on_change)
            e = tk.Entry(row, textvariable=var, bg='#2a2a3a', fg=FG,
                         insertbackground=FG, relief='flat', bd=4,
                         font=('Segoe UI', 8), width=8)
            e.pack(side=tk.LEFT)

        def add_int_field(label, get, set_):
            row = tk.Frame(body, bg=BG)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, bg=BG, fg=FG_DIM,
                     font=('Segoe UI', 8), width=13, anchor='w').pack(side=tk.LEFT)
            var = tk.StringVar(value=str(get()))

            def on_int_change(*_):
                try:
                    v = int(var.get())
                    if v >= 3:
                        set_(v)
                except ValueError:
                    pass

            var.trace_add('write', on_int_change)
            e = tk.Entry(row, textvariable=var, bg='#2a2a3a', fg=FG,
                         insertbackground=FG, relief='flat', bd=4,
                         font=('Segoe UI', 8), width=8)
            e.pack(side=tk.LEFT)

        def add_arc_field(label, get, set_):
            row = tk.Frame(body, bg=BG)
            row.pack(fill=tk.X, pady=3)
            tk.Label(row, text=label, bg=BG, fg=FG_DIM,
                     font=('Segoe UI', 8), width=13, anchor='w').pack(side=tk.LEFT)
            var = tk.StringVar(value=str(get()))

            def on_arc_change(*_):
                try:
                    v = float(var.get())
                    if 0 < v <= 360:
                        set_(v)
                except ValueError:
                    pass

            var.trace_add('write', on_arc_change)
            e = tk.Entry(row, textvariable=var, bg='#2a2a3a', fg=FG,
                         insertbackground=FG, relief='flat', bd=4,
                         font=('Segoe UI', 8), width=8)
            e.pack(side=tk.LEFT)

        add_int_field("Segments:", lambda: self._n, lambda v: setattr(self, '_n', v))
        add_field("Inner radius:", lambda: self._r_inner, lambda v: setattr(self, '_r_inner', v))
        add_field("Outer radius:", lambda: self._r_outer, lambda v: setattr(self, '_r_outer', v))
        add_arc_field("Arc angle (°):", lambda: self._arc_angle, lambda v: setattr(self, '_arc_angle', v))
        return True

    @property
    def toolbar_button_specs(self):
        def visible():
            return not self.state.tool_active
        return [{"label": "Add Ring (click)", "command": self.activate, "visible": visible}]
