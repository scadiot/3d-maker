from OpenGL.GL import (
    glEnable, glDisable, glBlendFunc, glBegin, glEnd, glVertex3f, glColor4f, glLineWidth,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_DEPTH_TEST,
    GL_TRIANGLE_FAN, GL_LINE_LOOP,
)

from .tool import Tool
from ..utils.math3d import ray_plane_intersect, ray_poly_intersect, vadd, vscale
from ..core.group import all_polygons, is_visible


class AddQuadTool(Tool):
    name = 'add_quad'
    captures_mouse_down = True

    def activate(self) -> None:
        self._preview = None
        self.state.active_tool_name = self.name
        self.state.tool_active = True
        self.state.selection_enable = False
        self.state.gizmo_enable = False
        self.app._sync_toolbar2_btns()

    def deactivate(self) -> None:
        self._preview = None
        self.state.tool_active = False
        self.state.active_tool_name = ""
        self.state.selection_enable = True
        self.state.gizmo_enable = True
        self.app._sync_toolbar2_btns()

    def _compute_hit(self, mx: int, my: int):
        """Returns snapped (cx, cy, cz) under the mouse, or None."""
        ray_o, ray_d = self.camera.pick_ray(mx, my)
        best_t = float('inf')
        for poly in all_polygons(self.scene.root):
            if not is_visible(poly):
                continue
            t = ray_poly_intersect(ray_o, ray_d, poly.vertices)
            if t is not None and t < best_t:
                best_t = t
        if best_t < float('inf'):
            raw_hit = vadd(ray_o, vscale(ray_d, best_t))
        else:
            raw_hit = ray_plane_intersect(ray_o, ray_d, (0.0, 0.0, 0.0), (0.0, 1.0, 0.0))
        if raw_hit is None:
            return None
        snap = float(self.app._snap_var.get())
        cx = round(raw_hit[0] / snap) * snap
        cy = round(raw_hit[1] / snap) * snap
        cz = round(raw_hit[2] / snap) * snap
        return (cx, cy, cz)

    def update(self, mx: int, my: int) -> None:
        self._preview = self._compute_hit(mx, my)

    def on_mouse_down(self, mx: int, my: int) -> None:
        hit = self._compute_hit(mx, my)
        if hit is not None:
            cx, cy, cz = hit
            group = self.state.current_group
            new_poly = group.add_polygon(
                [(cx - 0.5, cy, cz - 0.5), (cx + 0.5, cy, cz - 0.5),
                 (cx + 0.5, cy, cz + 0.5), (cx - 0.5, cy, cz + 0.5)],
                [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
            )
            self.scene._select_new_polygon(new_poly)
            self.scene._emit_scene_changed("polygon_added", polygon=new_poly, group=group)
        self.deactivate()

    def draw(self) -> None:
        if self._preview is None:
            return
        cx, cy, cz = self._preview
        verts = [
            (cx - 0.5, cy, cz - 0.5),
            (cx + 0.5, cy, cz - 0.5),
            (cx + 0.5, cy, cz + 0.5),
            (cx - 0.5, cy, cz + 0.5),
        ]
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # Filled face
        glColor4f(1.0, 0.5, 0.0, 0.35)
        glBegin(GL_TRIANGLE_FAN)
        for v in verts:
            glVertex3f(*v)
        glEnd()

        # Outline
        glColor4f(1.0, 0.5, 0.0, 0.9)
        glLineWidth(2.0)
        glBegin(GL_LINE_LOOP)
        for v in verts:
            glVertex3f(*v)
        glEnd()
        glLineWidth(1.0)

        glDisable(GL_BLEND)
        glEnable(GL_DEPTH_TEST)

    @property
    def toolbar_button_specs(self):
        def visible():
            return not self.state.tool_active
        return [{"label": "Add Quad (click)", "command": self.activate, "visible": visible}]
