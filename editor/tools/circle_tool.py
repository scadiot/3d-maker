import math

from OpenGL.GL import (
    glEnable, glDisable, glBlendFunc, glBegin, glEnd, glVertex3f, glColor4f, glLineWidth,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_DEPTH_TEST,
    GL_QUADS, GL_LINE_LOOP,
)

from .tool import Tool
from ..utils.math3d import ray_plane_intersect


_N       = 20    # border points per circle
_R_INNER = 5.0   # inner radius (m)
_R_OUTER = 7.0   # outer radius (m)

_PLANE_PT = (0.0, 0.0, 0.0)
_PLANE_N  = (0.0, 1.0, 0.0)


def _ring_points(cx, cz, radius, n):
    return [
        (cx + radius * math.cos(2 * math.pi * i / n),
         0.0,
         cz + radius * math.sin(2 * math.pi * i / n))
        for i in range(n)
    ]


class CircleTool(Tool):
    name = 'circle'
    captures_mouse_down = True

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

    def confirm(self) -> None:
        if self._preview is None:
            return
        cx, _, cz = self._preview
        inner = _ring_points(cx, cz, _R_INNER, _N)
        outer = _ring_points(cx, cz, _R_OUTER, _N)
        group = self.state.current_group
        for k in range(_N):
            k1 = (k + 1) % _N
            verts = [inner[k], outer[k], outer[k1], inner[k1]]
            uvs   = [(k/_N, 0.0), (k/_N, 1.0), ((k+1)/_N, 1.0), ((k+1)/_N, 0.0)]
            group.add_polygon(verts, uvs)
        self.scene._emit_scene_changed("polygon_added", polygon=None, group=group)
        self._locked = False
        self._preview = None

    def _compute_hit(self, mx: int, my: int):
        ray_o, ray_d = self.camera.pick_ray(mx, my)
        return ray_plane_intersect(ray_o, ray_d, _PLANE_PT, _PLANE_N)

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
        cx, _, cz = self._preview
        inner = _ring_points(cx, cz, _R_INNER, _N)
        outer = _ring_points(cx, cz, _R_OUTER, _N)

        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # Filled ring
        glColor4f(1.0, 0.5, 0.0, 0.35)
        glBegin(GL_QUADS)
        for k in range(_N):
            k1 = (k + 1) % _N
            glVertex3f(*inner[k])
            glVertex3f(*outer[k])
            glVertex3f(*outer[k1])
            glVertex3f(*inner[k1])
        glEnd()

        # Outlines
        glColor4f(1.0, 0.5, 0.0, 0.9)
        glLineWidth(2.0)
        glBegin(GL_LINE_LOOP)
        for v in inner:
            glVertex3f(*v)
        glEnd()
        glBegin(GL_LINE_LOOP)
        for v in outer:
            glVertex3f(*v)
        glEnd()
        glLineWidth(1.0)

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)

    @property
    def toolbar_button_specs(self):
        def visible():
            return not self.state.tool_active
        return [{"label": "Add Ring (click)", "command": self.activate, "visible": visible}]
