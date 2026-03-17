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
)

from editor.constants import TEXTURE_PATH, PREVIEW_MAX_SZ
from editor import math3d
from editor.group import Group, Polygon, all_polygons, iter_polygons


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

        self.selected_idx     = -1
        self.selected_indices = set()

        self.selected_edges         = set()    # set de (poly_idx, edge_idx)
        self.selected_edges_ordered = []       # même éléments, dans l'ordre de sélection

        self.selected_vertices      = set()    # set de (poly_idx, vertex_idx)

        self.poly_texture  = 0
        self.atlas_w       = 1
        self.atlas_h       = 1
        self.atlas_data    = {}

        self.tex_preview_win = None
        self.tex_preview_sz  = 0

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
    def _select_new_polygon(self, new_poly):
        """Sélectionne un polygone nouvellement créé."""
        flat = all_polygons(self.root)
        idx = next((i for i, p in enumerate(flat) if p is new_poly), -1)
        if idx >= 0:
            self.selected_indices = {idx}
            self.selected_idx     = idx

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

    def rotate_uvs(self):
        """Décale circulairement les UVs des polygons sélectionnés (v0→v1, v1→v2, …)."""
        flat = all_polygons(self.root)
        for i in self.selected_indices:
            if i < len(flat):
                poly = flat[i]
                poly.uvs = [poly.uvs[-1]] + list(poly.uvs[:-1])

    def flip_orientation(self):
        """Inverse l'orientation (normale) des polygons sélectionnés."""
        flat = all_polygons(self.root)
        for i in self.selected_indices:
            if i < len(flat):
                poly = flat[i]
                poly.vertices = list(reversed(poly.vertices))
                poly.uvs      = list(reversed(poly.uvs))

    def delete_selected(self):
        flat         = all_polygons(self.root)
        deleted_set  = set(self.selected_indices)
        sorted_del   = sorted(deleted_set)

        # Recalculer les sélections d'arêtes et de sommets (encore en int)
        new_edges = set()
        for poly_idx, edge_idx in self.selected_edges:
            if poly_idx in deleted_set:
                continue
            shift = sum(1 for d in sorted_del if d < poly_idx)
            new_edges.add((poly_idx - shift, edge_idx))
        self.selected_edges         = new_edges
        self.selected_edges_ordered = [e for e in self.selected_edges_ordered if e in new_edges]

        new_verts = set()
        for poly_idx, vert_idx in self.selected_vertices:
            if poly_idx in deleted_set:
                continue
            shift = sum(1 for d in sorted_del if d < poly_idx)
            new_verts.add((poly_idx - shift, vert_idx))
        self.selected_vertices = new_verts

        # Supprimer les polygones de l'arbre
        for i in sorted_del:
            if i < len(flat):
                poly = flat[i]
                if poly.group is not None:
                    poly.group.remove_polygon(poly)

        # Nettoyer les groupes vides
        for child in list(self.root.children):
            if isinstance(child, Group) and not all_polygons(child):
                self.root.children.remove(child)

        self.selected_idx     = -1
        self.selected_indices = set()

    def duplicate_selected(self):
        if not self.selected_indices:
            return
        flat      = all_polygons(self.root)
        new_polys = []

        for i in sorted(self.selected_indices):
            if i < len(flat):
                poly = flat[i]
                new_polys.append(poly.group.add_polygon(
                    copy.deepcopy(poly.vertices),
                    list(poly.uvs),
                ))

        flat_after  = all_polygons(self.root)
        new_indices = {flat_after.index(p) for p in new_polys}
        self.selected_indices = new_indices
        self.selected_idx     = max(new_indices) if new_indices else -1

    # ── Sélection ─────────────────────────────────────────────────────────────
    def selection_center(self):
        """Barycentre de tous les polygons sélectionnés."""
        indices = [i for i in self.selected_indices if i < len(self.polygons)]
        if not indices:
            return math3d.poly_center(self.polygons[self.selected_idx]) if self.selected_idx >= 0 else (0.0, 0.0, 0.0)
        cs = [math3d.poly_center(self.polygons[i]) for i in indices]
        return (sum(c[0] for c in cs)/len(cs),
                sum(c[1] for c in cs)/len(cs),
                sum(c[2] for c in cs)/len(cs))

    def pick_polygon(self, ray_o, ray_d):
        """Retourne l'indice du polygon le plus proche sous le rayon, ou -1."""
        best_t, best_i = float('inf'), -1
        for i, p in enumerate(self.polygons):
            t = math3d.ray_poly_intersect(ray_o, ray_d, p)
            if t is not None and t < best_t:
                best_t, best_i = t, i
        return best_i

    def pick_edge(self, ray_o, ray_d):
        """Retourne (poly_idx, edge_idx) de l'arête la plus proche du clic, ou None."""
        best_t, best_poly = float('inf'), -1
        for i, p in enumerate(self.polygons):
            t = math3d.ray_poly_intersect(ray_o, ray_d, p)
            if t is not None and t < best_t:
                best_t, best_poly = t, i
        if best_poly < 0:
            return None
        hit  = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = self.polygons[best_poly]
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
        for i, p in enumerate(self.polygons):
            t = math3d.ray_poly_intersect(ray_o, ray_d, p)
            if t is not None and t < best_t:
                best_t, best_poly = t, i
        if best_poly < 0:
            return None
        hit  = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = self.polygons[best_poly]
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
        if len(self.selected_indices) < 2:
            return
        old_flat       = all_polygons(self.root)
        polys_to_group = [old_flat[i] for i in sorted(self.selected_indices)
                          if i < len(old_flat)]

        new_group = self.root.add_group("Groupe")
        for poly in polys_to_group:
            new_group.adopt(poly)

        self._refresh_int_selections(old_flat)

    def ungroup_selected(self):
        """Dissocie les sous-groupes contenant des polygons sélectionnés."""
        old_flat = all_polygons(self.root)

        groups_to_dissolve = set()
        for i in self.selected_indices:
            if i < len(old_flat):
                poly = old_flat[i]
                if poly.group is not self.root:
                    groups_to_dissolve.add(poly.group)

        for group in groups_to_dissolve:
            for child in list(group.children):
                self.root.adopt(child)
            if group in self.root.children:
                self.root.children.remove(group)

        self._refresh_int_selections(old_flat)

    def _refresh_int_selections(self, old_flat):
        """Recalcule toutes les sélections entières après un changement d'ordre dans l'arbre."""
        new_flat        = all_polygons(self.root)
        poly_to_new_idx = {id(p): i for i, p in enumerate(new_flat)}

        # selected_indices
        new_sel = set()
        for i in self.selected_indices:
            if i < len(old_flat):
                new_i = poly_to_new_idx.get(id(old_flat[i]))
                if new_i is not None:
                    new_sel.add(new_i)
        self.selected_indices = new_sel

        # selected_idx
        if 0 <= self.selected_idx < len(old_flat):
            self.selected_idx = poly_to_new_idx.get(id(old_flat[self.selected_idx]), -1)
        else:
            self.selected_idx = -1

        # selected_edges
        new_edges = set()
        new_edges_ordered = []
        for pi, ei in self.selected_edges:
            if pi < len(old_flat):
                new_pi = poly_to_new_idx.get(id(old_flat[pi]))
                if new_pi is not None:
                    new_edges.add((new_pi, ei))
        for pi, ei in self.selected_edges_ordered:
            if pi < len(old_flat):
                new_pi = poly_to_new_idx.get(id(old_flat[pi]))
                if new_pi is not None:
                    new_edges_ordered.append((new_pi, ei))
        self.selected_edges         = new_edges
        self.selected_edges_ordered = new_edges_ordered

        # selected_vertices
        new_verts = set()
        for pi, vi in self.selected_vertices:
            if pi < len(old_flat):
                new_pi = poly_to_new_idx.get(id(old_flat[pi]))
                if new_pi is not None:
                    new_verts.add((new_pi, vi))
        self.selected_vertices = new_verts

    # ── Sauvegarde ────────────────────────────────────────────────────────────
    def save_json(self, path):
        """Exporte la scène dans un fichier JSON hiérarchique."""
        def serialize(node):
            if isinstance(node, Polygon):
                return {
                    "vertices": [[round(v, 6) for v in vert] for vert in node.vertices],
                    "uvs":      [[round(u, 6), round(v, 6)] for u, v in node.uvs],
                }
            else:
                return {
                    "name":     node.name,
                    "children": [serialize(c) for c in node.children],
                }
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"root": serialize(self.root)}, f, indent=2, ensure_ascii=False)

    def load_json(self, path):
        """Importe une scène depuis un fichier JSON (ajoute aux polygons existants)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        n_before = len(all_polygons(self.root))

        if "root" in data:
            # Nouveau format hiérarchique
            def load_node(node_data, parent):
                if "vertices" in node_data:
                    parent.add_polygon(
                        [tuple(v) for v in node_data["vertices"]],
                        [tuple(uv) for uv in node_data["uvs"]],
                    )
                else:
                    group = parent.add_group(node_data.get("name", "Groupe"))
                    for child_data in node_data.get("children", []):
                        load_node(child_data, group)
            for child_data in data["root"].get("children", []):
                load_node(child_data, self.root)

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

        n_after     = len(all_polygons(self.root))
        new_indices = set(range(n_before, n_after))
        if new_indices:
            self.selected_indices = new_indices
            self.selected_idx     = max(new_indices)

    # ── Opérations sur arêtes ─────────────────────────────────────────────────
    def rapprocher_edges(self):
        """Déplace le second polygon pour aligner le centre de son arête sur celui du premier."""
        if len(self.selected_edges_ordered) != 2:
            return
        e1, e2   = self.selected_edges_ordered
        qi1, ei1 = e1
        qi2, ei2 = e2
        q1, q2   = self.polygons[qi1], self.polygons[qi2]
        c1 = math3d.vscale(math3d.vadd(tuple(q1[ei1]), tuple(q1[(ei1+1) % len(q1)])), 0.5)
        c2 = math3d.vscale(math3d.vadd(tuple(q2[ei2]), tuple(q2[(ei2+1) % len(q2)])), 0.5)
        delta = math3d.vsub(c1, c2)
        self.polygons[qi2] = [math3d.vadd(tuple(v), delta) for v in q2]

    def create_polygon_from_edges(self):
        """Crée un nouveau polygon (quad) en reliant les deux arêtes sélectionnées."""
        if len(self.selected_edges_ordered) != 2:
            return
        e1, e2   = self.selected_edges_ordered
        qi1, ei1 = e1
        qi2, ei2 = e2
        q1, q2   = self.polygons[qi1], self.polygons[qi2]
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
        self.root.add_polygon(unique, quad_uvs[:len(unique)])

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
        if entry and self.selected_indices:
            u0 = entry["x"] / self.atlas_w
            u1 = (entry["x"] + entry["width"]) / self.atlas_w
            v1 = 1.0 - entry["y"] / self.atlas_h
            v0 = 1.0 - (entry["y"] + entry["height"]) / self.atlas_h
            corners = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]
            for idx in self.selected_indices:
                n = len(self.polygons[idx])
                self.poly_uvs[idx] = [corners[i % 4] for i in range(n)]

    def assign_uv_from_atlas_click(self, event_pos):
        """Applique les UVs de l'atlas au polygon sélectionné selon le clic dans l'aperçu."""
        px = int(event_pos[0] * self.atlas_w / self.tex_preview_sz)
        py = int(event_pos[1] * self.atlas_h / self.tex_preview_sz)
        self.assign_uv_at_atlas_pixel(px, py)

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def draw(self):
        # Indices nécessaires pour les arêtes/sommets sélectionnés
        needed = ({pi for pi, _ in self.selected_edges} |
                  {pi for pi, _ in self.selected_vertices})
        indexed = {}  # {poly_idx: vertices} collecté pendant la passe principale

        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK);  glFrontFace(GL_CW)
        for i, poly_obj in enumerate(iter_polygons(self.root)):
            poly = poly_obj.vertices
            uvs  = poly_obj.uvs
            sel  = (i in self.selected_indices)
            if i in needed:
                indexed[i] = poly
            glEnable(GL_TEXTURE_2D);  glBindTexture(GL_TEXTURE_2D, self.poly_texture)
            glColor3f(1.0, 1.0, 1.0)
            glBegin(GL_TRIANGLE_FAN)
            for (vx, vy, vz), (u, v) in zip(poly, uvs):
                glTexCoord2f(u, v);  glVertex3f(vx, vy, vz)
            glEnd()
            glDisable(GL_TEXTURE_2D)
            glLineWidth(2.5 if sel else 1.5)
            if sel:
                glColor4f(1.0, 0.15, 0.15, 1.0)
            elif poly_obj.group is not self.root:
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glColor4f(0.2, 0.7, 1.0, 0.5)
            else:
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glColor4f(1.0, 0.75, 0.35, 0.5)
            glBegin(GL_LINE_LOOP)
            for vx, vy, vz in poly: glVertex3f(vx, vy, vz)
            glEnd()
            if not sel:
                glDisable(GL_BLEND)
        glLineWidth(1.0)
        glDisable(GL_CULL_FACE)
        if self.selected_edges:
            glLineWidth(4.0)
            glColor3f(0.05, 0.05, 1.0)
            glBegin(GL_LINES)
            for poly_idx, edge_idx in self.selected_edges:
                p = indexed.get(poly_idx)
                if p is not None:
                    glVertex3f(*p[edge_idx])
                    glVertex3f(*p[(edge_idx + 1) % len(p)])
            glEnd()
            glLineWidth(1.0)
        if self.selected_vertices:
            glPointSize(8.0)
            glColor3f(0.05, 1.0, 0.3)
            glBegin(GL_POINTS)
            for poly_idx, vert_idx in self.selected_vertices:
                p = indexed.get(poly_idx)
                if p is not None and vert_idx < len(p):
                    glVertex3f(*p[vert_idx])
            glEnd()
            glPointSize(1.0)
