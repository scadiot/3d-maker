"""Scene class: polygons, UVs, texture, atlas, selection."""

import copy
import json
import math
import tkinter as tk
from PIL import Image, ImageTk
from OpenGL.GL import (
    glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
    glEnable, glDisable, glCullFace, glFrontFace, glBegin, glEnd,
    glColor3f, glColor4f, glTexCoord2f, glVertex3f, glLineWidth, glPointSize,
    glBlendFunc,
    GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE, GL_LINEAR,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_CULL_FACE, GL_BACK, GL_CW, GL_TRIANGLE_FAN, GL_LINE_LOOP, GL_LINES, GL_POINTS,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    GL_DEPTH_TEST,
)

from editor.constants import TEXTURE_PATH, PREVIEW_MAX_SZ
from editor import math3d
from editor.group import Group, all_polygons, iter_polygons, is_visible


# ── Flat views (compatibility with gizmo.py and the rest) ─────────────────────

class _PolygonVertices:
    """Flat view over the vertices of all scene polygons.

    Allows using scene.polygons[i] and scene.polygons[i] = v
    without modifying app.py or gizmo.py.
    """
    def __init__(self, root: Group):
        self._root = root

    def _flat(self):
        return all_polygons(self._root)

    def __len__(self):
        return len(self._flat())

    def __iter__(self):
        return (p.vertices for p in self._flat())

    def __getitem__(self, i):
        return self._flat()[i].vertices   # real mutable list → q[vi] = v works

    def __setitem__(self, i, value):
        self._flat()[i].vertices = list(value)


class _PolyUVs:
    """Flat view over the UVs of all scene polygons."""
    def __init__(self, root: Group):
        self._root = root

    def _flat(self):
        return all_polygons(self._root)

    def __len__(self):
        return len(self._flat())

    def __iter__(self):
        return (p.uvs for p in self._flat())

    def __getitem__(self, i):
        return self._flat()[i].uvs

    def __setitem__(self, i, value):
        self._flat()[i].uvs = list(value)


# ── Scene class ────────────────────────────────────────────────────────────────

class Scene:
    def __init__(self):
        self.root     = Group(name="Scene")
        self.polygons = _PolygonVertices(self.root)
        self.poly_uvs = _PolyUVs(self.root)

        self._state = None   # injected by App after StateManager creation

        self.poly_texture  = 0
        self.atlas_w       = 1
        self.atlas_h       = 1
        self.atlas_data    = {}

        self.tex_preview_win = None
        self.tex_preview_sz  = 0

    # ── Compatibility properties (delegate to StateManager) ──────────────────

    @property
    def selected_indices(self) -> set:
        """Integer indices of selected polygons (gizmo/render compatibility)."""
        if self._state is None:
            return getattr(self, '_sel_indices_fb', set())
        all_polys = all_polygons(self.root)
        flat_idx  = {id(p): i for i, p in enumerate(all_polys)}
        return {flat_idx[id(p)] for p in self._state.selected_polygons if id(p) in flat_idx}

    @selected_indices.setter
    def selected_indices(self, value: set) -> None:
        if self._state is None:
            self._sel_indices_fb = set(value)
            return
        flat = all_polygons(self.root)
        polys = [flat[i] for i in value if i < len(flat)]
        self._state.set_selection(polygons=polys)

    @property
    def selected_edges(self) -> set:
        """Selected edges as integer indices (Gizmo compatibility)."""
        if self._state is None:
            return set()
        flat     = all_polygons(self.root)
        flat_idx = {id(p): i for i, p in enumerate(flat)}
        return {(flat_idx[id(p)], ei)
                for p, ei in self._state._selected_edges
                if id(p) in flat_idx}

    @property
    def selected_vertices(self) -> set:
        """Selected vertices as integer indices (Gizmo compatibility)."""
        if self._state is None:
            return set()
        flat     = all_polygons(self.root)
        flat_idx = {id(p): i for i, p in enumerate(flat)}
        return {(flat_idx[id(p)], vi)
                for p, vi in self._state._selected_vertices
                if id(p) in flat_idx}

    @property
    def selected_idx(self) -> int:
        """Last selected polygon (value derived from selected_indices)."""
        if self._state is None:
            return getattr(self, '_sel_idx_fb', -1)
        polys = self._state.selected_polygons
        if not polys:
            return -1
        all_polys = all_polygons(self.root)
        flat_idx  = {id(p): i for i, p in enumerate(all_polys)}
        return flat_idx.get(id(polys[-1]), -1)

    @selected_idx.setter
    def selected_idx(self, value: int) -> None:
        # Derived value — ignored when the StateManager is active.
        if self._state is None:
            self._sel_idx_fb = value

    # ── Loading ───────────────────────────────────────────────────────────────
    def load_atlas(self, json_path):
        with open(json_path, encoding="utf-8") as f:
            self.atlas_data = json.load(f)

    def load_texture(self, path):
        """Loads a PNG texture into OpenGL via PIL."""
        img = Image.open(path).convert("RGBA").transpose(Image.FLIP_TOP_BOTTOM)
        w, h = img.size
        data = img.tobytes()
        tex = glGenTextures(1);  glBindTexture(GL_TEXTURE_2D, tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.poly_texture = tex
        self.atlas_w, self.atlas_h = w, h

    # ── Polygon management ────────────────────────────────────────────────────
    def _emit_scene_changed(self, change_type: str, **kw) -> None:
        """Notifies the StateManager of a structural scene change."""
        if self._state is not None:
            self._state._modified = True
            self._state._emit("scene_changed", change_type=change_type, **kw)

    def _select_new_polygon(self, new_poly):
        """Selects a newly created polygon."""
        if self._state is not None:
            self._state.set_selection(polygons=[new_poly])

    def add_polygon(self, cam_pos, cam_yaw, group=None):
        import math as _math
        yr = _math.radians(cam_yaw)
        cx = round(cam_pos[0] - _math.sin(yr)*5)
        cz = round(cam_pos[2] - _math.cos(yr)*5)
        target = group if group is not None else self.root
        new_poly = target.add_polygon(
            [(cx-1, 0.0, cz-1), (cx+1, 0.0, cz-1),
             (cx+1, 0.0, cz+1), (cx-1, 0.0, cz+1)],
            [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        self._select_new_polygon(new_poly)
        self._emit_scene_changed("polygon_added", polygon=new_poly, group=target)

    def add_triangle(self, cam_pos, cam_yaw, group=None):
        import math as _math
        yr = _math.radians(cam_yaw)
        cx = round(cam_pos[0] - _math.sin(yr)*5)
        cz = round(cam_pos[2] - _math.cos(yr)*5)
        target = group if group is not None else self.root
        new_poly = target.add_polygon(
            [(cx,   0.0, cz-1),
             (cx+1, 0.0, cz+1),
             (cx-1, 0.0, cz+1)],
            [(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)],
        )
        self._select_new_polygon(new_poly)
        self._emit_scene_changed("polygon_added", polygon=new_poly, group=target)

    def rotate_uvs(self):
        """Cyclically shifts the UVs of selected polygons (v0→v1, v1→v2, …)."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.uvs = [poly.uvs[-1]] + list(poly.uvs[:-1])

    def flip_orientation(self):
        """Reverses the orientation (normal) of selected polygons."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.vertices = list(reversed(poly.vertices))
            poly.uvs      = list(reversed(poly.uvs))

    def delete_selected(self):
        polys = self._state.selected_polygons if self._state else []

        # Remove polygons from the tree
        for poly in polys:
            if poly.group is not None:
                poly.group.remove_polygon(poly)

        # Clean up empty groups
        for child in list(self.root.children):
            if isinstance(child, Group) and not all_polygons(child):
                self.root.children.remove(child)

        if self._state is not None:
            self._state.clear_selection()
        self._emit_scene_changed("polygons_deleted")

    def duplicate_selected(self):
        polys = self._state.selected_polygons if self._state else []
        if not polys:
            return
        new_polys = [
            poly.group.add_polygon(copy.deepcopy(poly.vertices), list(poly.uvs))
            for poly in polys
        ]
        if self._state is not None:
            self._state.set_selection(polygons=new_polys)
        self._emit_scene_changed("polygon_added")

    # ── Selection ─────────────────────────────────────────────────────────────
    def selection_center(self):
        """Centroid of all selected polygons."""
        polys = self._state.selected_polygons if self._state else []
        if not polys:
            return (0.0, 0.0, 0.0)
        cs = [math3d.poly_center(p.vertices) for p in polys]
        return (sum(c[0] for c in cs)/len(cs),
                sum(c[1] for c in cs)/len(cs),
                sum(c[2] for c in cs)/len(cs))

    def pick_polygon(self, ray_o, ray_d):
        """Returns the index of the closest polygon under the ray, or -1."""
        best_t, best_i = float('inf'), -1
        for i, poly_obj in enumerate(all_polygons(self.root)):
            if not is_visible(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_i = t, i
        return best_i

    def pick_edge(self, ray_o, ray_d):
        """Returns (poly_idx, edge_idx) of the closest edge to the click, or None."""
        best_t, best_poly = float('inf'), -1
        flat = all_polygons(self.root)
        for i, poly_obj in enumerate(flat):
            if not is_visible(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_poly = t, i
        if best_poly < 0:
            return None
        hit  = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = flat[best_poly].vertices
        n    = len(poly)
        best_edge, best_dist = 0, float('inf')
        for ei in range(n):
            a  = tuple(poly[ei])
            b  = tuple(poly[(ei + 1) % n])
            cp = math3d.closest_point_on_seg(hit, a, b)
            d  = math3d.vlength(math3d.vsub(hit, cp))
            if d < best_dist:
                best_dist, best_edge = d, ei
        return (best_poly, best_edge)

    def pick_vertex(self, ray_o, ray_d):
        """Returns (poly_idx, vertex_idx) of the closest vertex to the click, or None."""
        best_t, best_poly = float('inf'), -1
        flat = all_polygons(self.root)
        for i, poly_obj in enumerate(flat):
            if not is_visible(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_poly = t, i
        if best_poly < 0:
            return None
        hit  = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = flat[best_poly].vertices
        best_vi, best_dist = 0, float('inf')
        for vi, v in enumerate(poly):
            d = math3d.vlength(math3d.vsub(hit, tuple(v)))
            if d < best_dist:
                best_dist, best_vi = d, vi
        return (best_poly, best_vi)

    # ── Groups ────────────────────────────────────────────────────────────────
    def get_group_for_polygon(self, idx):
        """Returns a Set[int] of indices of polygons in the same sub-group, or None."""
        flat = all_polygons(self.root)
        if idx < 0 or idx >= len(flat):
            return None
        poly = flat[idx]
        if poly.group is self.root:
            return None   # directly under root → not grouped
        return {i for i, p in enumerate(flat) if p.group is poly.group}

    def group_selected(self):
        """Groups the selected polygons (minimum 2) into a new sub-group."""
        polys_to_group = self._state.selected_polygons if self._state else []
        if len(polys_to_group) < 2:
            return
        new_group = self.root.add_group("Group")
        for poly in polys_to_group:
            new_group.adopt_polygon(poly)
        self._emit_scene_changed("group_added", group=new_group, parent=self.root)

    def ungroup_selected(self):
        """Dissolves the sub-groups containing selected polygons."""
        polys = self._state.selected_polygons if self._state else []
        groups_to_dissolve = {p.group for p in polys if p.group is not self.root}
        for group in groups_to_dissolve:
            parent = group.parent if group.parent is not None else self.root
            for poly in list(group.polygons):
                parent.adopt_polygon(poly)
            for child in list(group.children):
                parent.adopt_group(child)
            if group in parent.children:
                parent.remove_group(group)
        self._emit_scene_changed("group_deleted")

    # ── Save / Load ───────────────────────────────────────────────────────────
    def save_json(self, path):
        """Exports the scene to a hierarchical JSON file."""
        def serialize_group(g):
            return {
                "name":     g.name,
                "groups":   [serialize_group(c) for c in g.children],
                "polygons": [
                    {
                        "vertices": [[round(v, 6) for v in vert] for vert in p.vertices],
                        "uvs":      [[round(u, 6), round(v, 6)] for u, v in p.uvs],
                    }
                    for p in g.polygons
                ],
            }
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"root": serialize_group(self.root)}, f, indent=2, ensure_ascii=False)

    def load_json(self, path):
        """Imports a scene from a JSON file (appends to existing polygons)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if "root" in data:
            def load_group(node_data, parent):
                for p_data in node_data.get("polygons", []):
                    parent.add_polygon(
                        [tuple(v) for v in p_data["vertices"]],
                        [tuple(uv) for uv in p_data["uvs"]],
                    )
                for g_data in node_data.get("groups", []):
                    child = parent.add_group(g_data.get("name", "Group"))
                    load_group(g_data, child)
                # Backward compatibility: old format with mixed "children"
                for child_data in node_data.get("children", []):
                    if "vertices" in child_data:
                        parent.add_polygon(
                            [tuple(v) for v in child_data["vertices"]],
                            [tuple(uv) for uv in child_data["uvs"]],
                        )
                    else:
                        child = parent.add_group(child_data.get("name", "Group"))
                        load_group(child_data, child)
            load_group(data["root"], self.root)

        else:
            # Old flat format (backward compatibility)
            for p in data.get("polygons", []):
                self.root.add_polygon(
                    [tuple(v) for v in p["vertices"]],
                    [tuple(uv) for uv in p["uvs"]],
                )
            for q in data.get("quads", []):
                center = tuple(q["position"])
                hw     = q["size"][0] / 2
                hh     = q["size"][1] / 2
                if "x_axis" in q and "y_axis" in q:
                    wa = tuple(q["x_axis"])
                    ha = tuple(q["y_axis"])
                else:
                    wa, ha = math3d.perp_basis(tuple(q["orientation"]))
                self.root.add_polygon(
                    math3d.quad_compose(center, wa, ha, hw, hh),
                    [tuple(uv) for uv in q["uvs"]],
                )

        if self._state is not None:
            self._state.clear_selection()
        if self._state is not None:
            self._state.project_name = data.get("name", "Unnamed Project")  # already English
            self._state.project_path = path
        self._emit_scene_changed("polygons_added")

    # ── Edge operations ───────────────────────────────────────────────────────
    def create_polygon_from_edges(self, group=None):
        """Creates a new polygon (quad) by connecting the two selected edges."""
        if self._state is None:
            return
        edges = self._state.selected_edges
        if len(edges) != 2:
            return
        poly1, ei1 = edges[0]
        poly2, ei2 = edges[1]
        q1, q2 = poly1.vertices, poly2.vertices
        a = tuple(q1[ei1])
        b = tuple(q1[(ei1 + 1) % len(q1)])
        c = tuple(q2[(ei2 + 1) % len(q2)])
        d = tuple(q2[ei2])
        # If diagonals don't intersect → butterfly quad → swap c and d
        if not math3d.diagonals_intersect(a, b, c, d):
            c, d = d, c
        # Align orientation with source polygons
        n1 = math3d.cross(math3d.vsub(tuple(q1[1 % len(q1)]), tuple(q1[0])),
                          math3d.vsub(tuple(q1[-1]), tuple(q1[0])))
        n2 = math3d.cross(math3d.vsub(tuple(q2[1 % len(q2)]), tuple(q2[0])),
                          math3d.vsub(tuple(q2[-1]), tuple(q2[0])))
        n_ref = math3d.vadd(n1, n2)
        n_new = math3d.cross(math3d.vsub(b, a), math3d.vsub(d, a))
        if math3d.dot(n_new, n_ref) < 0:
            a, b, c, d = d, c, b, a
        # Deduplicate coincident vertices → triangle if two vertices are at the same position
        verts  = [a, b, c, d]
        unique = [verts[0]]
        for v in verts[1:]:
            if not any(math3d.vlength(math3d.vsub(v, u)) < 1e-6 for u in unique):
                unique.append(v)
        if len(unique) < 3:
            return
        quad_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        target = group if group is not None else self.root
        target.add_polygon(unique, quad_uvs[:len(unique)])
        self._emit_scene_changed("polygon_added", group=target)

    # ── Texture preview ───────────────────────────────────────────────────────
    def open_tex_preview(self, root_tk):
        if self.tex_preview_win:
            return
        img = Image.open(TEXTURE_PATH)
        sz  = min(img.width, PREVIEW_MAX_SZ)
        self.tex_preview_sz = sz
        img = img.resize((sz, sz), Image.LANCZOS)

        self.tex_preview_win = tk.Toplevel(root_tk)
        self.tex_preview_win.title("Texture Preview")
        self.tex_preview_win.resizable(False, False)
        self.tex_preview_win.protocol("WM_DELETE_WINDOW", self.close_tex_preview)

        photo = ImageTk.PhotoImage(img)
        label = tk.Label(self.tex_preview_win, image=photo)
        label._photo = photo
        label.pack()
        label.bind('<Button-1>', lambda e: (
            self.assign_uv_from_atlas_click((e.x, e.y)),
            self.close_tex_preview(),
        ))

    def close_tex_preview(self):
        if self.tex_preview_win:
            self.tex_preview_win.destroy()
            self.tex_preview_win = None

    def assign_uv_at_atlas_pixel(self, px, py):
        """Applies atlas UVs to the selected polygon from raw atlas coordinates."""
        entry = next((e for e in self.atlas_data.get("images", [])
                      if e["x"] <= px < e["x"]+e["width"]
                      and e["y"] <= py < e["y"]+e["height"]), None)
        polys = self._state.selected_polygons if self._state else []
        if entry and polys:
            u0 = entry["x"] / self.atlas_w
            u1 = (entry["x"] + entry["width"]) / self.atlas_w
            v1 = 1.0 - entry["y"] / self.atlas_h
            v0 = 1.0 - (entry["y"] + entry["height"]) / self.atlas_h
            corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            for poly in polys:
                n = len(poly.vertices)
                poly.uvs = [corners[i % 4] for i in range(n)]

    def assign_uv_from_atlas_click(self, event_pos):
        """Applies atlas UVs to the selected polygon based on a click in the preview."""
        px = int(event_pos[0] * self.atlas_w / self.tex_preview_sz)
        py = int(event_pos[1] * self.atlas_h / self.tex_preview_sz)
        self.assign_uv_at_atlas_pixel(px, py)

    # ── Rendering ─────────────────────────────────────────────────────────────
    def draw(self):
        sel_poly_ids = {id(p) for p in (self._state.selected_polygons if self._state else [])}
        sel_edges    = self._state.selected_edges if self._state else []
        sel_verts    = self._state.selected_vertices if self._state else []

        # Polygons with selected edges/vertices (for post-loop rendering)
        edge_poly_ids = {id(p) for p, _ in sel_edges}
        vert_poly_ids = {id(p) for p, _ in sel_verts}
        needed_ids    = edge_poly_ids | vert_poly_ids
        poly_verts_by_id = {}  # {id(poly_obj): vertices}

        selected_polys_verts = []  # vertices of selected polygons, deferred rendering

        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK);  glFrontFace(GL_CW)
        for poly_obj in iter_polygons(self.root):
            if not is_visible(poly_obj):
                continue
            poly = poly_obj.vertices
            uvs  = poly_obj.uvs
            sel  = (id(poly_obj) in sel_poly_ids)
            if id(poly_obj) in needed_ids:
                poly_verts_by_id[id(poly_obj)] = poly
            glEnable(GL_TEXTURE_2D);  glBindTexture(GL_TEXTURE_2D, self.poly_texture)
            glColor3f(1.0, 1.0, 1.0)
            glBegin(GL_TRIANGLE_FAN)
            for (vx, vy, vz), (u, v) in zip(poly, uvs):
                glTexCoord2f(u, v);  glVertex3f(vx, vy, vz)
            glEnd()
            glDisable(GL_TEXTURE_2D)
            if sel:
                selected_polys_verts.append(poly)
            else:
                glLineWidth(1.5)
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                if poly_obj.group is not self.root:
                    glColor4f(0.2, 0.7, 1.0, 0.5)
                else:
                    glColor4f(1.0, 0.75, 0.35, 0.5)
                glBegin(GL_LINE_LOOP)
                for vx, vy, vz in poly: glVertex3f(vx, vy, vz)
                glEnd()
                glDisable(GL_BLEND)
        glLineWidth(1.0)
        glDisable(GL_CULL_FACE)

        # Red selection borders rendered without z-buffer (always visible)
        if selected_polys_verts:
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.5)
            glColor4f(1.0, 0.15, 0.15, 1.0)
            for poly in selected_polys_verts:
                glBegin(GL_LINE_LOOP)
                for vx, vy, vz in poly: glVertex3f(vx, vy, vz)
                glEnd()
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)
        if sel_edges:
            glDisable(GL_DEPTH_TEST)
            glLineWidth(4.0)
            glColor3f(0.05, 0.05, 1.0)
            glBegin(GL_LINES)
            for poly_ref, edge_idx in sel_edges:
                p = poly_verts_by_id.get(id(poly_ref))
                if p is not None:
                    glVertex3f(*p[edge_idx])
                    glVertex3f(*p[(edge_idx + 1) % len(p)])
            glEnd()
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)
        if sel_verts:
            glDisable(GL_DEPTH_TEST)
            glPointSize(8.0)
            glColor3f(0.05, 1.0, 0.3)
            glBegin(GL_POINTS)
            for poly_ref, vert_idx in sel_verts:
                p = poly_verts_by_id.get(id(poly_ref))
                if p is not None and vert_idx < len(p):
                    glVertex3f(*p[vert_idx])
            glEnd()
            glPointSize(1.0)
            glEnable(GL_DEPTH_TEST)
