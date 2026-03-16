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


class Scene:
    def __init__(self):
        self.polygons         = []
        self.poly_uvs         = []
        self.selected_idx     = -1
        self.selected_indices = set()
        self.groups           = []   # liste de sets d'indices formant des groupes

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
    def add_polygon(self, cam_pos, cam_yaw):
        import math as _math
        yr = _math.radians(cam_yaw)
        cx = round(cam_pos[0] - _math.sin(yr)*5)
        cz = round(cam_pos[2] - _math.cos(yr)*5)
        self.polygons.append([
            (cx-1, 0.0, cz-1), (cx+1, 0.0, cz-1),
            (cx+1, 0.0, cz+1), (cx-1, 0.0, cz+1),
        ])
        self.poly_uvs.append([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])

    def add_triangle(self, cam_pos, cam_yaw):
        import math as _math
        yr = _math.radians(cam_yaw)
        cx = round(cam_pos[0] - _math.sin(yr)*5)
        cz = round(cam_pos[2] - _math.cos(yr)*5)
        self.polygons.append([
            (cx,   0.0, cz-1),
            (cx+1, 0.0, cz+1),
            (cx-1, 0.0, cz+1),
        ])
        self.poly_uvs.append([(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)])

    def rotate_uvs(self):
        """Décale circulairement les UVs des polygons sélectionnés (v0→v1, v1→v2, …)."""
        for i in self.selected_indices:
            uvs = self.poly_uvs[i]
            self.poly_uvs[i] = [uvs[-1]] + list(uvs[:-1])

    def flip_orientation(self):
        """Inverse l'orientation (normale) des polygons sélectionnés en retournant l'ordre des sommets."""
        for i in self.selected_indices:
            self.polygons[i] = list(reversed(self.polygons[i]))
            self.poly_uvs[i] = list(reversed(self.poly_uvs[i]))

    def delete_selected(self):
        deleted = set(self.selected_indices)
        for i in sorted(deleted, reverse=True):
            self.polygons.pop(i)
            self.poly_uvs.pop(i)
        self._reindex_after_delete(deleted)
        sorted_deleted = sorted(deleted)
        new_edges = set()
        for poly_idx, edge_idx in self.selected_edges:
            if poly_idx in deleted:
                continue
            shift = sum(1 for d in sorted_deleted if d < poly_idx)
            new_edges.add((poly_idx - shift, edge_idx))
        self.selected_edges         = new_edges
        self.selected_edges_ordered = [e for e in self.selected_edges_ordered if e in new_edges]
        new_verts = set()
        for poly_idx, vert_idx in self.selected_vertices:
            if poly_idx in deleted:
                continue
            shift = sum(1 for d in sorted_deleted if d < poly_idx)
            new_verts.add((poly_idx - shift, vert_idx))
        self.selected_vertices = new_verts
        self.selected_idx     = -1
        self.selected_indices = set()

    def duplicate_selected(self):
        if not self.selected_indices:
            return
        first_new = len(self.polygons)
        sorted_sel = sorted(self.selected_indices)
        idx_map = {old: first_new + i for i, old in enumerate(sorted_sel)}
        for i in sorted_sel:
            self.polygons.append(copy.deepcopy(self.polygons[i]))
            self.poly_uvs.append(list(self.poly_uvs[i]))
        for group in self.groups:
            new_group = {idx_map[i] for i in group if i in idx_map}
            if len(new_group) >= 2:
                self.groups.append(new_group)
        new_indices = set(range(first_new, len(self.polygons)))
        self.selected_indices = new_indices
        self.selected_idx     = max(new_indices)

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
        hit = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = self.polygons[best_poly]
        n = len(poly)
        best_edge, best_dist = 0, float('inf')
        for ei in range(n):
            a = tuple(poly[ei])
            b = tuple(poly[(ei + 1) % n])
            cp = math3d.closest_point_on_seg(hit, a, b)
            d = math3d.vlength(math3d.vsub(hit, cp))
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
        hit = math3d.vadd(ray_o, math3d.vscale(ray_d, best_t))
        poly = self.polygons[best_poly]
        best_vi, best_dist = 0, float('inf')
        for vi, v in enumerate(poly):
            d = math3d.vlength(math3d.vsub(hit, tuple(v)))
            if d < best_dist:
                best_dist, best_vi = d, vi
        return (best_poly, best_vi)

    # ── Groupes ───────────────────────────────────────────────────────────────
    def get_group_for_polygon(self, idx):
        """Retourne le set du groupe contenant ce polygon, ou None."""
        for group in self.groups:
            if idx in group:
                return group
        return None

    def group_selected(self):
        """Groupe les polygons sélectionnés (minimum 2)."""
        if len(self.selected_indices) < 2:
            return
        for group in self.groups:
            group -= self.selected_indices
        self.groups = [g for g in self.groups if len(g) >= 2]
        self.groups.append(set(self.selected_indices))

    def ungroup_selected(self):
        """Dissocie les groupes contenant des polygons sélectionnés."""
        self.groups = [g for g in self.groups
                       if not g.intersection(self.selected_indices)]

    def _reindex_after_delete(self, deleted_indices):
        """Met à jour les groupes après suppression de polygons."""
        sorted_deleted = sorted(deleted_indices)
        new_groups = []
        for group in self.groups:
            new_group = set()
            for idx in group:
                if idx in deleted_indices:
                    continue
                shift = sum(1 for d in sorted_deleted if d < idx)
                new_group.add(idx - shift)
            if len(new_group) >= 2:
                new_groups.append(new_group)
        self.groups = new_groups

    # ── Sauvegarde ────────────────────────────────────────────────────────────
    def save_json(self, path):
        """Exporte la scène dans un fichier JSON (sommets et uvs)."""
        polys_data = []
        for poly, uvs in zip(self.polygons, self.poly_uvs):
            polys_data.append({
                "vertices": [[round(v, 6) for v in vert] for vert in poly],
                "uvs":      [[round(u, 6), round(v, 6)] for u, v in uvs],
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"polygons": polys_data}, f, indent=2, ensure_ascii=False)

    def load_json(self, path):
        """Importe une scène depuis un fichier JSON (ajoute aux polygons existants)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        first_new = len(self.polygons)
        # Nouveau format
        for p in data.get("polygons", []):
            self.polygons.append([tuple(v) for v in p["vertices"]])
            self.poly_uvs.append([tuple(uv) for uv in p["uvs"]])
        # Ancien format (rétrocompatibilité)
        for q in data.get("quads", []):
            center = tuple(q["position"])
            hw = q["size"][0] / 2
            hh = q["size"][1] / 2
            if "x_axis" in q and "y_axis" in q:
                wa = tuple(q["x_axis"])
                ha = tuple(q["y_axis"])
            else:
                wa, ha = math3d.perp_basis(tuple(q["orientation"]))
            self.polygons.append(math3d.quad_compose(center, wa, ha, hw, hh))
            self.poly_uvs.append([tuple(uv) for uv in q["uvs"]])
        new_indices = set(range(first_new, len(self.polygons)))
        if new_indices:
            self.selected_indices = new_indices
            self.selected_idx = max(new_indices)

    # ── Opérations sur arêtes ─────────────────────────────────────────────────
    def rapprocher_edges(self):
        """Déplace le second polygon pour aligner le centre de son arête sur celui du premier."""
        if len(self.selected_edges_ordered) != 2:
            return
        e1, e2 = self.selected_edges_ordered   # e1 = ancre, e2 = déplacé
        qi1, ei1 = e1
        qi2, ei2 = e2
        q1, q2 = self.polygons[qi1], self.polygons[qi2]
        c1 = math3d.vscale(math3d.vadd(tuple(q1[ei1]), tuple(q1[(ei1+1) % len(q1)])), 0.5)
        c2 = math3d.vscale(math3d.vadd(tuple(q2[ei2]), tuple(q2[(ei2+1) % len(q2)])), 0.5)
        delta = math3d.vsub(c1, c2)
        self.polygons[qi2] = [math3d.vadd(tuple(v), delta) for v in q2]

    def create_polygon_from_edges(self):
        """Crée un nouveau polygon (quad) en reliant les deux arêtes sélectionnées."""
        if len(self.selected_edges_ordered) != 2:
            return
        e1, e2 = self.selected_edges_ordered
        qi1, ei1 = e1
        qi2, ei2 = e2
        q1, q2 = self.polygons[qi1], self.polygons[qi2]
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
        verts = [a, b, c, d]
        unique = [verts[0]]
        for v in verts[1:]:
            if not any(math3d.vlength(math3d.vsub(v, u)) < 1e-6 for u in unique):
                unique.append(v)
        if len(unique) < 3:
            return  # dégénéré, on n'ajoute rien
        self.polygons.append(unique)
        quad_uvs = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        self.poly_uvs.append(quad_uvs[:len(unique)])

    # ── Aperçu texture ────────────────────────────────────────────────────────
    def open_tex_preview(self, root_tk):
        if self.tex_preview_win:
            return
        img = Image.open(TEXTURE_PATH)
        sz = min(img.width, PREVIEW_MAX_SZ)
        self.tex_preview_sz = sz
        img = img.resize((sz, sz), Image.LANCZOS)

        self.tex_preview_win = tk.Toplevel(root_tk)
        self.tex_preview_win.title("Aperçu texture")
        self.tex_preview_win.resizable(False, False)
        self.tex_preview_win.protocol("WM_DELETE_WINDOW", self.close_tex_preview)

        photo = ImageTk.PhotoImage(img)
        label = tk.Label(self.tex_preview_win, image=photo)
        label._photo = photo  # empêche le garbage collection
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
            # V inversé : texture uploadée verticalement retournée
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
        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK);  glFrontFace(GL_CW)
        for i, poly in enumerate(self.polygons):
            sel = (i in self.selected_indices)
            uvs = self.poly_uvs[i] if i < len(self.poly_uvs) else [(0,0),(1,0),(1,1),(0,1)]
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
            elif self.get_group_for_polygon(i) is not None:
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
                if poly_idx < len(self.polygons):
                    p = self.polygons[poly_idx]
                    glVertex3f(*p[edge_idx])
                    glVertex3f(*p[(edge_idx + 1) % len(p)])
            glEnd()
            glLineWidth(1.0)
        if self.selected_vertices:
            glPointSize(8.0)
            glColor3f(0.05, 1.0, 0.3)
            glBegin(GL_POINTS)
            for poly_idx, vert_idx in self.selected_vertices:
                if poly_idx < len(self.polygons):
                    p = self.polygons[poly_idx]
                    if vert_idx < len(p):
                        glVertex3f(*p[vert_idx])
            glEnd()
            glPointSize(1.0)
