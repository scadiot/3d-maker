"""Classe Gizmo : mode, état drag, dessin et picking.

Camera et Scene sont passés en paramètre aux méthodes (pas stockés),
ce qui évite les imports circulaires.
"""

import math
from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
    glEnable, glDisable,
    GL_LINES, GL_TRIANGLE_FAN, GL_QUADS, GL_LINE_LOOP, GL_DEPTH_TEST,
)

from editor.constants import GIZMO_MODES, GIZMO_AXES, SCALE_COLORS, PANEL_WIDTH
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


# ── Classe Gizmo ──────────────────────────────────────────────────────────────
class Gizmo:
    def __init__(self):
        self.mode           = 'translate'
        self.translate_snap = 0.5
        self.scale_snap     = 0.5

        # État drag partagé
        self.dragging_axis        = None
        self.drag_start_verts     = None
        self.drag_start_verts_all = {}
        self.drag_axis_t0         = 0.0

        # État drag rotation
        self.drag_angle0  = 0.0
        self.drag_plane_u = None
        self.drag_plane_v = None
        self.drag_center  = None

        # État drag scale
        self.drag_hw0 = 0.0
        self.drag_hh0 = 0.0
        self.drag_wa  = None
        self.drag_ha  = None

        # État drag arêtes : {(qi, vi): sommet_départ}
        self.drag_start_edge_verts = {}

    # ── Mode ──────────────────────────────────────────────────────────────────
    def cycle_mode(self, multi_selected):
        if multi_selected:
            self.mode = 'rotate' if self.mode == 'translate' else 'translate'
        else:
            self.mode = GIZMO_MODES[(GIZMO_MODES.index(self.mode) + 1) % 3]
        self.dragging_axis = None

    def stop_drag(self):
        self.dragging_axis         = None
        self.drag_start_verts      = None
        self.drag_start_edge_verts = {}

    # ── Dessin ────────────────────────────────────────────────────────────────
    def draw(self, scene, camera):
        if scene.selected_edges:
            self._draw_translate(self._edge_center(scene), camera, self.dragging_axis)
            return
        if not scene.selected_indices:
            return
        if len(scene.selected_indices) > 1:
            center = scene.selection_center()
            if self.mode == 'rotate':
                self._draw_rotate(center, camera, self.dragging_axis)
            else:
                self._draw_translate(center, camera, self.dragging_axis)
        elif scene.selected_idx >= 0:
            q = scene.quads[scene.selected_idx]
            c = math3d.quad_center(q)
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
        center = math3d.quad_center(quad)
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
    def pick_translate_axis(self, mx, my, scene, camera):
        if scene.selected_edges:
            center = self._edge_center(scene)
        elif scene.selected_indices:
            center = scene.selection_center()
        else:
            return None
        scale  = self._gizmo_scale(center, camera)
        vx, vy = mx - PANEL_WIDTH, my;  best, best_d = None, 10.0
        for name, (axis_dir, _) in GIZMO_AXES.items():
            p0 = camera.world_to_screen(*center)
            p1 = camera.world_to_screen(*math3d.vadd(center, math3d.vscale(axis_dir, scale)))
            if p0 and p1:
                d = math3d.seg_dist_2d(vx, vy, p0[0], p0[1], p1[0], p1[1])
                if d < best_d: best_d, best = d, name
        return best

    def pick_rotate_axis(self, mx, my, scene, camera):
        if not scene.selected_indices: return None
        center = scene.selection_center()
        scale  = self._gizmo_scale(center, camera)
        vx, vy = mx - PANEL_WIDTH, my;  N = 48;  best, best_d = None, 10.0
        for name, (axis_dir, _) in GIZMO_AXES.items():
            u, v = math3d.perp_basis(axis_dir);  prev = None
            for i in range(N+1):
                a = 2*math.pi*i/N
                p = math3d.vadd(center, math3d.vadd(math3d.vscale(u, scale*math.cos(a)),
                                                    math3d.vscale(v, scale*math.sin(a))))
                sp = camera.world_to_screen(*p)
                if sp and prev:
                    d = math3d.seg_dist_2d(vx, vy, prev[0], prev[1], sp[0], sp[1])
                    if d < best_d: best_d, best = d, name
                prev = sp if sp else None
        return best

    def pick_scale_handle(self, mx, my, scene, camera):
        if scene.selected_idx < 0: return None
        handles = self._scale_handle_positions(scene.quads[scene.selected_idx], camera)
        vx, vy  = mx - PANEL_WIDTH, my;  best, best_d = None, 15.0
        for name, pos in handles.items():
            sp = camera.world_to_screen(*pos)
            if sp:
                d = math.hypot(vx - sp[0], vy - sp[1])
                if d < best_d: best_d, best = d, name
        return best

    # ── Drag ──────────────────────────────────────────────────────────────────
    def start_drag(self, axis_or_handle, mx, my, scene, camera):
        if self.mode == 'translate':
            self._start_translate_drag(axis_or_handle, mx, my, scene, camera)
        elif self.mode == 'rotate':
            self._start_rotate_drag(axis_or_handle, mx, my, scene, camera)
        else:
            self._start_scale_drag(axis_or_handle, mx, my, scene, camera)

    def update_drag(self, mx, my, scene, camera):
        if self.mode == 'translate':
            self._update_translate_drag(mx, my, scene, camera)
        elif self.mode == 'rotate':
            self._update_rotate_drag(mx, my, scene, camera)
        else:
            self._update_scale_drag(mx, my, scene, camera)

    # ── Drag translation ──────────────────────────────────────────────────────
    def _start_translate_drag(self, axis, mx, my, scene, camera):
        self.dragging_axis = axis
        if scene.selected_edges:
            self.drag_start_edge_verts = {}
            for qi, ei in scene.selected_edges:
                if qi < len(scene.quads):
                    q = scene.quads[qi]
                    self.drag_start_edge_verts[(qi, ei)]          = tuple(q[ei])
                    self.drag_start_edge_verts[(qi, (ei+1) % 4)] = tuple(q[(ei+1) % 4])
            self.drag_start_verts_all = {}
            center = self._edge_center(scene)
        else:
            self.drag_start_edge_verts = {}
            self.drag_start_verts_all  = {i: list(scene.quads[i])
                                          for i in scene.selected_indices if i < len(scene.quads)}
            if not self.drag_start_verts_all and scene.selected_idx >= 0:
                self.drag_start_verts_all = {scene.selected_idx: list(scene.quads[scene.selected_idx])}
            self.drag_start_verts = self.drag_start_verts_all.get(scene.selected_idx)
            cs = [math3d.quad_center(v) for v in self.drag_start_verts_all.values()]
            center = (sum(c[0] for c in cs)/len(cs), sum(c[1] for c in cs)/len(cs),
                      sum(c[2] for c in cs)/len(cs)) if cs else (0.0, 0.0, 0.0)
        self.drag_axis_t0 = math3d.ray_line_closest_s(
            tuple(camera.pos), camera.screen_ray(mx - PANEL_WIDTH, my),
            center, GIZMO_AXES[axis][0])

    def _update_translate_drag(self, mx, my, scene, camera):
        if self.dragging_axis is None: return
        axis_dir = GIZMO_AXES[self.dragging_axis][0]
        if self.drag_start_edge_verts:
            verts  = list(self.drag_start_edge_verts.values())
            n      = len(verts)
            center = (sum(v[0] for v in verts)/n, sum(v[1] for v in verts)/n,
                      sum(v[2] for v in verts)/n)
            t    = math3d.ray_line_closest_s(tuple(camera.pos),
                                             camera.screen_ray(mx - PANEL_WIDTH, my),
                                             center, axis_dir)
            move = math3d.vscale(axis_dir,
                                 round((t - self.drag_axis_t0) / self.translate_snap) * self.translate_snap)
            quad_updates = {}
            for (qi, vi), start_v in self.drag_start_edge_verts.items():
                quad_updates.setdefault(qi, {})[vi] = math3d.vadd(start_v, move)
            for qi, vi_verts in quad_updates.items():
                if qi < len(scene.quads):
                    q = list(scene.quads[qi])
                    for vi, new_v in vi_verts.items():
                        q[vi] = new_v
                    scene.quads[qi] = q
        elif self.drag_start_verts_all:
            cs = [math3d.quad_center(v) for v in self.drag_start_verts_all.values()]
            center = (sum(c[0] for c in cs)/len(cs), sum(c[1] for c in cs)/len(cs),
                      sum(c[2] for c in cs)/len(cs))
            t    = math3d.ray_line_closest_s(tuple(camera.pos),
                                             camera.screen_ray(mx - PANEL_WIDTH, my),
                                             center, axis_dir)
            move = math3d.vscale(axis_dir,
                                 round((t - self.drag_axis_t0) / self.translate_snap) * self.translate_snap)
            for i, start_verts in self.drag_start_verts_all.items():
                if i < len(scene.quads):
                    scene.quads[i] = [math3d.vadd(v, move) for v in start_verts]

    # ── Drag rotation ─────────────────────────────────────────────────────────
    def _start_rotate_drag(self, axis, mx, my, scene, camera):
        self.dragging_axis        = axis
        self.drag_start_verts_all = {i: list(scene.quads[i])
                                     for i in scene.selected_indices if i < len(scene.quads)}
        self.drag_start_verts = self.drag_start_verts_all.get(scene.selected_idx)
        self.drag_center  = scene.selection_center()
        axis_dir          = GIZMO_AXES[axis][0]
        self.drag_plane_u, self.drag_plane_v = math3d.perp_basis(axis_dir)
        hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                         camera.screen_ray(mx - PANEL_WIDTH, my),
                                         self.drag_center, axis_dir)
        self.drag_angle0 = (math3d.angle_on_plane(hit, self.drag_center,
                                                   self.drag_plane_u, self.drag_plane_v)
                            if hit else 0.0)

    def _update_rotate_drag(self, mx, my, scene, camera):
        if self.dragging_axis is None or not self.drag_start_verts_all: return
        axis_dir = GIZMO_AXES[self.dragging_axis][0]
        hit = math3d.ray_plane_intersect(tuple(camera.pos),
                                         camera.screen_ray(mx - PANEL_WIDTH, my),
                                         self.drag_center, axis_dir)
        if hit is None: return
        angle = math3d.angle_on_plane(hit, self.drag_center, self.drag_plane_u, self.drag_plane_v)
        step  = math.radians(45)
        delta = round((angle - self.drag_angle0) / step) * step
        for i, start_verts in self.drag_start_verts_all.items():
            if i < len(scene.quads):
                scene.quads[i] = [math3d.rotate_point(v, self.drag_center, axis_dir, delta)
                                   for v in start_verts]

    # ── Drag scale ────────────────────────────────────────────────────────────
    def _start_scale_drag(self, handle, mx, my, scene, camera):
        self.dragging_axis    = handle
        self.drag_start_verts = list(scene.quads[scene.selected_idx])
        (self.drag_center, self.drag_wa, self.drag_ha,
         self.drag_hw0, self.drag_hh0) = math3d.quad_decompose(self.drag_start_verts)
        ray_o = tuple(camera.pos);  ray_d = camera.screen_ray(mx - PANEL_WIDTH, my)
        if handle == 'width':
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_wa)
        elif handle == 'height':
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, self.drag_ha)
        else:
            diag = math3d.normalize(math3d.vadd(self.drag_wa, self.drag_ha))
            self.drag_axis_t0 = math3d.ray_line_closest_s(ray_o, ray_d, self.drag_center, diag)

    def _update_scale_drag(self, mx, my, scene, camera):
        if self.dragging_axis is None or self.drag_start_verts is None: return
        ray_o = tuple(camera.pos);  ray_d = camera.screen_ray(mx - PANEL_WIDTH, my)
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
        scene.quads[scene.selected_idx] = math3d.quad_compose(
            self.drag_center, self.drag_wa, self.drag_ha, new_hw, new_hh)

    # ── Helpers internes ──────────────────────────────────────────────────────
    def _edge_center(self, scene):
        verts = []
        for qi, ei in scene.selected_edges:
            if qi < len(scene.quads):
                q = scene.quads[qi]
                verts.append(tuple(q[ei]))
                verts.append(tuple(q[(ei+1) % 4]))
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
