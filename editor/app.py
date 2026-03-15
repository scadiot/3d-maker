"""Classe App : initialisation, boucle principale, gestion des événements."""

import tkinter as tk
from tkinter import filedialog

import pygame
import pygame_gui
from pygame.locals import (DOUBLEBUF, OPENGL, QUIT, KEYDOWN,
                           K_SPACE, K_c, K_DELETE, K_t, K_g, K_h, K_r)
from OpenGL.GL import (
    glEnable, glClearColor, glClear, glViewport,
    glMatrixMode, glLoadIdentity, glRotatef, glTranslatef,
    glGenTextures, glBindTexture, glTexImage2D, glTexParameteri, glDeleteTextures,
    GL_DEPTH_TEST, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_PROJECTION, GL_MODELVIEW, GL_TEXTURE_2D, GL_RGBA, GL_UNSIGNED_BYTE,
    GL_LINEAR, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
)
from OpenGL.GLU import gluPerspective

from editor.constants import (PANEL_WIDTH, VIEW_WIDTH, HEIGHT, TOTAL_WIDTH,
                               FOV, NEAR, FAR, ATLAS_JSON, TEXTURE_PATH)
from editor.camera   import Camera
from editor.scene    import Scene
from editor.gizmo    import Gizmo
from editor.renderer import draw_grid, begin_2d, end_2d, draw_rect, draw_texture


class App:
    def __init__(self):
        self.camera = Camera()
        self.scene  = Scene()
        self.gizmo  = Gizmo()

        self.running         = False
        self.clock           = None
        self.ui_manager      = None
        self.btn_add         = None
        self.btn_save        = None
        self.btn_load        = None
        self.btn_border_sel  = None
        self.btn_rapprocher  = None
        self.btn_create_quad = None
        self.border_selection_mode = False
        self.dropdown_snap   = None
        self.dropdown_scale_snap = None
        self.ui_tex     = 0
        self.ui_surface = None

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    def run(self):
        self._init()
        self.clock   = pygame.time.Clock()
        self.running = True
        while self.running:
            dt       = self.clock.tick(60) / 1000.0
            mx, my   = pygame.mouse.get_pos()
            in_3d    = mx >= PANEL_WIDTH
            self._handle_events(mx, my, in_3d)
            self._update(dt, mx, my, in_3d)
            self._render(dt)
        self._cleanup()

    def _init(self):
        pygame.init()
        pygame.display.set_mode((TOTAL_WIDTH, HEIGHT), DOUBLEBUF | OPENGL)
        pygame.display.set_caption("3D Viewer")
        glEnable(GL_DEPTH_TEST)
        glClearColor(0.08, 0.08, 0.12, 1.0)

        self.scene.load_atlas(ATLAS_JSON)
        self.scene.load_texture(TEXTURE_PATH)

        self.ui_surface = pygame.Surface((PANEL_WIDTH, HEIGHT), pygame.SRCALPHA)
        self.ui_manager = pygame_gui.UIManager((PANEL_WIDTH, HEIGHT))

        self.btn_add = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 15, 220, 36),
            text="Ajouter quad", manager=self.ui_manager)
        self.dropdown_snap = pygame_gui.elements.UIDropDownMenu(
            options_list=['1', '0.5', '0.25', '0.1', '0.05'],
            starting_option=str(self.gizmo.translate_snap),
            relative_rect=pygame.Rect(15, 60, 220, 36),
            manager=self.ui_manager)
        self.dropdown_scale_snap = pygame_gui.elements.UIDropDownMenu(
            options_list=['1', '0.5', '0.25', '0.1', '0.05'],
            starting_option=str(self.gizmo.scale_snap),
            relative_rect=pygame.Rect(15, 108, 220, 36),
            manager=self.ui_manager)
        self.btn_save = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 162, 220, 36),
            text="Enregistrer JSON", manager=self.ui_manager)
        self.btn_load = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 210, 220, 36),
            text="Charger JSON", manager=self.ui_manager)
        self.btn_border_sel = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 258, 220, 36),
            text="Sélection arête : OFF", manager=self.ui_manager)
        self.btn_rapprocher = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 306, 220, 36),
            text="Rapprocher", manager=self.ui_manager)
        self.btn_rapprocher.disable()
        self.btn_create_quad = pygame_gui.elements.UIButton(
            relative_rect=pygame.Rect(15, 354, 220, 36),
            text="Créer quad", manager=self.ui_manager)
        self.btn_create_quad.disable()
        self.ui_tex = glGenTextures(1)

    def _cleanup(self):
        self.scene.close_tex_preview()
        self.ui_manager.clear_and_reset()
        glDeleteTextures(1, [self.ui_tex])
        glDeleteTextures(1, [self.scene.quad_texture])
        pygame.quit()

    # ── Événements ────────────────────────────────────────────────────────────
    def _handle_events(self, mx, my, in_3d):
        for event in pygame.event.get():
            self.ui_manager.process_events(event)
            self._handle_ui_event(event)

            if event.type == QUIT:
                self.running = False

            elif event.type == KEYDOWN:
                self._handle_keyboard(event)

            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                in_preview = (self.scene.tex_preview_win
                              and getattr(event, 'window', None) is self.scene.tex_preview_win)
                if in_preview:
                    self.scene.assign_uv_from_atlas_click(event.pos)
                    self.scene.close_tex_preview()
                elif in_3d:
                    self._handle_mouse_down_3d(mx, my)

            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.gizmo.stop_drag()

            elif event.type == pygame.WINDOWCLOSE:
                if self.scene.tex_preview_win and event.window == self.scene.tex_preview_win:
                    self.scene.close_tex_preview()
                else:
                    self.running = False

    def _handle_ui_event(self, event):
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_add:
            self.scene.add_quad(self.camera.pos, self.camera.yaw)
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_save:
            self._save_json_dialog()
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_load:
            self._load_json_dialog()
        if (event.type == pygame_gui.UI_DROP_DOWN_MENU_CHANGED
                and event.ui_element == self.dropdown_snap):
            self.gizmo.translate_snap = float(event.text)
        if (event.type == pygame_gui.UI_DROP_DOWN_MENU_CHANGED
                and event.ui_element == self.dropdown_scale_snap):
            self.gizmo.scale_snap = float(event.text)
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_rapprocher:
            self.scene.rapprocher_edges()
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_create_quad:
            self.scene.create_quad_from_edges()
        if event.type == pygame_gui.UI_BUTTON_PRESSED and event.ui_element == self.btn_border_sel:
            self.border_selection_mode = not self.border_selection_mode
            if not self.border_selection_mode:
                self.scene.selected_edges.clear()
                self.scene.selected_edges_ordered.clear()
            label = "Sélection arête : ON" if self.border_selection_mode else "Sélection arête : OFF"
            self.btn_border_sel.set_text(label)

    def _handle_keyboard(self, event):
        if event.key == K_t and self.scene.selected_idx >= 0:
            if self.scene.tex_preview_win:
                self.scene.close_tex_preview()
            else:
                self.scene.open_tex_preview()

        if event.key == K_DELETE and self.scene.selected_indices:
            self.scene.delete_selected()
            self.gizmo.stop_drag()

        if event.key == K_c:
            self.scene.duplicate_selected()

        if event.key == K_SPACE and self.scene.selected_indices:
            self.gizmo.cycle_mode(len(self.scene.selected_indices) > 1)

        if event.key == K_g and len(self.scene.selected_indices) >= 2:
            self.scene.group_selected()

        if event.key == K_h and self.scene.selected_indices:
            self.scene.ungroup_selected()

        if event.key == K_r and self.scene.selected_indices:
            self.scene.rotate_uvs()

    def _handle_mouse_down_3d(self, mx, my):
        ctrl_held = bool(pygame.key.get_mods() & pygame.KMOD_CTRL)
        multi     = len(self.scene.selected_indices) > 1

        if self.gizmo.mode == 'translate' or (multi and self.gizmo.mode == 'scale'):
            axis = self.gizmo.pick_translate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            elif self.border_selection_mode:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_quad(mx, my), ctrl_held)

        elif self.gizmo.mode == 'rotate':
            axis = self.gizmo.pick_rotate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            elif self.border_selection_mode:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_quad(mx, my), ctrl_held)
                if len(self.scene.selected_indices) <= 1:
                    self.gizmo.mode = 'translate'

        else:  # scale (sélection unique)
            handle = self.gizmo.pick_scale_handle(mx, my, self.scene, self.camera)
            if handle:
                self.gizmo.start_drag(handle, mx, my, self.scene, self.camera)
            elif self.border_selection_mode:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_quad(mx, my), ctrl_held)
                if len(self.scene.selected_indices) <= 1:
                    self.gizmo.mode = 'translate'

    def _save_json_dialog(self):
        root = tk.Tk()
        root.withdraw()
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Enregistrer la scène",
        )
        root.destroy()
        if path:
            self.scene.save_json(path)

    def _load_json_dialog(self):
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            filetypes=[("JSON", "*.json")],
            title="Charger une scène",
        )
        root.destroy()
        if path:
            self.scene.load_json(path)
            self.gizmo.stop_drag()

    def _pick_quad(self, mx, my):
        ray_o = tuple(self.camera.pos)
        ray_d = self.camera.screen_ray(mx - PANEL_WIDTH, my)
        return self.scene.pick_quad(ray_o, ray_d)

    def _pick_edge(self, mx, my):
        ray_o = tuple(self.camera.pos)
        ray_d = self.camera.screen_ray(mx - PANEL_WIDTH, my)
        return self.scene.pick_edge(ray_o, ray_d)

    def _apply_edge_selection(self, edge, ctrl_held):
        if edge is None:
            if not ctrl_held:
                self.scene.selected_edges.clear()
                self.scene.selected_edges_ordered.clear()
            return
        if ctrl_held:
            if edge in self.scene.selected_edges:
                self.scene.selected_edges.discard(edge)
                self.scene.selected_edges_ordered.remove(edge)
            else:
                self.scene.selected_edges.add(edge)
                self.scene.selected_edges_ordered.append(edge)
        else:
            self.scene.selected_edges = {edge}
            self.scene.selected_edges_ordered = [edge]

    def _apply_selection(self, clicked_idx, ctrl_held):
        """Applique la sélection selon Ctrl, en expandant aux groupes."""
        group = self.scene.get_group_for_quad(clicked_idx) if clicked_idx >= 0 else None
        to_select = group if group else ({clicked_idx} if clicked_idx >= 0 else set())

        if ctrl_held:
            if clicked_idx >= 0:
                if clicked_idx in self.scene.selected_indices:
                    self.scene.selected_indices -= to_select
                    self.scene.selected_idx = next(iter(self.scene.selected_indices), -1)
                else:
                    self.scene.selected_indices |= to_select
                    self.scene.selected_idx = clicked_idx
            # Ctrl+clic dans le vide : on ne désélectionne pas
        else:
            self.scene.selected_idx     = clicked_idx
            self.scene.selected_indices = set(to_select) if clicked_idx >= 0 else set()

    # ── Mise à jour ───────────────────────────────────────────────────────────
    def _update(self, dt, mx, my, in_3d):
        edges = self.scene.selected_edges_ordered
        two_diff = len(edges) == 2 and edges[0][0] != edges[1][0]
        if two_diff:
            self.btn_rapprocher.enable()
            self.btn_create_quad.enable()
        else:
            self.btn_rapprocher.disable()
            self.btn_create_quad.disable()

        if self.gizmo.dragging_axis and pygame.mouse.get_pressed()[0]:
            self.gizmo.update_drag(mx, my, self.scene, self.camera)

        dx, dy = pygame.mouse.get_rel()
        if pygame.mouse.get_pressed()[1] and in_3d:
            self.camera.apply_mouse_look(dx, dy)

        keys = pygame.key.get_pressed()
        self.camera.apply_movement(keys, dt)

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def _render(self, dt):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # 3D
        glViewport(PANEL_WIDTH, 0, VIEW_WIDTH, HEIGHT)
        glMatrixMode(GL_PROJECTION);  glLoadIdentity()
        gluPerspective(FOV, VIEW_WIDTH/HEIGHT, NEAR, FAR)
        glMatrixMode(GL_MODELVIEW);   glLoadIdentity()
        glRotatef(-self.camera.pitch, 1, 0, 0)
        glRotatef(-self.camera.yaw,   0, 1, 0)
        glTranslatef(-self.camera.pos[0], -self.camera.pos[1], -self.camera.pos[2])

        draw_grid(30, 1)
        self.scene.draw()
        self.gizmo.draw(self.scene, self.camera)

        # 2D UI
        self.ui_manager.update(dt)
        self.ui_surface.fill((0, 0, 0, 0))
        self.ui_manager.draw_ui(self.ui_surface)
        data = pygame.image.tobytes(self.ui_surface, "RGBA", True)
        glBindTexture(GL_TEXTURE_2D, self.ui_tex)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, PANEL_WIDTH, HEIGHT, 0,
                     GL_RGBA, GL_UNSIGNED_BYTE, data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_2D, 0)

        begin_2d()
        draw_rect(0, 0, PANEL_WIDTH, HEIGHT, 0.10, 0.10, 0.13)
        draw_texture(self.ui_tex, 0, 0, PANEL_WIDTH, HEIGHT)
        draw_rect(PANEL_WIDTH-1, 0, 1, HEIGHT, 0.22, 0.22, 0.28)
        end_2d()

        pygame.display.flip()
