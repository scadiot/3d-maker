"""Classe Gizmo : mode, état drag, dessin et picking.

Camera et StateManager sont passés en paramètre aux méthodes (pas stockés),
ce qui évite les imports circulaires.
"""

import math
from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
    glEnable, glDisable,
    GL_LINES, GL_TRIANGLE_FAN, GL_QUADS, GL_LINE_LOOP, GL_DEPTH_TEST,
)

from editor.constants import GIZMO_MODES, GIZMO_AXES, SCALE_COLORS
from editor import math3d


# ── Helpers de dessin (privés au module) ──────────────────────────────────────
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


def _polys_center(polys):
    """Barycentre des centres de polygones."""
    cs = [math3d.poly_center(p.vertices) for p in polys]
    n  = len(cs)
    return (sum(c[0] for c in cs)/n, sum(c[1] for c in cs)/n, sum(c[2] for c in cs)/n)


# ── Classe Gizmo ──────────────────────────────────────────────────────────────
class Gizmo:
    def __init__(self):
        self.mode           = 'translate'
        self.translate_snap = 0.5
        self.scale_snap     = 0.5

        # État drag partagé
        self.dragging_axis        = None
        self.drag_start_verts     = None
        self.drag_start_verts_all = {}   # {Polygon: list[verts]}
        self.drag_axis_t0         = 0.0

        # État drag rotation
        self.drag_angle0  = 0.0
        self.drag_plane_u = None
        self.drag_plane_v = None
        self.drag_center  = None

        # État drag scale
        self.drag_hw0  = 0.0
        self.drag_hh0  = 0.0
        self.drag_wa   = None
        self.drag_ha   = None
        self.drag_poly = None   # Polygon de référence pour le scale

        # État drag arêtes : {(Polygon, vi): sommet_départ}
        self.drag_start_edge_verts = {}
        # État drag vertices : {(Polygon, vi): sommet_départ}
        self.drag_start_vertex_verts = {}

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

    # ── Dessin ────────────────────────────────────────────────────────────────
    def draw(self, state, camera):
        if state.selected_edges:
            self._draw_translate(self._edge_center(state), camera, self.dragging_axis)
            return
        if state.selected_vertices:
            self._draw_translate(self._vertex_center(state), camera, self.dragging_axis)
            return
        polys = state.selected_polygons
        if not polys:
            return
        if len(polys) > 1:
            center = _polys_center(polys)
            if self.mode == 'rotate':
                self._draw_rotate(center, camera, self.dragging_axis)
            else:
                self._draw_translate(center, camera, self.dragging_axis)
        else:
            q = polys[-1].vertices
            c = math3d.poly_center(q)
            if self.mode == 'translate':
                self._draw_translate(c, camera, self.dragging_axis)
            elif self.mode == 'rotate':
                self._draw_rotate(c, camera, self.dragging_axis)
            else:
                self._draw_scale(q, camera, self.dragging_axis)

    def _draw_translate(self, center, camera, active=None):
        scale = self._gizmo_scale(center, camera)
        glDisable(GL_DEPTH_TEST)
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

    # ── Picking ───────────────────────────────────────────────────────────────
    def pick_translate_axis(self, mx, my, state, camera):
        if state.selected_edges:
            center = self._edge_center(state)
        elif state.selected_vertices:
            center = self._vertex_center(state)
        elif state.selected_polygons:
            center = _polys_center(state.selected_polygons)
        else:
            return None
        scale  = self._gizmo_scale(center, camera)
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
        center = _polys_center(polys)
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

    # ── Drag ──────────────────────────────────────────────────────────────────
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

    # ── Drag translation ──────────────────────────────────────────────────────
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
            center = self._edge_center(state)
        elif state.selected_vertices:
            self.drag_start_edge_verts   = {}
            self.drag_start_vertex_verts = {}
            for poly, vi in state.selected_vertices:
                q = poly.vertices
                if vi < len(q):
                    self.drag_start_vertex_verts[(poly, vi)] = tuple(q[vi])
            self.drag_start_verts_all = {}
            center = self._vertex_center(state)
        else:
            self.drag_start_edge_verts   = {}
            self.drag_start_vertex_verts = {}
            polys = state.selected_polygons
            self.drag_start_verts_all = {p: list(p.vertices) for p in polys}
            cs = [math3d.poly_center(v) for v in self.drag_start_verts_all.values()]
            center = (sum(c[0] for c in cs)/len(cs), sum(c[1] for c in cs)/len(cs),
                      sum(c[2] for c in cs)/len(cs)) if cs else (0.0, 0.0, 0.0)
        self.drag_axis_t0 = math3d.ray_line_closest_s(
            tuple(camera.pos), camera.screen_ray(mx, my),
            center, GIZMO_AXES[axis][0])

    def _update_translate_drag(self, mx, my, state, camera):
        if self.dragging_axis is None: return
        axis_dir = GIZMO_AXES[self.dragging_axis][0]
        if self.drag_start_vertex_verts:
            verts  = list(self.drag_start_vertex_verts.values())
            n      = len(verts)
            center = (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                      sum(v[2] for v in verts)/n)
            t    = math3d.ray_line_closest_s(tuple(camera.pos),
                                             camera.screen_ray(mx, my),
                                             center, axis_dir)
            move = math3d.vscale(axis_dir,
                                 round((t - self.drag_axis_t0) / self.translate_snap) * self.translate_snap)
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
            t    = math3d.ray_line_closest_s(tuple(camera.pos),
                                             camera.screen_ray(mx, my),
                                             center, axis_dir)
            move = math3d.vscale(axis_dir,
                                 round((t - self.drag_axis_t0) / self.translate_snap) * self.translate_snap)
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
            t    = math3d.ray_line_closest_s(tuple(camera.pos),
                                             camera.screen_ray(mx, my),
                                             center, axis_dir)
            move = math3d.vscale(axis_dir,
                                 round((t - self.drag_axis_t0) / self.translate_snap) * self.translate_snap)
            for poly, start_verts in self.drag_start_verts_all.items():
                poly.vertices = [math3d.vadd(v, move) for v in start_verts]
            state.notify_polygon_transformed(list(self.drag_start_verts_all.keys()))

    # ── Drag rotation ─────────────────────────────────────────────────────────
    def _start_rotate_drag(self, axis, mx, my, state, camera):
        self.dragging_axis        = axis
        polys = state.selected_polygons
        self.drag_start_verts_all = {p: list(p.vertices) for p in polys}
        self.drag_center  = _polys_center(polys)
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

    # ── Drag scale ────────────────────────────────────────────────────────────
    def _start_scale_drag(self, handle, mx, my, state, camera):
        self.dragging_axis = handle
        polys = state.selected_polygons
        if not polys: return
        self.drag_poly        = polys[-1]
        self.drag_start_verts = list(self.drag_poly.vertices)
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

    # ── Helpers internes ──────────────────────────────────────────────────────
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
