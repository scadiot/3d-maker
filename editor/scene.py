"""Classe Scene : polygons, UVs, texture, atlas, sélection."""

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


# ── Vues plates (compatibilité avec gizmo.py et le reste) ─────────────────────

class _PolygonVertices:
    """Vue plate sur les vertices de tous les polygones de la scène.

    Permet d'utiliser scene.polygons[i] et scene.polygons[i] = v
    sans modifier app.py ni gizmo.py.
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
        return self._flat()[i].vertices   # liste mutable réelle → q[vi] = v fonctionne

    def __setitem__(self, i, value):
        self._flat()[i].vertices = list(value)


class _PolyUVs:
    """Vue plate sur les UVs de tous les polygones de la scène."""
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


# ── Classe Scene ───────────────────────────────────────────────────────────────

class Scene:
    def __init__(self):
        self.root     = Group(name="Scène")
        self.polygons = _PolygonVertices(self.root)
        self.poly_uvs = _PolyUVs(self.root)

        self._state = None   # injecté par App après création du StateManager

        self.poly_texture  = 0
        self.atlas_w       = 1
        self.atlas_h       = 1
        self.atlas_data    = {}

        self.tex_preview_win = None
        self.tex_preview_sz  = 0

    # ── Propriétés de compatibilité (délèguent au StateManager) ──────────────

    @property
    def selected_indices(self) -> set:
        """Indices entiers des polygones sélectionnés (compatibilité gizmo/rendu)."""
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
        """Arêtes sélectionnées sous forme d'indices entiers (compatibilité Gizmo)."""
        if self._state is None:
            return set()
        flat     = all_polygons(self.root)
        flat_idx = {id(p): i for i, p in enumerate(flat)}
        return {(flat_idx[id(p)], ei)
                for p, ei in self._state._selected_edges
                if id(p) in flat_idx}

    @property
    def selected_vertices(self) -> set:
        """Sommets sélectionnés sous forme d'indices entiers (compatibilité Gizmo)."""
        if self._state is None:
            return set()
        flat     = all_polygons(self.root)
        flat_idx = {id(p): i for i, p in enumerate(flat)}
        return {(flat_idx[id(p)], vi)
                for p, vi in self._state._selected_vertices
                if id(p) in flat_idx}

    @property
    def selected_idx(self) -> int:
        """Dernier polygone sélectionné (valeur dérivée de selected_indices)."""
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
        # Valeur dérivée — ignorée quand le StateManager est actif.
        if self._state is None:
            self._sel_idx_fb = value

    # ── Chargement ────────────────────────────────────────────────────────────
    def load_atlas(self, json_path):
        with open(json_path, encoding="utf-8") as f:
            self.atlas_data = json.load(f)

    def load_texture(self, path):
        """Charge une texture PNG dans OpenGL via PIL."""
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

    # ── Gestion des polygons ──────────────────────────────────────────────────
    def _emit_scene_changed(self, change_type: str, **kw) -> None:
        """Notifie le StateManager d'un changement structurel de la scène."""
        if self._state is not None:
            self._state._modified = True
            self._state._emit("scene_changed", change_type=change_type, **kw)

    def _select_new_polygon(self, new_poly):
        """Sélectionne un polygone nouvellement créé."""
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
        """Décale circulairement les UVs des polygons sélectionnés (v0→v1, v1→v2, …)."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.uvs = [poly.uvs[-1]] + list(poly.uvs[:-1])

    def flip_orientation(self):
        """Inverse l'orientation (normale) des polygons sélectionnés."""
        for poly in (self._state.selected_polygons if self._state else []):
            poly.vertices = list(reversed(poly.vertices))
            poly.uvs      = list(reversed(poly.uvs))

    def delete_selected(self):
        polys = self._state.selected_polygons if self._state else []

        # Supprimer les polygones de l'arbre
        for poly in polys:
            if poly.group is not None:
                poly.group.remove_polygon(poly)

        # Nettoyer les groupes vides
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

    # ── Sélection ─────────────────────────────────────────────────────────────
    def selection_center(self):
        """Barycentre de tous les polygons sélectionnés."""
        polys = self._state.selected_polygons if self._state else []
        if not polys:
            return (0.0, 0.0, 0.0)
        cs = [math3d.poly_center(p.vertices) for p in polys]
        return (sum(c[0] for c in cs)/len(cs),
                sum(c[1] for c in cs)/len(cs),
                sum(c[2] for c in cs)/len(cs))

    def pick_polygon(self, ray_o, ray_d):
        """Retourne l'indice du polygon le plus proche sous le rayon, ou -1."""
        best_t, best_i = float('inf'), -1
        for i, poly_obj in enumerate(all_polygons(self.root)):
            if not is_visible(poly_obj):
                continue
            t = math3d.ray_poly_intersect(ray_o, ray_d, poly_obj.vertices)
            if t is not None and t < best_t:
                best_t, best_i = t, i
        return best_i

    def pick_edge(self, ray_o, ray_d):
        """Retourne (poly_idx, edge_idx) de l'arête la plus proche du clic, ou None."""
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
        """Retourne (poly_idx, vertex_idx) du sommet le plus proche du clic, ou None."""
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

    # ── Groupes ───────────────────────────────────────────────────────────────
    def get_group_for_polygon(self, idx):
        """Retourne un Set[int] des indices des polygones du même sous-groupe, ou None."""
        flat = all_polygons(self.root)
        if idx < 0 or idx >= len(flat):
            return None
        poly = flat[idx]
        if poly.group is self.root:
            return None   # directement sous la racine → pas groupé
        return {i for i, p in enumerate(flat) if p.group is poly.group}

    def group_selected(self):
        """Groupe les polygons sélectionnés (minimum 2) dans un nouveau sous-groupe."""
        polys_to_group = self._state.selected_polygons if self._state else []
        if len(polys_to_group) < 2:
            return
        new_group = self.root.add_group("Groupe")
        for poly in polys_to_group:
            new_group.adopt_polygon(poly)
        self._emit_scene_changed("group_added", group=new_group, parent=self.root)

    def ungroup_selected(self):
        """Dissocie les sous-groupes contenant des polygons sélectionnés."""
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

    # ── Sauvegarde ────────────────────────────────────────────────────────────
    def save_json(self, path):
        """Exporte la scène dans un fichier JSON hiérarchique."""
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
        """Importe une scène depuis un fichier JSON (ajoute aux polygons existants)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        n_before = len(all_polygons(self.root))

        if "root" in data:
            def load_group(node_data, parent):
                for p_data in node_data.get("polygons", []):
                    parent.add_polygon(
                        [tuple(v) for v in p_data["vertices"]],
                        [tuple(uv) for uv in p_data["uvs"]],
                    )
                for g_data in node_data.get("groups", []):
                    child = parent.add_group(g_data.get("name", "Groupe"))
                    load_group(g_data, child)
                # Rétrocompatibilité : ancien format avec "children" mixte
                for child_data in node_data.get("children", []):
                    if "vertices" in child_data:
                        parent.add_polygon(
                            [tuple(v) for v in child_data["vertices"]],
                            [tuple(uv) for uv in child_data["uvs"]],
                        )
                    else:
                        child = parent.add_group(child_data.get("name", "Groupe"))
                        load_group(child_data, child)
            load_group(data["root"], self.root)

        else:
            # Ancien format plat (rétrocompatibilité)
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

        flat_after = all_polygons(self.root)
        new_polys  = flat_after[n_before:]
        if new_polys and self._state is not None:
            self._state.set_selection(polygons=new_polys)
        if self._state is not None:
            self._state.project_name = data.get("name", "Unnamed Project")
            self._state.project_path = path
        self._emit_scene_changed("polygons_added")

    # ── Opérations sur arêtes ─────────────────────────────────────────────────
    def rapprocher_edges(self):
        """Déplace le second polygon pour aligner le centre de son arête sur celui du premier."""
        if self._state is None:
            return
        edges = self._state.selected_edges
        if len(edges) != 2:
            return
        poly1, ei1 = edges[0]
        poly2, ei2 = edges[1]
        q1 = poly1.vertices
        q2 = poly2.vertices
        c1 = math3d.vscale(math3d.vadd(tuple(q1[ei1]), tuple(q1[(ei1+1) % len(q1)])), 0.5)
        c2 = math3d.vscale(math3d.vadd(tuple(q2[ei2]), tuple(q2[(ei2+1) % len(q2)])), 0.5)
        delta = math3d.vsub(c1, c2)
        poly2.vertices = [math3d.vadd(tuple(v), delta) for v in q2]

    def create_polygon_from_edges(self, group=None):
        """Crée un nouveau polygon (quad) en reliant les deux arêtes sélectionnées."""
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
        # Si les diagonales ne se croisent pas → quad papillon → inverser c et d
        if not math3d.diagonals_intersect(a, b, c, d):
            c, d = d, c
        # Aligner l'orientation sur les polygons sources
        n1 = math3d.cross(math3d.vsub(tuple(q1[1 % len(q1)]), tuple(q1[0])),
                          math3d.vsub(tuple(q1[-1]), tuple(q1[0])))
        n2 = math3d.cross(math3d.vsub(tuple(q2[1 % len(q2)]), tuple(q2[0])),
                          math3d.vsub(tuple(q2[-1]), tuple(q2[0])))
        n_ref = math3d.vadd(n1, n2)
        n_new = math3d.cross(math3d.vsub(b, a), math3d.vsub(d, a))
        if math3d.dot(n_new, n_ref) < 0:
            a, b, c, d = d, c, b, a
        # Dédupliquer les vertex coïncidents → triangle si deux vertex sont au même endroit
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

    # ── Aperçu texture ────────────────────────────────────────────────────────
    def open_tex_preview(self, root_tk):
        if self.tex_preview_win:
            return
        img = Image.open(TEXTURE_PATH)
        sz  = min(img.width, PREVIEW_MAX_SZ)
        self.tex_preview_sz = sz
        img = img.resize((sz, sz), Image.LANCZOS)

        self.tex_preview_win = tk.Toplevel(root_tk)
        self.tex_preview_win.title("Aperçu texture")
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
        """Applique les UVs de l'atlas au polygon sélectionné à partir de coordonnées atlas brutes."""
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
        """Applique les UVs de l'atlas au polygon sélectionné selon le clic dans l'aperçu."""
        px = int(event_pos[0] * self.atlas_w / self.tex_preview_sz)
        py = int(event_pos[1] * self.atlas_h / self.tex_preview_sz)
        self.assign_uv_at_atlas_pixel(px, py)

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def draw(self):
        sel_poly_ids = {id(p) for p in (self._state.selected_polygons if self._state else [])}
        sel_edges    = self._state.selected_edges if self._state else []
        sel_verts    = self._state.selected_vertices if self._state else []

        # Polygones avec arêtes/sommets sélectionnés (pour rendu post-boucle)
        edge_poly_ids = {id(p) for p, _ in sel_edges}
        vert_poly_ids = {id(p) for p, _ in sel_verts}
        needed_ids    = edge_poly_ids | vert_poly_ids
        poly_verts_by_id = {}  # {id(poly_obj): vertices}

        selected_polys_verts = []  # vertices des polygones sélectionnés, rendu différé

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

        # Bordures de sélection rouge rendues sans z-buffer (toujours visibles)
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
