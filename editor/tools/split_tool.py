"""SplitTool: interactive polygon-split tool."""

from OpenGL.GL import (
    glDisable, glEnable, glLineWidth, glColor3f, glBegin, glEnd, glVertex3f,
    GL_DEPTH_TEST, GL_LINES,
)

from editor.tools.tool import Tool
from editor.core.group import Polygon, all_polygons
from editor.utils.math3d import (normalize, cross, vsub, vadd, vscale, dot,
                            vlength, ray_plane_intersect, closest_point_on_seg)
from editor.core.history import SplitPolygonCommand


class SplitTool(Tool):

    name = 'split'
    captures_mouse_down = True

    def __init__(self, app):
        super().__init__(app)
        self._split_polygon    = None
        self._split_dir        = None
        self._split_perp       = None
        self._split_origin     = None
        self._split_seg        = None
        self._splitting_active = False

    # ── Toolbar integration ───────────────────────────────────────────────────

    @property
    def toolbar_button_specs(self):
        def visible():
            return (self.state.selection_mode == 'polygon'
                    and len(self.state.selected_polygons) == 1)

        def enabled():
            polys = self.state.selected_polygons
            return bool(polys) and self.app._poly_is_coplanar(polys[0])

        return [{"label": "Split [K]", "command": self.activate,
                 "visible": visible, "enabled": enabled}]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self) -> None:
        self.state.active_tool_name = self.name
        self.state.tool_active = True
        self.state.selection_enable = False
        self.state.gizmo_enable = False

    def deactivate(self) -> None:
        self.state.tool_active = False
        self.state.active_tool_name = ""
        self.state.selection_enable = True
        self.state.gizmo_enable = True
        self._split_polygon    = None
        self._split_seg        = None
        self._splitting_active = False

    def confirm(self) -> None:
        """Confirm the current split segment: create two polygons and delete the original."""
        if self._split_seg is None or self._split_polygon is None:
            return
        pt_a, pt_b = self._split_seg
        poly  = self._split_polygon
        verts = [tuple(v) for v in poly.vertices]
        uvs   = [tuple(u) for u in poly.uvs]
        n = len(verts)

        def find_edge_and_t(pt):
            best_ei, best_t, best_dist = 0, 0.0, float('inf')
            for ei in range(n):
                a, b = verts[ei], verts[(ei + 1) % n]
                ab   = vsub(b, a)
                len2 = dot(ab, ab)
                t    = max(0.0, min(1.0, dot(vsub(pt, a), ab) / len2)) if len2 > 1e-10 else 0.0
                cp   = vadd(a, vscale(ab, t))
                d    = vlength(vsub(pt, cp))
                if d < best_dist:
                    best_dist, best_ei, best_t = d, ei, t
            return best_ei, best_t

        def lerp_uv(uv0, uv1, t):
            return (uv0[0] + t * (uv1[0] - uv0[0]), uv0[1] + t * (uv1[1] - uv0[1]))

        ei_a, t_a = find_edge_and_t(pt_a)
        ei_b, t_b = find_edge_and_t(pt_b)
        if ei_a == ei_b:
            return  # both endpoints on the same edge — degenerate, skip

        uv_a = lerp_uv(uvs[ei_a], uvs[(ei_a + 1) % n], t_a)
        uv_b = lerp_uv(uvs[ei_b], uvs[(ei_b + 1) % n], t_b)

        def walk_polygon(start_pt, start_uv, from_idx, stop_idx, end_pt, end_uv):
            vs, us = [start_pt], [start_uv]
            i = from_idx % n
            while i != stop_idx % n:
                vs.append(verts[i])
                us.append(uvs[i])
                i = (i + 1) % n
            vs.append(end_pt)
            us.append(end_uv)
            return vs, us

        verts1, uvs1 = walk_polygon(pt_a, uv_a, (ei_a + 1) % n, (ei_b + 1) % n, pt_b, uv_b)
        verts2, uvs2 = walk_polygon(pt_b, uv_b, (ei_b + 1) % n, (ei_a + 1) % n, pt_a, uv_a)

        if len(verts1) < 3 or len(verts2) < 3:
            return

        new_poly1 = Polygon(verts1, uvs1)
        new_poly1.texture_atlas_id = poly.texture_atlas_id
        new_poly2 = Polygon(verts2, uvs2)
        new_poly2.texture_atlas_id = poly.texture_atlas_id

        cmd = SplitPolygonCommand(self.state, poly, new_poly1, new_poly2)
        self.history.push(cmd)

        self.deactivate()

    # ── Input ─────────────────────────────────────────────────────────────────

    def on_mouse_down(self, mx: int, my: int) -> None:
        """Begin a polygon-split drag: create a segment parallel to the
        nearest edge of the polygon under the cursor."""
        ray_o, ray_d = self.camera.pick_ray(mx, my)

        poly_idx = self.scene.pick_polygon(ray_o, ray_d)
        if poly_idx < 0:
            return

        poly_obj = all_polygons(self.scene.root)[poly_idx]
        verts = [tuple(v) for v in poly_obj.vertices]
        if len(verts) < 3:
            return

        normal = normalize(cross(vsub(verts[1], verts[0]), vsub(verts[2], verts[0])))
        hit = ray_plane_intersect(ray_o, ray_d, verts[0], normal)
        if hit is None:
            return

        best_edge, best_dist = 0, float('inf')
        n = len(verts)
        for ei in range(n):
            cp = closest_point_on_seg(hit, verts[ei], verts[(ei + 1) % n])
            d = vlength(vsub(hit, cp))
            if d < best_dist:
                best_dist, best_edge = d, ei

        ea = verts[best_edge]
        eb = verts[(best_edge + 1) % n]
        split_dir  = normalize(vsub(eb, ea))
        split_perp = normalize(cross(normal, split_dir))

        self._split_polygon    = poly_obj
        self._split_dir        = split_dir
        self._split_perp       = split_perp
        self._split_origin     = verts[0]
        self._splitting_active = True

        snap = float(self.app._snap_var.get())
        pv = round(dot(vsub(hit, verts[0]), split_perp) / snap) * snap
        self._split_seg = self._compute_split_segment(verts, split_dir, split_perp, verts[0], pv)

    def on_mouse_up(self, mx: int, my: int) -> None:
        self._splitting_active = False

    def update(self, mx: int, my: int) -> None:
        if self._splitting_active and self.app.mouse_btn1:
            self._update_split(mx, my)

    # ── Internals ─────────────────────────────────────────────────────────────

    def _update_split(self, mx, my):
        if self._split_polygon is None:
            return
        verts = [tuple(v) for v in self._split_polygon.vertices]
        if len(verts) < 3:
            return
        normal = normalize(cross(vsub(verts[1], verts[0]), vsub(verts[2], verts[0])))
        ray_o, ray_d = self.camera.pick_ray(mx, my)
        hit = ray_plane_intersect(ray_o, ray_d, verts[0], normal)
        if hit is None:
            return
        snap = float(self.app._snap_var.get())
        pv = round(dot(vsub(hit, self._split_origin), self._split_perp) / snap) * snap
        self._split_seg = self._compute_split_segment(
            verts, self._split_dir, self._split_perp, self._split_origin, pv
        )

    def _compute_split_segment(self, verts, split_dir, split_perp, origin, pv):
        """Return (pt_a, pt_b) where the parallel line at perpendicular
        offset pv intersects the polygon's boundary edges, or None."""
        intersections = []
        n = len(verts)
        for ei in range(n):
            a = verts[ei]
            b = verts[(ei + 1) % n]
            av = dot(vsub(a, origin), split_perp)
            bv = dot(vsub(b, origin), split_perp)
            dv = bv - av
            if abs(dv) < 1e-8:
                continue
            t = (pv - av) / dv
            if -1e-5 <= t <= 1.0 + 1e-5:
                t = max(0.0, min(1.0, t))
                pt = vadd(a, vscale(vsub(b, a), t))
                intersections.append(pt)
        if len(intersections) >= 2:
            intersections.sort(key=lambda p: dot(vsub(p, origin), split_dir))
            return (intersections[0], intersections[-1])
        return None

    # ── Rendering ─────────────────────────────────────────────────────────────

    def draw(self) -> None:
        if not self.state.tool_active or self._split_seg is None:
            return
        pt_a, pt_b = self._split_seg
        glDisable(GL_DEPTH_TEST)
        glLineWidth(2.5)
        glColor3f(0.6, 0.1, 1.0)
        glBegin(GL_LINES)
        glVertex3f(*pt_a)
        glVertex3f(*pt_b)
        glEnd()
        glLineWidth(1.0)
        glEnable(GL_DEPTH_TEST)
