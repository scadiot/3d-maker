"""Classe Scene : quads, UVs, texture, atlas, sélection."""

import copy
import json
import math
import pygame
from OpenGL.GL import (
    glGenTextures, glBindTexture, glTexImage2D, glTexParameteri,
    glEnable, glDisable, glCullFace, glFrontFace, glBegin, glEnd,
    glColor3f, glTexCoord2f, glVertex3f, glLineWidth,
    GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE, GL_LINEAR,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_CULL_FACE, GL_BACK, GL_CW, GL_QUADS, GL_LINE_LOOP,
)

from editor.constants import TEXTURE_PATH, PREVIEW_MAX_SZ
from editor import math3d


class Scene:
    def __init__(self):
        self.quads            = []
        self.quad_uvs         = []
        self.selected_idx     = -1
        self.selected_indices = set()
        self.groups           = []   # liste de sets d'indices formant des groupes

        self.quad_texture  = 0
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
        """Charge une texture PNG dans OpenGL. À appeler après pygame.display.set_mode."""
        surf = pygame.image.load(path).convert_alpha()
        w, h = surf.get_size()
        data = pygame.image.tobytes(surf, "RGBA", True)
        tex = glGenTextures(1);  glBindTexture(GL_TEXTURE_2D, tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.quad_texture = tex
        self.atlas_w, self.atlas_h = w, h

    # ── Gestion des quads ─────────────────────────────────────────────────────
    def add_quad(self, cam_pos, cam_yaw):
        import math as _math
        yr = _math.radians(cam_yaw)
        cx = round(cam_pos[0] - _math.sin(yr)*5)
        cz = round(cam_pos[2] - _math.cos(yr)*5)
        self.quads.append([
            (cx-1, 0.0, cz-1), (cx+1, 0.0, cz-1),
            (cx+1, 0.0, cz+1), (cx-1, 0.0, cz+1),
        ])
        self.quad_uvs.append([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])

    def rotate_uvs(self):
        """Décale circulairement les UVs des quads sélectionnés (v1→v2, v2→v3, …)."""
        for i in self.selected_indices:
            uvs = self.quad_uvs[i]
            self.quad_uvs[i] = [uvs[3], uvs[0], uvs[1], uvs[2]]

    def delete_selected(self):
        deleted = set(self.selected_indices)
        for i in sorted(deleted, reverse=True):
            self.quads.pop(i)
            self.quad_uvs.pop(i)
        self._reindex_after_delete(deleted)
        self.selected_idx     = -1
        self.selected_indices = set()

    def duplicate_selected(self):
        if not self.selected_indices:
            return
        first_new = len(self.quads)
        sorted_sel = sorted(self.selected_indices)
        # old_idx -> new_idx
        idx_map = {old: first_new + i for i, old in enumerate(sorted_sel)}
        for i in sorted_sel:
            self.quads.append(copy.deepcopy(self.quads[i]))
            self.quad_uvs.append(list(self.quad_uvs[i]))
        # Reproduire les groupes pour les nouveaux quads
        for group in self.groups:
            new_group = {idx_map[i] for i in group if i in idx_map}
            if len(new_group) >= 2:
                self.groups.append(new_group)
        new_indices = set(range(first_new, len(self.quads)))
        self.selected_indices = new_indices
        self.selected_idx     = max(new_indices)

    # ── Sélection ─────────────────────────────────────────────────────────────
    def selection_center(self):
        """Barycentre de tous les quads sélectionnés."""
        indices = [i for i in self.selected_indices if i < len(self.quads)]
        if not indices:
            return math3d.quad_center(self.quads[self.selected_idx]) if self.selected_idx >= 0 else (0.0, 0.0, 0.0)
        cs = [math3d.quad_center(self.quads[i]) for i in indices]
        return (sum(c[0] for c in cs)/len(cs),
                sum(c[1] for c in cs)/len(cs),
                sum(c[2] for c in cs)/len(cs))

    def pick_quad(self, ray_o, ray_d):
        """Retourne l'indice du quad le plus proche sous le rayon, ou -1."""
        best_t, best_i = float('inf'), -1
        for i, q in enumerate(self.quads):
            t = math3d.ray_quad_intersect(ray_o, ray_d, q)
            if t is not None and t < best_t:
                best_t, best_i = t, i
        return best_i

    # ── Groupes ───────────────────────────────────────────────────────────────
    def get_group_for_quad(self, idx):
        """Retourne le set du groupe contenant ce quad, ou None."""
        for group in self.groups:
            if idx in group:
                return group
        return None

    def group_selected(self):
        """Groupe les quads sélectionnés (minimum 2)."""
        if len(self.selected_indices) < 2:
            return
        # Retirer les quads sélectionnés de leurs groupes existants
        for group in self.groups:
            group -= self.selected_indices
        self.groups = [g for g in self.groups if len(g) >= 2]
        self.groups.append(set(self.selected_indices))

    def ungroup_selected(self):
        """Dissocie les groupes contenant des quads sélectionnés."""
        self.groups = [g for g in self.groups
                       if not g.intersection(self.selected_indices)]

    def _reindex_after_delete(self, deleted_indices):
        """Met à jour les groupes après suppression de quads."""
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
        """Exporte la scène dans un fichier JSON (position, taille, axes, uvs)."""
        quads_data = []
        for quad, uvs in zip(self.quads, self.quad_uvs):
            center, wa, ha, hw, hh = math3d.quad_decompose(quad)
            quads_data.append({
                "position": [round(v, 6) for v in center],
                "size":     [round(hw * 2, 6), round(hh * 2, 6)],
                "x_axis":   [round(v, 6) for v in wa],
                "y_axis":   [round(v, 6) for v in ha],
                "uvs":      [[round(u, 6), round(v, 6)] for u, v in uvs],
            })
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"quads": quads_data}, f, indent=2, ensure_ascii=False)

    def load_json(self, path):
        """Importe une scène depuis un fichier JSON (ajoute aux quads existants)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        first_new = len(self.quads)
        for q in data.get("quads", []):
            center = tuple(q["position"])
            hw = q["size"][0] / 2
            hh = q["size"][1] / 2
            if "x_axis" in q and "y_axis" in q:
                wa = tuple(q["x_axis"])
                ha = tuple(q["y_axis"])
            else:
                wa, ha = math3d.perp_basis(tuple(q["orientation"]))
            self.quads.append(math3d.quad_compose(center, wa, ha, hw, hh))
            self.quad_uvs.append([tuple(uv) for uv in q["uvs"]])
        new_indices = set(range(first_new, len(self.quads)))
        if new_indices:
            self.selected_indices = new_indices
            self.selected_idx = max(new_indices)

    # ── Aperçu texture ────────────────────────────────────────────────────────
    def open_tex_preview(self):
        if self.tex_preview_win:
            return
        img = pygame.image.load(TEXTURE_PATH)
        self.tex_preview_sz = min(img.get_width(), PREVIEW_MAX_SZ)
        if img.get_width() != self.tex_preview_sz:
            img = pygame.transform.smoothscale(img, (self.tex_preview_sz, self.tex_preview_sz))
        self.tex_preview_win = pygame.Window("Aperçu texture",
                                             size=(self.tex_preview_sz, self.tex_preview_sz))
        self.tex_preview_win.get_surface().blit(img, (0, 0))
        self.tex_preview_win.flip()

    def close_tex_preview(self):
        if self.tex_preview_win:
            self.tex_preview_win.destroy()
            self.tex_preview_win = None

    def assign_uv_from_atlas_click(self, event_pos):
        """Applique les UVs de l'atlas au quad sélectionné selon le clic dans l'aperçu."""
        px = int(event_pos[0] * self.atlas_w / self.tex_preview_sz)
        py = int(event_pos[1] * self.atlas_h / self.tex_preview_sz)
        entry = next((e for e in self.atlas_data["images"]
                      if e["x"] <= px < e["x"]+e["width"]
                      and e["y"] <= py < e["y"]+e["height"]), None)
        if entry and self.selected_idx >= 0:
            u0 = entry["x"] / self.atlas_w
            u1 = (entry["x"] + entry["width"]) / self.atlas_w
            # V inversé : texture uploadée verticalement retournée
            v1 = 1.0 - entry["y"] / self.atlas_h
            v0 = 1.0 - (entry["y"] + entry["height"]) / self.atlas_h
            self.quad_uvs[self.selected_idx] = [(u0, v0), (u1, v0), (u1, v1), (u0, v1)]

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def draw(self):
        glEnable(GL_CULL_FACE);  glCullFace(GL_BACK);  glFrontFace(GL_CW)
        for i, quad in enumerate(self.quads):
            sel = (i in self.selected_indices)
            uvs = self.quad_uvs[i] if i < len(self.quad_uvs) else [(0,0),(1,0),(1,1),(0,1)]
            glEnable(GL_TEXTURE_2D);  glBindTexture(GL_TEXTURE_2D, self.quad_texture)
            glColor3f(1.0, 1.0, 1.0)
            glBegin(GL_QUADS)
            for (vx, vy, vz), (u, v) in zip(quad, uvs):
                glTexCoord2f(u, v);  glVertex3f(vx, vy, vz)
            glEnd()
            glDisable(GL_TEXTURE_2D)
            glLineWidth(2.5 if sel else 1.5)
            if sel:
                glColor3f(1.0, 0.15, 0.15)
            elif self.get_group_for_quad(i) is not None:
                glColor3f(0.2, 0.7, 1.0)
            else:
                glColor3f(1.0, 0.75, 0.35)
            glBegin(GL_LINE_LOOP)
            for vx, vy, vz in quad: glVertex3f(vx, vy, vz)
            glEnd()
        glLineWidth(1.0)
        glDisable(GL_CULL_FACE)
