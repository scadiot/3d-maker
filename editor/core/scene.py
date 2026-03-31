"""Scene class: polygons, UVs, texture, atlas, selection."""

import copy
import ctypes
import json
import math
import numpy as np
from PIL import Image
from OpenGL.GL import (
    glGenTextures, glDeleteTextures, glBindTexture, glTexImage2D, glTexParameteri,
    glEnable, glDisable, glCullFace, glFrontFace, glLineWidth, glPointSize,
    glColor3f, glColor4f, glBlendFunc,
    glGenBuffers, glDeleteBuffers, glBindBuffer, glBufferData,
    glEnableClientState, glDisableClientState,
    glVertexPointer, glNormalPointer, glTexCoordPointer,
    glDrawArrays,
    glLightfv, glColorMaterial,
    GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE, GL_LINEAR,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_CULL_FACE, GL_BACK, GL_CW,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    GL_DEPTH_TEST,
    GL_ARRAY_BUFFER, GL_DYNAMIC_DRAW, GL_FLOAT,
    GL_VERTEX_ARRAY, GL_NORMAL_ARRAY, GL_TEXTURE_COORD_ARRAY,
    GL_TRIANGLES, GL_LINES, GL_POINTS,
    GL_LIGHTING, GL_LIGHT0, GL_COLOR_MATERIAL,
    GL_AMBIENT, GL_DIFFUSE, GL_POSITION,
    GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE,
)

from editor.utils.texture_atlas import TextureAtlas
from editor.utils import math3d
from editor.utils import serializer
from editor.core.group import Group, all_polygons, iter_polygons, is_visible, is_locked, iter_ancestors


# Directional light — world-space direction (w=0), set after camera transform
# so it stays fixed in the world regardless of camera orientation.
_LIGHT_AMBIENT  = (0.30, 0.30, 0.30, 1.0)
_LIGHT_DIFFUSE  = (0.85, 0.85, 0.85, 1.0)
_LIGHT_DIR      = (0.50, 1.00, 0.75, 0.0)   # upper-front-right, w=0 → directional


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
        self.poly_textures: dict = {}   # atlas_id -> GL texture id
        self.atlas_w       = 1
        self.atlas_h       = 1
        self.atlas_data    = {}

        # Atlases queued for GL upload on the next draw() (context-safe)
        self._pending_atlases: list = []

        # ── VBO state ──────────────────────────────────────────────────────────
        self._vbo_dirty    = True   # rebuild VBOs on next draw
        self._subscribed   = False  # lazy subscription to state events

        # Face VBOs: atlas_id -> (vbo_id, vertex_count)  (fan-triangulated)
        self._face_vbos: dict = {}

        # Outline VBOs: (vbo_id, vertex_count) or None
        self._vbo_root   = None   # orange — root-level polygons
        self._vbo_group  = None   # blue   — grouped polygons
        self._vbo_sel    = None   # red    — selected polygon outlines
        self._vbo_locked = None   # red    — polygons in a selected locked group

        # Selection-detail VBOs
        self._vbo_sel_edges = None   # thick blue
        self._vbo_sel_verts = None   # green points

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
    def load_atlas(self, atlas: TextureAtlas) -> None:
        """Queues a TextureAtlas for GL upload on the next draw() call."""
        self._pending_atlases.append(atlas)
        self._vbo_dirty = True

    def _upload_atlas(self, atlas: TextureAtlas) -> None:
        """Actually uploads a TextureAtlas to OpenGL (must be called with an active GL context)."""
        if atlas.id in self.poly_textures:
            glDeleteTextures(1, [self.poly_textures[atlas.id]])
        self.load_texture(atlas.image_path)
        self.poly_textures[atlas.id] = self.poly_texture
        data = atlas.atlas_data
        if isinstance(data, str) and data:
            with open(data, encoding="utf-8") as f:
                data = json.load(f)
        self.atlas_data = data if data is not None else {}

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

    def rotate_vertices(self):
        """Cyclically shifts the vertices and UVs of selected polygons (v0→v1, v1→v2, …)."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.vertices = [poly.vertices[-1]] + list(poly.vertices[:-1])
        self._emit_scene_changed("polygon_transformed")

    def flip_orientation(self):
        """Reverses the orientation (normal) of selected polygons."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.vertices = list(reversed(poly.vertices))
            poly.uvs      = list(reversed(poly.uvs))
        self._emit_scene_changed("polygon_transformed")

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
        new_polys = []
        for poly in polys:
            new_poly = poly.group.add_polygon(copy.deepcopy(poly.vertices), list(poly.uvs))
            new_poly.texture_atlas_id = poly.texture_atlas_id
            new_polys.append(new_poly)
        if self._state is not None:
            self._state.set_selection(polygons=new_polys)
        self._emit_scene_changed("polygon_added")

    def duplicate_selected_groups(self):
        """Duplicates selected groups and returns the new groups."""
        groups = self._state.selected_groups if self._state else []
        if not groups:
            return []
        # Skip groups whose ancestor is also selected (avoid double-duplication)
        group_ids = {id(g) for g in groups}
        def has_selected_ancestor(g):
            node = g.parent
            while node is not None:
                if id(node) in group_ids:
                    return True
                node = node.parent
            return False
        top_groups = [g for g in groups if not has_selected_ancestor(g)]
        new_groups = []
        for group in top_groups:
            clone = self._clone_group(group, group.parent)
            new_groups.append(clone)
        if self._state is not None:
            self._state.selected_groups = new_groups
        self._emit_scene_changed("group_added")
        return new_groups

    def _clone_group(self, group, parent):
        """Recursively clones a group into the given parent."""
        clone = parent.add_group(group.name)
        clone.hidden = group.hidden
        clone.locked = group.locked
        for poly in group.polygons:
            new_poly = clone.add_polygon(copy.deepcopy(poly.vertices), list(poly.uvs))
            new_poly.texture_atlas_id = poly.texture_atlas_id
        for child in group.children:
            self._clone_group(child, clone)
        return clone

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
            if not is_visible(poly_obj) or is_locked(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_i = t, i
        return best_i

    def pick_locked_group(self, ray_o, ray_d):
        """Returns the topmost locked ancestor Group of the closest locked polygon under the ray, or None."""
        best_t, best_poly = float('inf'), None
        for poly_obj in all_polygons(self.root):
            if not is_visible(poly_obj) or not is_locked(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_poly = t, poly_obj
        if best_poly is None:
            return None
        topmost_locked = None
        node = best_poly.group
        while node is not None:
            if node.locked:
                topmost_locked = node
            node = node.parent
        return topmost_locked

    def pick_edge(self, ray_o, ray_d):
        """Returns (poly_idx, edge_idx) of the closest edge to the click, or None."""
        best_t, best_poly = float('inf'), -1
        flat = all_polygons(self.root)
        for i, poly_obj in enumerate(flat):
            if not is_visible(poly_obj) or is_locked(poly_obj):
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
            if not is_visible(poly_obj) or is_locked(poly_obj):
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
        serializer.save_json(self, path)

    def import_json(self, path):
        """Merges polygons from a JSON file into the current scene."""
        serializer.import_json(self, path)

    def load_json(self, path):
        """Imports a scene from a JSON file (appends to existing polygons)."""
        serializer.load_json(self, path)

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
            if self._state:
                self._state._emit("polygon_transformed")


    # ── VBO helpers ───────────────────────────────────────────────────────────
    def _mark_dirty(self, **_kw):
        self._vbo_dirty = True

    def _upload_vbo(self, data_list, existing_vbo, floats_per_vertex):
        """Upload a flat float list to a VBO. Returns (vbo_id, count) or None."""
        if not data_list:
            if existing_vbo is not None:
                glDeleteBuffers(1, [existing_vbo[0]])
            return None
        data   = np.array(data_list, dtype=np.float32)
        count  = len(data_list) // floats_per_vertex
        vbo_id = existing_vbo[0] if existing_vbo is not None else glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo_id)
        glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
        return (vbo_id, count)

    def _rebuild_vbos(self, sel_poly_ids, sel_edges, sel_verts, sel_group_ids):
        """Rebuild every VBO from the current scene state."""
        visible = [p for p in iter_polygons(self.root) if is_visible(p)]
        visible.sort(key=lambda p: str(p.texture_atlas_id) if p.texture_atlas_id is not None else '')

        # Collect poly refs needed for edge/vertex detail passes
        needed_ids       = {id(p) for p, _ in sel_edges} | {id(p) for p, _ in sel_verts}
        poly_verts_by_id = {}

        # Outline buckets (list of vertex lists, one per polygon)
        root_polys   = []
        group_polys  = []
        sel_polys    = []
        locked_polys = []

        # Face data per texture: atlas_id -> flat [x,y,z,u,v, …] (triangulated)
        polys_by_tex: dict = {}

        for poly_obj in visible:
            v, uvs = poly_obj.vertices, poly_obj.uvs
            n      = len(v)
            if id(poly_obj) in needed_ids:
                poly_verts_by_id[id(poly_obj)] = v

            # Fan-triangulate into flat interleaved array
            atlas_id = poly_obj.texture_atlas_id if poly_obj.texture_atlas_id is not None else None
            face_buf = polys_by_tex.setdefault(atlas_id, [])
            for i in range(n - 2):
                i0, i1, i2 = 0, i + 1, i + 2
                # Flat face normal — CW winding → cross(e2, e1)
                e1 = math3d.vsub(v[i1], v[i0])
                e2 = math3d.vsub(v[i2], v[i0])
                nx, ny, nz = math3d.normalize(math3d.cross(e2, e1))
                for idx in (i0, i1, i2):
                    face_buf += [v[idx][0], v[idx][1], v[idx][2], nx, ny, nz, uvs[idx][0], uvs[idx][1]]

            # Outline bucket assignment
            in_locked_group = sel_group_ids and any(
                id(node) in sel_group_ids and getattr(node, 'locked', False)
                for node in iter_ancestors(poly_obj)
            )
            if id(poly_obj) in sel_poly_ids:
                sel_polys.append(v)
            elif in_locked_group:
                locked_polys.append(v)
            elif poly_obj.group is not self.root:
                group_polys.append(v)
            else:
                root_polys.append(v)

        # ── Upload face VBOs (reuse existing buffer objects where possible) ──
        for atlas_id in list(self._face_vbos):
            if atlas_id not in polys_by_tex:
                glDeleteBuffers(1, [self._face_vbos.pop(atlas_id)[0]])

        for atlas_id, face_data in polys_by_tex.items():
            existing = self._face_vbos.get(atlas_id)
            result   = self._upload_vbo(face_data, existing, 8)
            if result is not None:
                self._face_vbos[atlas_id] = result
            elif atlas_id in self._face_vbos:
                del self._face_vbos[atlas_id]

        # ── Upload outline VBOs ───────────────────────────────────────────────
        def edge_data(bucket):
            buf = []
            for poly in bucket:
                n = len(poly)
                for i in range(n):
                    v0, v1 = poly[i], poly[(i + 1) % n]
                    buf += [v0[0], v0[1], v0[2], v1[0], v1[1], v1[2]]
            return buf

        self._vbo_root   = self._upload_vbo(edge_data(root_polys),   self._vbo_root,   3)
        self._vbo_group  = self._upload_vbo(edge_data(group_polys),  self._vbo_group,  3)
        self._vbo_sel    = self._upload_vbo(edge_data(sel_polys),    self._vbo_sel,    3)
        self._vbo_locked = self._upload_vbo(edge_data(locked_polys), self._vbo_locked, 3)

        # ── Upload selection-detail VBOs ──────────────────────────────────────
        edge_buf = []
        for poly_ref, edge_idx in sel_edges:
            p = poly_verts_by_id.get(id(poly_ref))
            if p is not None:
                v0, v1 = p[edge_idx], p[(edge_idx + 1) % len(p)]
                edge_buf += [v0[0], v0[1], v0[2], v1[0], v1[1], v1[2]]
        self._vbo_sel_edges = self._upload_vbo(edge_buf, self._vbo_sel_edges, 3)

        vert_buf = []
        for poly_ref, vert_idx in sel_verts:
            p = poly_verts_by_id.get(id(poly_ref))
            if p is not None and vert_idx < len(p):
                v0 = p[vert_idx]
                vert_buf += [v0[0], v0[1], v0[2]]
        self._vbo_sel_verts = self._upload_vbo(vert_buf, self._vbo_sel_verts, 3)

        glBindBuffer(GL_ARRAY_BUFFER, 0)
        self._vbo_dirty = False

    def _draw_lines_vbo(self, vbo_tuple, color4):
        """Draw a lines VBO with a given RGBA colour. Caller manages line width."""
        if vbo_tuple is None:
            return
        vbo_id, count = vbo_tuple
        glColor4f(*color4)
        glEnableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, vbo_id)
        glVertexPointer(3, GL_FLOAT, 0, None)
        glDrawArrays(GL_LINES, 0, count)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)

    # ── Rendering ─────────────────────────────────────────────────────────────
    def draw(self):
        # Upload any atlases queued outside the GL frame (context is now active)
        if self._pending_atlases:
            for atlas in self._pending_atlases:
                self._upload_atlas(atlas)
            self._pending_atlases.clear()

        # Lazy subscription to state events (first draw after state is injected)
        if self._state is not None and not self._subscribed:
            self._state.subscribe("scene_changed",      self._mark_dirty)
            self._state.subscribe("polygon_transformed", self._mark_dirty)
            self._state.subscribe("selection_changed",   self._mark_dirty)
            self._subscribed = True

        sel_poly_ids  = {id(p) for p in (self._state.selected_polygons if self._state else [])}
        sel_edges     = self._state.selected_edges    if self._state else []
        sel_verts     = self._state.selected_vertices if self._state else []
        sel_group_ids = {id(g) for g in (self._state.selected_groups  if self._state else [])}

        if self._vbo_dirty:
            self._rebuild_vbos(sel_poly_ids, sel_edges, sel_verts, sel_group_ids)

        # ── Face pass — one glDrawArrays per texture atlas ───────────────────
        # Lighting is set here, after the camera modelview transform, so the
        # light direction is expressed in world space and stays fixed.
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_AMBIENT,  _LIGHT_AMBIENT)
        glLightfv(GL_LIGHT0, GL_DIFFUSE,  _LIGHT_DIFFUSE)
        glLightfv(GL_LIGHT0, GL_POSITION, _LIGHT_DIR)
        glEnable(GL_COLOR_MATERIAL)
        glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)

        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK);  glFrontFace(GL_CW)
        glEnable(GL_TEXTURE_2D);  glColor3f(1.0, 1.0, 1.0)
        glEnableClientState(GL_VERTEX_ARRAY)
        glEnableClientState(GL_TEXTURE_COORD_ARRAY)

        stride = 8 * 4   # 8 floats × 4 bytes (x,y,z,nx,ny,nz,u,v interleaved)
        glEnableClientState(GL_NORMAL_ARRAY)
        for atlas_id, (vbo_id, count) in self._face_vbos.items():
            tex_id = self.poly_textures.get(atlas_id, self.poly_texture)
            glBindTexture(GL_TEXTURE_2D, tex_id)
            glBindBuffer(GL_ARRAY_BUFFER, vbo_id)
            glVertexPointer(3, GL_FLOAT, stride, ctypes.c_void_p(0))
            glNormalPointer(GL_FLOAT, stride, ctypes.c_void_p(12))
            glTexCoordPointer(2, GL_FLOAT, stride, ctypes.c_void_p(24))
            glDrawArrays(GL_TRIANGLES, 0, count)

        glDisableClientState(GL_NORMAL_ARRAY)
        glDisableClientState(GL_TEXTURE_COORD_ARRAY)
        glDisableClientState(GL_VERTEX_ARRAY)
        glBindBuffer(GL_ARRAY_BUFFER, 0)
        glDisable(GL_TEXTURE_2D)
        glDisable(GL_CULL_FACE)
        glDisable(GL_COLOR_MATERIAL)
        glDisable(GL_LIGHT0)
        glDisable(GL_LIGHTING)

        # ── Outline pass — VBO draw calls, one per colour bucket ─────────────
        if self._vbo_root or self._vbo_group:
            glLineWidth(1.5)
            glEnable(GL_BLEND);  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            self._draw_lines_vbo(self._vbo_root,  (1.0, 0.75, 0.35, 0.5))
            self._draw_lines_vbo(self._vbo_group, (0.2, 0.7,  1.0,  0.5))
            glDisable(GL_BLEND)
            glLineWidth(1.0)

        if self._vbo_locked:
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.5)
            self._draw_lines_vbo(self._vbo_locked, (1.0, 0.15, 0.15, 0.9))
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)

        if self._vbo_sel:
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.5)
            self._draw_lines_vbo(self._vbo_sel, (1.0, 0.15, 0.15, 1.0))
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)

        # ── Selected edges ────────────────────────────────────────────────────
        if self._vbo_sel_edges:
            glDisable(GL_DEPTH_TEST)
            glLineWidth(4.0)
            self._draw_lines_vbo(self._vbo_sel_edges, (0.05, 0.05, 1.0, 1.0))
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)

        # ── Selected vertices ─────────────────────────────────────────────────
        if self._vbo_sel_verts:
            vbo_id, count = self._vbo_sel_verts
            glDisable(GL_DEPTH_TEST)
            glPointSize(8.0)
            glColor3f(0.05, 1.0, 0.3)
            glEnableClientState(GL_VERTEX_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, vbo_id)
            glVertexPointer(3, GL_FLOAT, 0, None)
            glDrawArrays(GL_POINTS, 0, count)
            glDisableClientState(GL_VERTEX_ARRAY)
            glBindBuffer(GL_ARRAY_BUFFER, 0)
            glPointSize(1.0)
            glEnable(GL_DEPTH_TEST)
