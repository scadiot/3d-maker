"""Gizmo class: mode, drag state, drawing and picking.

Camera and StateManager are passed as parameters to methods (not stored),
which avoids circular imports.
"""

import math
from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
    glEnable, glDisable,
    GL_LINES, GL_TRIANGLE_FAN, GL_QUADS, GL_LINE_LOOP, GL_DEPTH_TEST,
)

from editor.constants import GIZMO_MODES, GIZMO_AXES, GIZMO_PLANES, SCALE_COLORS
from editor import math3d


# ── Drawing helpers (module-private) ──────────────────────────────────────────
def _draw_arrow_3d(start, tip, color, selected=False):
    r, g, b = (1.0, 0.9, 0.1) if selected else color
    length = math3d.vlength(math3d.vsub(tip, start))
    if length < 1e-10: return
    axis = math3d.normalize(math3d.vsub(tip, start))
    cone_base = math3d.vadd(start, math3d.vscale(axis, length*0.78))
    cone_r = length*0.08;  u, v = math3d.perp_basis(axis);  N = 10
    glColor3f(r, g, b)
    glLineWidth(2.5 if selected else 2.0)
    glBegin(GL_LINES); glVertex3f(*start); glVertex3f(*cone_base); glEnd()
    glLineWidth(1.0)
    glBegin(GL_TRIANGLE_FAN); glVertex3f(*tip)
    for i in range(N+1):
        a = 2*math.pi*i/N
        p = math3d.vadd(cone_base, math3d.vadd(math3d.vscale(u, cone_r*math.cos(a)),
                                               math3d.vscale(v, cone_r*math.sin(a))))
        glVertex3f(*p)
    glEnd()


def _draw_box_3d(pos, size, r, g, b):
    x, y, z = pos;  s = size/2
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    for face in [
        [(x-s,y-s,z+s),(x+s,y-s,z+s),(x+s,y+s,z+s),(x-s,y+s,z+s)],
        [(x+s,y-s,z-s),(x-s,y-s,z-s),(x-s,y+s,z-s),(x+s,y+s,z-s)],
        [(x-s,y-s,z-s),(x-s,y-s,z+s),(x-s,y+s,z+s),(x-s,y+s,z-s)],
        [(x+s,y-s,z+s),(x+s,y-s,z-s),(x+s,y+s,z-s),(x+s,y+s,z+s)],
        [(x-s,y+s,z+s),(x+s,y+s,z+s),(x+s,y+s,z-s),(x-s,y+s,z-s)],
        [(x-s,y-s,z-s),(x+s,y-s,z-s),(x+s,y-s,z+s),(x-s,y-s,z+s)],
    ]:
        for vv in face: glVertex3f(*vv)
    glEnd()


def _draw_plane_squares(center, scale, active=None):
    """Draw the three XY/XZ/YZ plane-handle squares at the base of the arrows."""
    offset = scale * 0.18
    half   = scale * 0.07
    for name, (a1, a2, _normal, color) in GIZMO_PLANES.items():
        r, g, b = (1.0, 0.9, 0.1) if name == active else color
        sq_c = math3d.vadd(center, math3d.vadd(math3d.vscale(a1, offset),
                                               math3d.vscale(a2, offset)))
        corners = [
            math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1, -half), math3d.vscale(a2, -half))),
            math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1,  half), math3d.vscale(a2, -half))),
            math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1,  half), math3d.vscale(a2,  half))),
            math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1, -half), math3d.vscale(a2,  half))),
        ]
        # filled face (dimmed)
        glColor3f(r * 0.45, g * 0.45, b * 0.45)
        glBegin(GL_QUADS)
        for c in corners: glVertex3f(*c)
        glEnd()
        # outline
        glColor3f(r, g, b)
        glLineWidth(1.5)
        glBegin(GL_LINE_LOOP)
        for c in corners: glVertex3f(*c)
        glEnd()
        glLineWidth(1.0)


def _point_in_quad_2d(px, py, pts):
    """Return True if (px, py) is inside the convex quad defined by 4 screen points."""
    crosses = []
    for i in range(4):
        x1, y1 = pts[i]; x2, y2 = pts[(i + 1) % 4]
        crosses.append((x2 - x1) * (py - y1) - (y2 - y1) * (px - x1))
    return all(c >= 0 for c in crosses) or all(c <= 0 for c in crosses)


def _polys_center(polys):
    """Centroid of polygon centers."""
    cs = [math3d.poly_center(p.vertices) for p in polys]
    n  = len(cs)
    return (sum(c[0] for c in cs)/n, sum(c[1] for c in cs)/n, sum(c[2] for c in cs)/n)


# ── Gizmo class ───────────────────────────────────────────────────────────────
class Gizmo:
    def __init__(self):
        self.mode           = 'translate'
        self.translate_snap = 0.5
        self.scale_snap     = 0.5
        self.snap_to_grid   = False

        # Shared drag state
        self.dragging_axis        = None
        self.drag_start_verts     = None
        self.drag_start_verts_all = {}   # {Polygon: list[verts]}
        self.drag_axis_t0         = 0.0

        # Rotation drag state
        self.drag_angle0  = 0.0
        self.drag_plane_u = None
        self.drag_plane_v = None
        self.drag_center  = None

        # Scale drag state
        self.drag_hw0  = 0.0
        self.drag_hh0  = 0.0
        self.drag_wa   = None
        self.drag_ha   = None
        self.drag_poly = None   # Reference polygon for scale

        # Edge drag state: {(Polygon, vi): start_vertex}
        self.drag_start_edge_verts = {}
        # Vertex drag state: {(Polygon, vi): start_vertex}
        self.drag_start_vertex_verts = {}

        # "Before drag" snapshot for history: {Polygon: list[vertex]}
        self.drag_before_snapshot: dict = {}

        # Glued vertices: {(Polygon, vi): start_pos} for co-located verts not in primary drag
        self.drag_start_glued_verts: dict = {}

        # Plane drag state
        self.drag_plane_hit0   = None   # initial ray/plane intersection point
        self.drag_plane_normal = None   # normal of the drag plane

    # ── Mode ──────────────────────────────────────────────────────────────────
    def cycle_mode(self, multi_selected):
        if multi_selected:
            self.mode = 'rotate' if self.mode == 'translate' else 'translate'
        else:
            self.mode = GIZMO_MODES[(GIZMO_MODES.index(self.mode) + 1) % 3]
        self.dragging_axis = None

    def stop_drag(self):
        self.dragging_axis           = None
        self.drag_start_verts        = None
        self.drag_start_edge_verts   = {}
        self.drag_start_vertex_verts = {}
        self.drag_poly               = None
        self.drag_before_snapshot    = {}
        self.drag_start_glued_verts  = {}
        self.drag_plane_hit0         = None
        self.drag_plane_normal       = None

    def finish_drag(self, history, state) -> None:
        """Finalizes the drag and records the transform in history."""
        if self.dragging_axis is not None and self.drag_before_snapshot:
            after   = {p: list(p.vertices) for p in self.drag_before_snapshot}
            changed = any(after[p] != self.drag_before_snapshot[p] for p in after)
            if changed:
                from editor.history import TransformCommand
                history.record(TransformCommand(state,
                                                dict(self.drag_before_snapshot),
                                                after))
        self.stop_drag()

    # ── Drawing ───────────────────────────────────────────────────────────────
    def draw(self, state, camera):
        if state.selected_edges:
            self._draw_translate(self._snap_pos(self._edge_center(state)), camera, self.dragging_axis)
            return
        if state.selected_vertices:
            self._draw_translate(self._snap_pos(self._vertex_center(state)), camera, self.dragging_axis)
            return
        polys = state.selected_polygons
        if not polys:
            return
        if len(polys) > 1:
            center = self._snap_pos(_polys_center(polys))
            if self.mode == 'rotate':
                self._draw_rotate(center, camera, self.dragging_axis)
            else:
                self._draw_translate(center, camera, self.dragging_axis)
        else:
            q = polys[-1].vertices
            c = self._snap_pos(math3d.poly_center(q))
            if self.mode == 'translate':
                self._draw_translate(c, camera, self.dragging_axis)
            elif self.mode == 'rotate':
                self._draw_rotate(c, camera, self.dragging_axis)
            else:
                self._draw_scale(q, camera, self.dragging_axis)

    def _draw_translate(self, center, camera, active=None):
        scale = self._gizmo_scale(center, camera)
        glDisable(GL_DEPTH_TEST)
        _draw_plane_squares(center, scale, active)
        for name, (axis_dir, color) in GIZMO_AXES.items():
            _draw_arrow_3d(center, math3d.vadd(center, math3d.vscale(axis_dir, scale)),
                           color, name == active)
        glEnable(GL_DEPTH_TEST)

    def _draw_rotate(self, center, camera, active=None):
        scale = self._gizmo_scale(center, camera);  N = 48
        glDisable(GL_DEPTH_TEST)
        for name, (axis_dir, color) in GIZMO_AXES.items():
            r, g, b = (1.0, 0.9, 0.1) if name == active else color
            glColor3f(r, g, b);  glLineWidth(2.5 if name == active else 2.0)
            u, v = math3d.perp_basis(axis_dir)
            glBegin(GL_LINE_LOOP)
            for i in range(N):
                a = 2*math.pi*i/N
                p = math3d.vadd(center, math3d.vadd(math3d.vscale(u, scale*math.cos(a)),
                                                    math3d.vscale(v, scale*math.sin(a))))
                glVertex3f(*p)
            glEnd()
        glLineWidth(1.0);  glEnable(GL_DEPTH_TEST)

    def _draw_scale(self, quad, camera, active=None):
        if len(quad) != 4:
            self._draw_translate(math3d.poly_center(quad), camera, active)
            return
        center = math3d.poly_center(quad)
        bs = self._gizmo_scale(center, camera) * 0.1
        handles = self._scale_handle_positions(quad, camera)
        glDisable(GL_DEPTH_TEST);  glLineWidth(2.0)
        for name, pos in handles.items():
            r, g, b = (1.0, 0.9, 0.1) if name == active else SCALE_COLORS[name]
            glColor3f(r, g, b)
            glBegin(GL_LINES); glVertex3f(*center); glVertex3f(*pos); glEnd()
            _draw_box_3d(pos, bs * (1.4 if name == active else 1.0), r, g, b)
        glLineWidth(1.0);  glEnable(GL_DEPTH_TEST)

    # ── Picking ──────────────────────────────────────────────────────────────
    def pick_translate_axis(self, mx, my, state, camera):
        if state.selected_edges:
            center = self._snap_pos(self._edge_center(state))
        elif state.selected_vertices:
            center = self._snap_pos(self._vertex_center(state))
        elif state.selected_polygons:
            center = self._snap_pos(_polys_center(state.selected_polygons))
        else:
            return None
        scale  = self._gizmo_scale(center, camera)
        # Plane squares take priority over axis arrows
        offset = scale * 0.18
        half   = scale * 0.07
        for name, (a1, a2, _normal, _color) in GIZMO_PLANES.items():
            sq_c = math3d.vadd(center, math3d.vadd(math3d.vscale(a1, offset),
                                                   math3d.vscale(a2, offset)))
            corners_3d = [
                math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1, -half), math3d.vscale(a2, -half))),
                math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1,  half), math3d.vscale(a2, -half))),
                math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1,  half), math3d.vscale(a2,  half))),
                math3d.vadd(sq_c, math3d.vadd(math3d.vscale(a1, -half), math3d.vscale(a2,  half))),
            ]
            corners_2d = [camera.world_to_screen(*c) for c in corners_3d]
            if all(c is not None for c in corners_2d):
                if _point_in_quad_2d(mx, my, corners_2d):
                    return name
        # Axis arrows
        best, best_d = None, 10.0
        for name, (axis_dir, _) in GIZMO_AXES.items():
            p0 = camera.world_to_screen(*center)
            p1 = camera.world_to_screen(*math3d.vadd(center, math3d.vscale(axis_dir, scale)))
            if p0 and p1:
                d = math3d.seg_dist_2d(mx, my, p0[0], p0[1], p1[0], p1[1])
                if d < best_d: best_d, best = d, name
        return best

    def pick_rotate_axis(self, mx, my, state, camera):
        polys = state.selected_polygons
        if not polys: return None
        center = self._snap_pos(_polys_center(polys))
        scale  = self._gizmo_scale(center, camera)
        N = 48;  best, best_d = None, 10.0
        for name, (axis_dir, _) in GIZMO_AXES.items():
            u, v = math3d.perp_basis(axis_dir);  prev = None
            for i in range(N+1):
                a = 2*math.pi*i/N
                p = math3d.vadd(center, math3d.vadd(math3d.vscale(u, scale*math.cos(a)),
                                                    math3d.vscale(v, scale*math.sin(a))))
                sp = camera.world_to_screen(*p)
                if sp and prev:
                    d = math3d.seg_dist_2d(mx, my, prev[0], prev[1], sp[0], sp[1])
                    if d < best_d: best_d, best = d, name
                prev = sp if sp else None
        return best

    def pick_scale_handle(self, mx, my, state, camera):
        polys = state.selected_polygons
        if not polys: return None
        q = polys[-1].vertices
        if len(q) != 4: return None
        handles = self._scale_handle_positions(q, camera)
        best, best_d = None, 15.0
        for name, pos in handles.items():
            sp = camera.world_to_screen(*pos)
            if sp:
                d = math.hypot(mx - sp[0], my - sp[1])
                if d < best_d: best_d, best = d, name
        return best

    # ── Drag ─────────────────────────────────────────────────────────────────
    def start_drag(self, axis_or_handle, mx, my, state, camera):
        if self.mode == 'translate':
            self._start_translate_drag(axis_or_handle, mx, my, state, camera)
        elif self.mode == 'rotate':
            self._start_rotate_drag(axis_or_handle, mx, my, state, camera)
        else:
            self._start_scale_drag(axis_or_handle, mx, my, state, camera)

    def update_drag(self, mx, my, state, camera):
        if self.mode == 'translate':
            self._update_translate_drag(mx, my, state, camera)
        elif self.mode == 'rotate':
            self._update_rotate_drag(mx, my, state, camera)
        else:
            self._update_scale_drag(mx, my, state, camera)

    # ── Move computation (axis or plane) ──────────────────────────────────────
    def _get_move(self, mx, my, center, camera):
        """Return the 3-D move vector for the current drag, handling both axis
        and plane modes.  Returns None if a plane ray cast misses."""
        if self.dragging_axis in GIZMO_PLANES:
            hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                             camera.screen_ray(mx, my),
                                             self.drag_plane_hit0,
                                             self.drag_plane_normal)
            if hit is None:
                return None
            delta = math3d.vsub(hit, self.drag_plane_hit0)
            a1, a2 = GIZMO_PLANES[self.dragging_axis][:2]
            snap = self.translate_snap
            s1 = round(math3d.dot(delta, a1) / snap) * snap
            s2 = round(math3d.dot(delta, a2) / snap) * snap
            return math3d.vadd(math3d.vscale(a1, s1), math3d.vscale(a2, s2))
        else:
            axis_dir = GIZMO_AXES[self.dragging_axis][0]
            t = math3d.ray_line_closest_s(tuple(camera.pos),
                                          camera.screen_ray(mx, my),
                                          center, axis_dir)
            return self._snap_move(t - self.drag_axis_t0, center, axis_dir)

    # ── Translate snap helper ─────────────────────────────────────────────────
    def _snap_move(self, delta, center, axis_dir):
        snap = self.translate_snap
        if self.snap_to_grid:
            proj    = math3d.dot(center, axis_dir)
            snapped = round((proj + delta) / snap) * snap
            return math3d.vscale(axis_dir, snapped - proj)
        else:
            return math3d.vscale(axis_dir, round(delta / snap) * snap)

    # ── Vertex glue helper ────────────────────────────────────────────────────
    @staticmethod
    def _find_glued_extra(state, moving_positions, exclude_poly_vi, exclude_polys):
        """Return {(poly, vi): pos} for all scene vertices co-located with any
        position in *moving_positions*, excluding already-tracked pairs/polys."""
        from editor.group import all_polygons as _all_polys
        EPS = 1e-5
        result = {}
        for poly in _all_polys(state.root_group):
            if poly in exclude_polys:
                continue
            for vi, v in enumerate(poly.vertices):
                if (poly, vi) in exclude_poly_vi:
                    continue
                vt = (v[0], v[1], v[2])
                for mp in moving_positions:
                    if (abs(vt[0]-mp[0]) < EPS and
                            abs(vt[1]-mp[1]) < EPS and
                            abs(vt[2]-mp[2]) < EPS):
                        result[(poly, vi)] = vt
                        break
        return result

    # ── Translate drag ────────────────────────────────────────────────────────
    def _start_translate_drag(self, axis, mx, my, state, camera):
        self.dragging_axis = axis
        if state.selected_edges:
            self.drag_start_edge_verts   = {}
            self.drag_start_vertex_verts = {}
            for poly, ei in state.selected_edges:
                q = poly.vertices
                self.drag_start_edge_verts[(poly, ei)]              = tuple(q[ei])
                self.drag_start_edge_verts[(poly, (ei+1) % len(q))] = tuple(q[(ei+1) % len(q)])
            self.drag_start_verts_all = {}
            center = self._snap_pos(self._edge_center(state))
            self.drag_before_snapshot = {}
            for poly, _ in self.drag_start_edge_verts:
                if poly not in self.drag_before_snapshot:
                    self.drag_before_snapshot[poly] = list(poly.vertices)
        elif state.selected_vertices:
            self.drag_start_edge_verts   = {}
            self.drag_start_vertex_verts = {}
            for poly, vi in state.selected_vertices:
                q = poly.vertices
                if vi < len(q):
                    self.drag_start_vertex_verts[(poly, vi)] = tuple(q[vi])
            self.drag_start_verts_all = {}
            center = self._snap_pos(self._vertex_center(state))
            self.drag_before_snapshot = {}
            for poly, _ in self.drag_start_vertex_verts:
                if poly not in self.drag_before_snapshot:
                    self.drag_before_snapshot[poly] = list(poly.vertices)
        else:
            self.drag_start_edge_verts   = {}
            self.drag_start_vertex_verts = {}
            polys = state.selected_polygons
            self.drag_start_verts_all = {p: list(p.vertices) for p in polys}
            cs = [math3d.poly_center(v) for v in self.drag_start_verts_all.values()]
            raw_center = (sum(c[0] for c in cs)/len(cs), sum(c[1] for c in cs)/len(cs),
                          sum(c[2] for c in cs)/len(cs)) if cs else (0.0, 0.0, 0.0)
            center = self._snap_pos(raw_center)
            self.drag_before_snapshot = {p: list(vs)
                                         for p, vs in self.drag_start_verts_all.items()}
        # ── Vertex glue ───────────────────────────────────────────────────────
        self.drag_start_glued_verts = {}
        if state.vertex_glue:
            if self.drag_start_vertex_verts:
                moving = list(self.drag_start_vertex_verts.values())
                excl_vi = set(self.drag_start_vertex_verts.keys())
                glued = self._find_glued_extra(state, moving, excl_vi, set())
            elif self.drag_start_edge_verts:
                moving = list(self.drag_start_edge_verts.values())
                excl_vi = set(self.drag_start_edge_verts.keys())
                glued = self._find_glued_extra(state, moving, excl_vi, set())
            else:
                moving = [v for vs in self.drag_start_verts_all.values() for v in vs]
                glued = self._find_glued_extra(
                    state, moving, set(), set(self.drag_start_verts_all.keys()))
            self.drag_start_glued_verts = glued
            for poly in {p for p, _ in glued}:
                if poly not in self.drag_before_snapshot:
                    self.drag_before_snapshot[poly] = list(poly.vertices)
        if axis in GIZMO_PLANES:
            _, _, normal, _ = GIZMO_PLANES[axis]
            hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                             camera.screen_ray(mx, my),
                                             center, normal)
            self.drag_plane_hit0   = hit if hit is not None else center
            self.drag_plane_normal = normal
        else:
            self.drag_axis_t0 = math3d.ray_line_closest_s(
                tuple(camera.pos), camera.screen_ray(mx, my),
                center, GIZMO_AXES[axis][0])

    def _update_translate_drag(self, mx, my, state, camera):
        if self.dragging_axis is None: return
        move = None
        if self.drag_start_vertex_verts:
            verts  = list(self.drag_start_vertex_verts.values())
            n      = len(verts)
            center = (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                      sum(v[2] for v in verts)/n)
            move = self._get_move(mx, my, center, camera)
            if move is None: return
            poly_updates = {}
            for (poly, vi), start_v in self.drag_start_vertex_verts.items():
                poly_updates.setdefault(poly, {})[vi] = math3d.vadd(start_v, move)
            for poly, vi_verts in poly_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_verts.items():
                    if vi < len(q):
                        q[vi] = new_v
                poly.vertices = q
            state.notify_polygon_transformed(list(poly_updates.keys()))
        elif self.drag_start_edge_verts:
            verts  = list(self.drag_start_edge_verts.values())
            n      = len(verts)
            center = (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                      sum(v[2] for v in verts)/n)
            move = self._get_move(mx, my, center, camera)
            if move is None: return
            poly_updates = {}
            for (poly, vi), start_v in self.drag_start_edge_verts.items():
                poly_updates.setdefault(poly, {})[vi] = math3d.vadd(start_v, move)
            for poly, vi_verts in poly_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_verts.items():
                    q[vi] = new_v
                poly.vertices = q
            state.notify_polygon_transformed(list(poly_updates.keys()))
        elif self.drag_start_verts_all:
            cs = [math3d.poly_center(v) for v in self.drag_start_verts_all.values()]
            center = (sum(c[0] for c in cs)/len(cs), sum(c[1] for c in cs)/len(cs),
                      sum(c[2] for c in cs)/len(cs))
            move = self._get_move(mx, my, center, camera)
            if move is None: return
            for poly, start_verts in self.drag_start_verts_all.items():
                poly.vertices = [math3d.vadd(v, move) for v in start_verts]
            state.notify_polygon_transformed(list(self.drag_start_verts_all.keys()))
        # ── Apply glued vertices ──────────────────────────────────────────────
        if move is not None and self.drag_start_glued_verts:
            glue_updates = {}
            for (poly, vi), start_v in self.drag_start_glued_verts.items():
                glue_updates.setdefault(poly, {})[vi] = math3d.vadd(start_v, move)
            for poly, vi_verts in glue_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_verts.items():
                    if vi < len(q):
                        q[vi] = new_v
                poly.vertices = q
            state.notify_polygon_transformed(list(glue_updates.keys()))

    # ── Rotate drag ───────────────────────────────────────────────────────────
    def _start_rotate_drag(self, axis, mx, my, state, camera):
        self.dragging_axis        = axis
        polys = state.selected_polygons
        self.drag_start_verts_all = {p: list(p.vertices) for p in polys}
        self.drag_before_snapshot = {p: list(vs)
                                     for p, vs in self.drag_start_verts_all.items()}
        self.drag_start_glued_verts = {}
        if state.vertex_glue:
            moving = [v for vs in self.drag_start_verts_all.values() for v in vs]
            glued  = self._find_glued_extra(
                state, moving, set(), set(self.drag_start_verts_all.keys()))
            self.drag_start_glued_verts = glued
            for poly in {p for p, _ in glued}:
                if poly not in self.drag_before_snapshot:
                    self.drag_before_snapshot[poly] = list(poly.vertices)
        self.drag_center  = self._snap_pos(_polys_center(polys))
        axis_dir          = GIZMO_AXES[axis][0]
        self.drag_plane_u, self.drag_plane_v = math3d.perp_basis(axis_dir)
        hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                         camera.screen_ray(mx, my),
                                         self.drag_center, axis_dir)
        self.drag_angle0 = (math3d.angle_on_plane(hit, self.drag_center,
                                                   self.drag_plane_u, self.drag_plane_v)
                            if hit else 0.0)

    def _update_rotate_drag(self, mx, my, state, camera):
        if self.dragging_axis is None or not self.drag_start_verts_all: return
        axis_dir = GIZMO_AXES[self.dragging_axis][0]
        hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                         camera.screen_ray(mx, my),
                                         self.drag_center, axis_dir)
        if hit is None: return
        angle = math3d.angle_on_plane(hit, self.drag_center, self.drag_plane_u, self.drag_plane_v)
        step  = math.radians(45)
        delta = round((angle - self.drag_angle0) / step) * step
        for poly, start_verts in self.drag_start_verts_all.items():
            poly.vertices = [math3d.rotate_point(v, self.drag_center, axis_dir, delta)
                             for v in start_verts]
        state.notify_polygon_transformed(list(self.drag_start_verts_all.keys()))
        if self.drag_start_glued_verts:
            glue_updates = {}
            for (poly, vi), start_v in self.drag_start_glued_verts.items():
                glue_updates.setdefault(poly, {})[vi] = math3d.rotate_point(
                    start_v, self.drag_center, axis_dir, delta)
            for poly, vi_verts in glue_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_verts.items():
                    q[vi] = new_v
                poly.vertices = q
            state.notify_polygon_transformed(list(glue_updates.keys()))

    # ── Scale drag ────────────────────────────────────────────────────────────
    def _start_scale_drag(self, handle, mx, my, state, camera):
        self.dragging_axis = handle
        polys = state.selected_polygons
        if not polys: return
        self.drag_poly        = polys[-1]
        self.drag_start_verts = list(self.drag_poly.vertices)
        self.drag_before_snapshot = {self.drag_poly: list(self.drag_start_verts)}
        self.drag_start_glued_verts = {}
        if state.vertex_glue:
            glued = self._find_glued_extra(
                state, self.drag_start_verts, set(), {self.drag_poly})
            self.drag_start_glued_verts = glued
            for poly in {p for p, _ in glued}:
                if poly not in self.drag_before_snapshot:
                    self.drag_before_snapshot[poly] = list(poly.vertices)
        (self.drag_center, self.drag_wa, self.drag_ha,
         self.drag_hw0, self.drag_hh0) = math3d.quad_decompose(self.drag_start_verts)
        ray_o = tuple(camera.pos);  ray_d = camera.screen_ray(mx, my)
        if handle == 'width':
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_wa)
        elif handle == 'height':
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_ha)
        else:
            diag = math3d.normalize(math3d.vadd(self.drag_wa, self.drag_ha))
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, diag)

    def _update_scale_drag(self, mx, my, state, camera):
        if self.dragging_axis is None or self.drag_start_verts is None or self.drag_poly is None: return
        ray_o = tuple(camera.pos);  ray_d = camera.screen_ray(mx, my)
        snap  = lambda x: max(self.scale_snap, round(x / self.scale_snap) * self.scale_snap)
        if self.dragging_axis == 'width':
            t = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_wa)
            new_hw = snap(self.drag_hw0 + (t - self.drag_axis_t0));  new_hh = self.drag_hh0
        elif self.dragging_axis == 'height':
            t = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_ha)
            new_hw = self.drag_hw0;  new_hh = snap(self.drag_hh0 + (t - self.drag_axis_t0))
        else:
            diag  = math3d.normalize(math3d.vadd(self.drag_wa, self.drag_ha))
            t     = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, diag)
            delta = t - self.drag_axis_t0
            new_hw = snap(self.drag_hw0 + delta);  new_hh = snap(self.drag_hh0 + delta)
        self.drag_poly.vertices = math3d.quad_compose(
            self.drag_center, self.drag_wa, self.drag_ha, new_hw, new_hh)
        state.notify_polygon_transformed([self.drag_poly])
        if self.drag_start_glued_verts:
            pos_map = {old: new for old, new in zip(self.drag_start_verts,
                                                    self.drag_poly.vertices)}
            glue_updates = {}
            for (poly, vi), start_pos in self.drag_start_glued_verts.items():
                new_pos = pos_map.get(start_pos)
                if new_pos is not None:
                    glue_updates.setdefault(poly, {})[vi] = new_pos
            for poly, vi_verts in glue_updates.items():
                q = list(poly.vertices)
                for vi, new_v in vi_verts.items():
                    q[vi] = new_v
                poly.vertices = q
            state.notify_polygon_transformed(list(glue_updates.keys()))

    # ── Internal helpers ──────────────────────────────────────────────────────
    def _vertex_center(self, state):
        verts = []
        for poly, vi in state.selected_vertices:
            q = poly.vertices
            if vi < len(q):
                verts.append(tuple(q[vi]))
        if not verts:
            return (0.0, 0.0, 0.0)
        n = len(verts)
        return (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                sum(v[2] for v in verts)/n)

    def _edge_center(self, state):
        verts = []
        for poly, ei in state.selected_edges:
            q = poly.vertices
            verts.append(tuple(q[ei]))
            verts.append(tuple(q[(ei+1) % len(q)]))
        if not verts:
            return (0.0, 0.0, 0.0)
        n = len(verts)
        return (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                sum(v[2] for v in verts)/n)

    def _snap_pos(self, pos):
        """Snap a 3-D position to the nearest translate-snap grid point."""
        s = self.translate_snap
        return (round(pos[0] / s) * s, round(pos[1] / s) * s, round(pos[2] / s) * s)

    def _gizmo_scale(self, center, camera):
        return max(0.5, math3d.vlength(math3d.vsub(tuple(camera.pos), center)) * 0.2)

    def _scale_handle_positions(self, quad, camera):
        center, wa, ha, hw, hh = math3d.quad_decompose(quad)
        off  = self._gizmo_scale(center, camera) * 0.3
        diag = math3d.normalize(math3d.vadd(wa, ha))
        return {
            'width':   math3d.vadd(center, math3d.vscale(wa, hw + off)),
            'height':  math3d.vadd(center, math3d.vscale(ha, hh + off)),
            'uniform': math3d.vadd(center, math3d.vscale(diag, math.hypot(hw, hh) + off*1.2)),
        }
