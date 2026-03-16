"""Classe App : initialisation Tkinter/pyopengltk, boucle principale, gestion des événements."""

import math
import time
import ctypes
import tkinter as tk
from tkinter import filedialog
from PIL import Image, ImageDraw, ImageTk

from pyopengltk import OpenGLFrame
from OpenGL.GL import (
    glEnable, glClearColor, glClear, glViewport,
    glMatrixMode, glLoadIdentity, glRotatef, glTranslatef,
    GL_DEPTH_TEST, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_PROJECTION, GL_MODELVIEW,
)
from OpenGL.GLU import gluPerspective

from editor.constants import (PANEL_WIDTH, VIEW_WIDTH, HEIGHT,
                               FOV, NEAR, FAR, ATLAS_JSON, TEXTURE_PATH)

SNAP_VALUES = ["1", "0.5", "0.25", "0.1", "0.05", "0.01"]
from editor.camera   import Camera
from editor.scene    import Scene
from editor.gizmo    import Gizmo
from editor.renderer import draw_grid


class Viewport3D(OpenGLFrame):
    """Widget OpenGL intégré dans Tkinter via pyopengltk."""

    def __init__(self, master, app, **kw):
        super().__init__(master, **kw)
        self._app = app

    def initgl(self):
        glEnable(GL_DEPTH_TEST)
        glClearColor(0.08, 0.08, 0.12, 1.0)
        self._app.scene.load_texture(TEXTURE_PATH)

    def redraw(self):
        self._app._render()


class App:
    def __init__(self):
        self.camera         = Camera()
        self.scene          = Scene()
        self.gizmo          = Gizmo()
        self.selection_mode = 'polygon'
        self.panning        = False
        self.pan_last_x     = 0
        self.pan_last_y     = 0
        self.keys_pressed   = set()
        self.mouse_btn1     = False
        self.mouse_x        = 0
        self.mouse_y        = 0
        self.last_time      = time.time()

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    def run(self):
        self.root = tk.Tk()
        self.root.title("3D Viewer")
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.sel_mode_var = tk.StringVar(value='Polygon')
        self._build_menu()
        self._build_toolbar()
        self._build_toolbar2()
        self._build_panel()
        self._build_viewport()
        self._bind_events()

        self.scene.load_atlas(ATLAS_JSON)
        self.viewport.animate = 1
        self._update_loop()
        self.root.mainloop()

    def _on_close(self):
        self.scene.close_tex_preview()
        self.root.destroy()

    # ── Barre de menus ────────────────────────────────────────────────────────
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        # ── File ──────────────────────────────────────────────────────────────
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="Enregistrer JSON…", accelerator="",
                           command=self._save_json_dialog)
        m_file.add_command(label="Charger JSON…",
                           command=self._load_json_dialog)
        m_file.add_separator()
        m_file.add_command(label="Quitter", accelerator="Échap",
                           command=self._on_close)
        menubar.add_cascade(label="File", menu=m_file)

        # ── Edit ──────────────────────────────────────────────────────────────
        m_edit = tk.Menu(menubar, tearoff=0)
        m_edit.add_command(label="Dupliquer", accelerator="C",
                           command=self.scene.duplicate_selected)
        m_edit.add_command(label="Supprimer", accelerator="Suppr",
                           command=lambda: (self.scene.delete_selected(), self.gizmo.stop_drag())
                           if self.scene.selected_indices else None)
        m_edit.add_separator()
        m_edit.add_command(label="Grouper", accelerator="G",
                           command=self.scene.group_selected)
        m_edit.add_command(label="Dégrouper", accelerator="H",
                           command=self.scene.ungroup_selected)
        menubar.add_cascade(label="Edit", menu=m_edit)

        # ── Polygon ───────────────────────────────────────────────────────────
        m_poly = tk.Menu(menubar, tearoff=0)
        m_poly.add_command(label="Ajouter polygon",
                           command=lambda: self.scene.add_polygon(self.camera.pos, self.camera.yaw))
        m_poly.add_command(label="Ajouter triangle",
                           command=lambda: self.scene.add_triangle(self.camera.pos, self.camera.yaw))
        m_poly.add_separator()
        m_poly.add_command(label="Inverser orientation", accelerator="N",
                           command=self.scene.flip_orientation)
        m_poly.add_command(label="Rotation UVs", accelerator="R",
                           command=self.scene.rotate_uvs)
        m_poly.add_separator()
        m_poly.add_command(label="Rapprocher arêtes",
                           command=self.scene.rapprocher_edges)
        m_poly.add_command(label="Créer polygon depuis arêtes",
                           command=self.scene.create_polygon_from_edges)
        menubar.add_cascade(label="Polygon", menu=m_poly)

        self.root.config(menu=menubar)

    # ── Barre d'outils ────────────────────────────────────────────────────────
    def _build_toolbar(self):
        BG      = '#16161f'
        BG_ACT  = '#2a2a3a'
        BG_ON   = '#2d4080'
        IC      = '#c8c8d8'   # couleur icône
        SZ      = 22           # taille icône en px
        BTN_SZ  = 34           # taille bouton

        self._icons       = []   # garde les PhotoImage en vie
        self._gizmo_btns  = {}   # boutons gizmo pour le highlighting
        self._sel_btns    = {}   # boutons mode sélection

        self.toolbar = tk.Frame(self.root, bg=BG, height=BTN_SZ + 4)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.toolbar.pack_propagate(False)

        # ── Fabrique d'icône ──────────────────────────────────────────────────
        def make_icon(draw_fn):
            img = Image.new('RGBA', (SZ, SZ), (0, 0, 0, 0))
            draw_fn(ImageDraw.Draw(img), SZ, IC)
            ph = ImageTk.PhotoImage(img)
            self._icons.append(ph)
            return ph

        # ── Fabrique de bouton avec tooltip au survol ─────────────────────────
        def add_btn(icon, cmd, label='', shortcut=''):
            btn = tk.Button(
                self.toolbar, image=icon, command=cmd,
                bg=BG, activebackground=BG_ACT,
                relief='flat', bd=0,
                width=BTN_SZ, height=BTN_SZ,
                cursor='hand2',
            )
            btn.pack(side=tk.LEFT, padx=1, pady=2)

            tip_text = f"{label} [{shortcut}]" if shortcut else label
            tip_win  = [None]

            def show_tip(_e):
                if tip_win[0] or not tip_text:
                    return
                x = btn.winfo_rootx() + BTN_SZ // 2
                y = btn.winfo_rooty() + BTN_SZ + 6
                w = tk.Toplevel(self.root)
                w.wm_overrideredirect(True)
                w.wm_geometry(f"+{x}+{y}")
                tk.Label(w, text=tip_text, bg='#2a2a3a', fg='#c8c8d8',
                         font=('Segoe UI', 8), relief='flat', bd=1,
                         padx=6, pady=3).pack()
                tip_win[0] = w

            def hide_tip(_e):
                if tip_win[0]:
                    tip_win[0].destroy()
                    tip_win[0] = None

            btn.bind('<Enter>', show_tip)
            btn.bind('<Leave>', hide_tip)
            btn.bind('<ButtonPress>', hide_tip)
            btn.bind('<Enter>', lambda _e, b=btn: b.config(bg=BG_ACT) if b['bg'] != BG_ON else None, add='+')
            btn.bind('<Leave>', lambda _e, b=btn: b.config(bg=BG) if b['bg'] == BG_ACT else None, add='+')
            return btn

        def add_sep():
            tk.Frame(self.toolbar, width=1, bg='#38384a').pack(
                side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        # ── Dessins des icônes ────────────────────────────────────────────────
        def ico_save(d, s, c):
            d.rectangle([3, 4, s-3, s-3], outline=c, width=1)
            d.rectangle([5, 3, s-7, 8],   fill=c)               # étiquette
            d.rectangle([s-8, 3, s-5, 7], fill='#16161f')        # fenêtre étiquette
            d.rectangle([6, 13, s-6, s-4], outline=c, width=1)  # poche

        def ico_load(d, s, c):
            d.rectangle([3, 7, s-3, s-3], outline=c, width=1)
            d.polygon([3, 7, 3, 4, 9, 4, 11, 7], outline=c, fill='#16161f')
            d.line([3, 7, 11, 7], fill=c, width=1)

        def ico_polygon(d, s, c):
            r, cx, cy = s/2 - 3, s/2, s/2
            pts = [(cx + r*math.cos(2*math.pi*i/5 - math.pi/2),
                    cy + r*math.sin(2*math.pi*i/5 - math.pi/2)) for i in range(5)]
            d.polygon(pts, outline=c)

        def ico_triangle(d, s, c):
            d.polygon([s/2, 3, s-3, s-3, 3, s-3], outline=c)

        def ico_duplicate(d, s, c):
            d.rectangle([5, 8, s-4, s-3], outline=c, width=1)
            d.rectangle([3, 3, s-6, s-6], outline=c, width=1)
            d.rectangle([s-5, 3, s-6+1, s-6+1], fill='#16161f')  # efface angle

        def ico_delete(d, s, c):
            d.rectangle([4, 7, s-4, s-3], outline=c, width=1)
            d.line([4, 7, s-4, 7], fill=c, width=1)
            d.rectangle([7, 4, s-7, 7], outline=c, width=1)       # poignée
            d.line([8, 11, 8, s-5],  fill=c, width=1)             # fente g
            d.line([s-8, 11, s-8, s-5], fill=c, width=1)          # fente d

        def ico_group(d, s, c):
            d.line([4, 4, 4, s-4],   fill=c, width=2)             # crochet g
            d.line([4, 4, 7, 4],     fill=c, width=2)
            d.line([4, s-4, 7, s-4], fill=c, width=2)
            d.line([s-4, 4, s-4, s-4],   fill=c, width=2)         # crochet d
            d.line([s-7, 4, s-4, 4],     fill=c, width=2)
            d.line([s-7, s-4, s-4, s-4], fill=c, width=2)
            d.line([7, s//2, s-7, s//2], fill=c, width=1)         # liaison

        def ico_ungroup(d, s, c):
            d.line([4, 4, 4, s//2-3],   fill=c, width=2)
            d.line([4, 4, 7, 4],        fill=c, width=2)
            d.line([4, s//2+3, 4, s-4], fill=c, width=2)
            d.line([4, s-4, 7, s-4],    fill=c, width=2)
            d.line([s-4, 4, s-4, s//2-3],   fill=c, width=2)
            d.line([s-7, 4, s-4, 4],        fill=c, width=2)
            d.line([s-4, s//2+3, s-4, s-4], fill=c, width=2)
            d.line([s-7, s-4, s-4, s-4],    fill=c, width=2)

        def ico_translate(d, s, c):
            cx, cy, a = s//2, s//2, 6
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                ex, ey = cx + dx*a, cy + dy*a
                d.line([cx, cy, ex, ey], fill=c, width=1)
                nx, ny = -dy, dx
                d.polygon([ex, ey,
                            ex - dx*3 + nx*2, ey - dy*3 + ny*2,
                            ex - dx*3 - nx*2, ey - dy*3 - ny*2], fill=c)

        def ico_rotate(d, s, c):
            r = s//2 - 3
            cx, cy = s//2, s//2
            d.arc([cx-r, cy-r, cx+r, cy+r], start=30, end=300, fill=c, width=1)
            ax = cx + r * math.cos(math.radians(30))
            ay = cy + r * math.sin(math.radians(30))
            d.polygon([ax, ay, ax-4, ay-1, ax-1, ay+4], fill=c)

        def ico_scale(d, s, c):
            d.line([3, s-3, s-3, 3], fill=c, width=1)
            d.polygon([3, s-3, 3, s-8, 8, s-3], fill=c)
            d.polygon([s-3, 3, s-3, 8, s-8, 3], fill=c)

        def ico_sel_polygon(d, s, c):
            # Face sélectionnée : carré avec remplissage tamisé + contour fort
            d.rectangle([4, 4, s-4, s-4], fill='#404060', outline=c, width=2)

        def ico_sel_edge(d, s, c):
            # Polygone gris + une arête mise en valeur
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline='#505065')
            d.line([s//2, 3, s-3, s-3], fill=c, width=3)

        def ico_sel_vertex(d, s, c):
            # Polygone gris + un sommet mis en valeur
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline='#505065')
            r = 3
            cx, cy = s//2, 3
            d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=c)

        # ── Placement ─────────────────────────────────────────────────────────
        add_btn(make_icon(ico_save),      self._save_json_dialog,  "Enregistrer")
        add_btn(make_icon(ico_load),      self._load_json_dialog,  "Charger")
        add_sep()
        add_btn(make_icon(ico_polygon),   lambda: self.scene.add_polygon(self.camera.pos, self.camera.yaw),  "Polygon")
        add_btn(make_icon(ico_triangle),  lambda: self.scene.add_triangle(self.camera.pos, self.camera.yaw), "Triangle")
        add_sep()
        add_btn(make_icon(ico_duplicate), self.scene.duplicate_selected, "Dupliquer", "C")
        add_btn(make_icon(ico_delete),
                lambda: (self.scene.delete_selected(), self.gizmo.stop_drag())
                if self.scene.selected_indices else None,
                "Supprimer", "Suppr")
        add_sep()
        add_btn(make_icon(ico_group),   self.scene.group_selected,   "Grouper",   "G")
        add_btn(make_icon(ico_ungroup), self.scene.ungroup_selected, "Dégrouper", "H")
        add_sep()

        # Boutons gizmo (radio-style) — mis en valeur selon self.gizmo.mode
        def set_gizmo(mode):
            self.gizmo.mode = mode
            self._sync_gizmo_btns()

        for mode, ifn, lbl in [('translate', ico_translate, "Translater"),
                                ('rotate',    ico_rotate,    "Rotation"),
                                ('scale',     ico_scale,     "Échelle")]:
            b = add_btn(make_icon(ifn), lambda m=mode: set_gizmo(m), lbl, "Espace")
            self._gizmo_btns[mode] = (b, BG, BG_ON)

        self._sync_gizmo_btns()
        add_sep()

        # Boutons mode sélection (radio-style)
        def set_sel_mode(mode):
            self.sel_mode_var.set({'polygon': 'Polygon', 'edge': 'Arête', 'vertex': 'Vertex'}[mode])
            self._on_selection_mode_change()

        for mode, ifn, lbl in [('polygon', ico_sel_polygon, "Polygon"),
                                ('edge',    ico_sel_edge,    "Arête"),
                                ('vertex',  ico_sel_vertex,  "Vertex")]:
            b = add_btn(make_icon(ifn), lambda m=mode: set_sel_mode(m), lbl, "E")
            self._sel_btns[mode] = (b, BG, BG_ON)

        self._sync_sel_mode_btns()
        add_sep()

        # ── Snap ──────────────────────────────────────────────────────────────
        tk.Label(self.toolbar, text="Snap :", bg=BG, fg='#c8c8d8',
                 font=('Segoe UI', 8)).pack(side=tk.LEFT, padx=(4, 2))

        self._snap_var = tk.StringVar(value=str(self.gizmo.translate_snap))
        snap_menu = tk.OptionMenu(self.toolbar, self._snap_var, *SNAP_VALUES,
                                  command=self._on_snap_change)
        snap_menu.config(bg=BG, fg='#c8c8d8',
                         activebackground=BG_ACT, activeforeground='#c8c8d8',
                         highlightthickness=0, relief='flat', bd=0,
                         font=('Segoe UI', 8), width=4)
        snap_menu['menu'].config(bg='#2a2a3a', fg='#c8c8d8',
                                 activebackground='#2d4080',
                                 activeforeground='#c8c8d8')
        snap_menu.pack(side=tk.LEFT, padx=2, pady=4)

    # ── Deuxième barre d'outils ───────────────────────────────────────────────
    def _build_toolbar2(self):
        BG      = '#16161f'
        BG_ACT  = '#2a2a3a'
        IC      = '#c8c8d8'
        SZ      = 22
        BTN_SZ  = 34

        self.toolbar2 = tk.Frame(self.root, bg=BG, height=BTN_SZ + 4)
        self.toolbar2.pack(side=tk.TOP, fill=tk.X)
        self.toolbar2.pack_propagate(False)

        def make_icon(draw_fn):
            img = Image.new('RGBA', (SZ, SZ), (0, 0, 0, 0))
            draw_fn(ImageDraw.Draw(img), SZ, IC)
            ph = ImageTk.PhotoImage(img)
            self._icons.append(ph)
            return ph

        def add_btn(icon, cmd, label='', shortcut=''):
            btn = tk.Button(
                self.toolbar2, image=icon, command=cmd,
                bg=BG, activebackground=BG_ACT,
                relief='flat', bd=0,
                width=BTN_SZ, height=BTN_SZ,
                cursor='hand2',
            )
            btn.pack(side=tk.LEFT, padx=1, pady=2)

            tip_text = f"{label} [{shortcut}]" if shortcut else label
            tip_win  = [None]

            def show_tip(_e):
                if tip_win[0] or not tip_text:
                    return
                x = btn.winfo_rootx() + BTN_SZ // 2
                y = btn.winfo_rooty() + BTN_SZ + 6
                w = tk.Toplevel(self.root)
                w.wm_overrideredirect(True)
                w.wm_geometry(f"+{x}+{y}")
                tk.Label(w, text=tip_text, bg='#2a2a3a', fg='#c8c8d8',
                         font=('Segoe UI', 8), relief='flat', bd=1,
                         padx=6, pady=3).pack()
                tip_win[0] = w

            def hide_tip(_e):
                if tip_win[0]:
                    tip_win[0].destroy()
                    tip_win[0] = None

            btn.bind('<Enter>', show_tip)
            btn.bind('<Leave>', hide_tip)
            btn.bind('<ButtonPress>', hide_tip)
            btn.bind('<Enter>', lambda _e, b=btn: b.config(bg=BG_ACT), add='+')
            btn.bind('<Leave>', lambda _e, b=btn: b.config(bg=BG), add='+')
            return btn

        def add_sep():
            tk.Frame(self.toolbar2, width=1, bg='#38384a').pack(
                side=tk.LEFT, fill=tk.Y, padx=5, pady=5)

        # ── Icônes ────────────────────────────────────────────────────────────
        def ico_flip(d, s, c):
            cx = s // 2
            d.line([cx, 3, cx, s-3], fill=c, width=2)
            pts_l = [3, s//2, cx-2, 4, cx-2, s-4]
            d.polygon(pts_l, outline=c)
            pts_r = [s-3, s//2, cx+2, s-4, cx+2, 4]
            d.polygon(pts_r, fill=c)

        def ico_rotate_uv(d, s, c):
            r = s//2 - 3
            cx, cy = s//2, s//2
            d.arc([cx-r, cy-r, cx+r, cy+r], start=60, end=330, fill=c, width=1)
            ax = cx + r * math.cos(math.radians(60))
            ay = cy + r * math.sin(math.radians(60))
            d.polygon([ax, ay, ax+4, ay-1, ax+1, ay+4], fill=c)
            d.rectangle([cx-3, cy-3, cx+3, cy+3], outline=c, width=1)

        def ico_rapprocher(d, s, c):
            m = s // 2
            d.line([3, m-4, s-3, m-4], fill=c, width=1)
            d.line([3, m+4, s-3, m+4], fill=c, width=1)
            d.line([m, m-4, m, m+4],   fill=c, width=2)
            d.polygon([m, m-1, m-3, m-5, m+3, m-5], fill=c)
            d.polygon([m, m+1, m-3, m+5, m+3, m+5], fill=c)

        def ico_create_from_edges(d, s, c):
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline=c, width=2)
            r = 3
            for px, py in [(s//2, 3), (s-3, s-3), (3, s-3)]:
                d.ellipse([px-r, py-r, px+r, py+r], fill=c)

        # ── Placement ─────────────────────────────────────────────────────────
        add_btn(make_icon(ico_flip),
                self.scene.flip_orientation,
                "Inverser orientation", "N")
        add_btn(make_icon(ico_rotate_uv),
                self.scene.rotate_uvs,
                "Rotation UVs", "R")
        add_sep()
        add_btn(make_icon(ico_rapprocher),
                self.scene.rapprocher_edges,
                "Rapprocher arêtes")
        add_btn(make_icon(ico_create_from_edges),
                self.scene.create_polygon_from_edges,
                "Créer polygon depuis arêtes")

    def _on_snap_change(self, *_):
        v = float(self._snap_var.get())
        self.gizmo.translate_snap = v
        self.gizmo.scale_snap     = v

    def _sync_gizmo_btns(self):
        for mode, (btn, bg_off, bg_on) in self._gizmo_btns.items():
            btn.config(bg=bg_on if self.gizmo.mode == mode else bg_off)

    def _sync_sel_mode_btns(self):
        for mode, (btn, bg_off, bg_on) in self._sel_btns.items():
            btn.config(bg=bg_on if self.selection_mode == mode else bg_off)

    # ── Construction de l'interface ───────────────────────────────────────────
    def _build_panel(self):
        self.panel = tk.Frame(self.root, width=PANEL_WIDTH, bg='#1a1a21')
        self.panel.pack(side=tk.LEFT, fill=tk.Y)
        self.panel.pack_propagate(False)

    def _build_viewport(self):
        self.viewport = Viewport3D(self.root, self, width=VIEW_WIDTH, height=HEIGHT)
        self.viewport.pack(side=tk.LEFT)

    # ── Bindings ──────────────────────────────────────────────────────────────
    def _bind_events(self):
        self.viewport.bind('<Button-1>',        self._on_mouse_down)
        self.viewport.bind('<ButtonRelease-1>', self._on_mouse_up)
        self.viewport.bind('<Button-2>',        self._on_middle_down)
        self.viewport.bind('<ButtonRelease-2>', self._on_middle_up)
        self.viewport.bind('<Motion>',          self._on_mouse_motion)
        self.viewport.bind('<MouseWheel>',      self._on_mouse_wheel)
        self.root.bind('<KeyPress>',            self._on_key_press)
        self.root.bind('<KeyRelease>',          self._on_key_release)

    # ── Événements souris ─────────────────────────────────────────────────────
    def _on_mouse_down(self, event):
        self.mouse_btn1 = True
        self.mouse_x, self.mouse_y = event.x, event.y
        self._handle_mouse_down_3d(event.x, event.y)

    def _on_mouse_up(self, event):
        self.mouse_btn1 = False
        self.gizmo.stop_drag()

    def _on_mouse_wheel(self, event):
        self.camera.apply_scroll(event.delta / 120)

    def _on_middle_down(self, event):
        self.panning = True
        self.pan_last_x = event.x_root
        self.pan_last_y = event.y_root
        self.viewport.config(cursor='none')

    def _on_middle_up(self, event):
        self.panning = False
        self.viewport.config(cursor='')

    def _on_mouse_motion(self, event):
        self.mouse_x, self.mouse_y = event.x, event.y
        if self.panning:
            dx = event.x_root - self.pan_last_x
            dy = event.y_root - self.pan_last_y
            if dx or dy:
                self.camera.apply_mouse_look(dx, dy)
                cx = self.viewport.winfo_rootx() + VIEW_WIDTH // 2
                cy = self.viewport.winfo_rooty() + HEIGHT // 2
                ctypes.windll.user32.SetCursorPos(cx, cy)
                self.pan_last_x = cx
                self.pan_last_y = cy

    # ── Événements clavier ────────────────────────────────────────────────────
    def _on_key_press(self, event):
        key = event.keysym.lower()
        self.keys_pressed.add(key)
        self._handle_keyboard(key)

    def _on_key_release(self, event):
        self.keys_pressed.discard(event.keysym.lower())

    def _on_selection_mode_change(self, event=None):
        mode_map = {'Polygon': 'polygon', 'Arête': 'edge', 'Vertex': 'vertex'}
        self.selection_mode = mode_map[self.sel_mode_var.get()]
        if self.selection_mode != 'edge':
            self.scene.selected_edges.clear()
            self.scene.selected_edges_ordered.clear()
        if self.selection_mode != 'vertex':
            self.scene.selected_vertices.clear()
        self._sync_sel_mode_btns()

    def _handle_keyboard(self, key):
        if key == 't' and self.scene.selected_idx >= 0:
            if self.scene.tex_preview_win:
                self.scene.close_tex_preview()
            else:
                self.scene.open_tex_preview(self.root)

        if key == 'delete' and self.scene.selected_indices:
            self.scene.delete_selected()
            self.gizmo.stop_drag()

        if key == 'c':
            self.scene.duplicate_selected()

        if key == 'space' and self.scene.selected_indices:
            self.gizmo.cycle_mode(len(self.scene.selected_indices) > 1)
            self._sync_gizmo_btns()

        if key == 'g' and len(self.scene.selected_indices) >= 2:
            self.scene.group_selected()

        if key == 'h' and self.scene.selected_indices:
            self.scene.ungroup_selected()

        if key == 'r' and self.scene.selected_indices:
            self.scene.rotate_uvs()

        if key == 'n' and self.scene.selected_indices:
            self.scene.flip_orientation()

        if key == 'e':
            modes = ['polygon', 'edge', 'vertex']
            next_mode = modes[(modes.index(self.selection_mode) + 1) % len(modes)]
            self.sel_mode_var.set({'polygon': 'Polygon', 'edge': 'Arête', 'vertex': 'Vertex'}[next_mode])
            self._on_selection_mode_change()

        if key in ('prior', 'next'):   # Page Up / Page Down
            idx = SNAP_VALUES.index(self._snap_var.get()) if self._snap_var.get() in SNAP_VALUES else 0
            if key == 'prior' and idx > 0:
                self._snap_var.set(SNAP_VALUES[idx - 1])
            elif key == 'next' and idx < len(SNAP_VALUES) - 1:
                self._snap_var.set(SNAP_VALUES[idx + 1])
            self._on_snap_change()

        if key == 'escape':
            self._on_close()

    def _handle_mouse_down_3d(self, mx, my):
        ctrl_held = 'shift_l' in self.keys_pressed
        multi     = len(self.scene.selected_indices) > 1

        if self.selection_mode == 'edge' and self.scene.selected_edges:
            axis = self.gizmo.pick_translate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            else:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            return

        if self.selection_mode == 'vertex' and self.scene.selected_vertices:
            axis = self.gizmo.pick_translate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            else:
                self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if self.selection_mode == 'vertex':
            self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if self.gizmo.mode == 'translate' or (multi and self.gizmo.mode == 'scale'):
            axis = self.gizmo.pick_translate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            elif self.selection_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)

        elif self.gizmo.mode == 'rotate':
            axis = self.gizmo.pick_rotate_axis(mx, my, self.scene, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.scene, self.camera)
            elif self.selection_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)
                if len(self.scene.selected_indices) <= 1:
                    self.gizmo.mode = 'translate'

        else:  # scale
            handle = self.gizmo.pick_scale_handle(mx, my, self.scene, self.camera)
            if handle:
                self.gizmo.start_drag(handle, mx, my, self.scene, self.camera)
            elif self.selection_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)
                if len(self.scene.selected_indices) <= 1:
                    self.gizmo.mode = 'translate'

    def _save_json_dialog(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Enregistrer la scène",
        )
        if path:
            self.scene.save_json(path)

    def _load_json_dialog(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON", "*.json")],
            title="Charger une scène",
        )
        if path:
            self.scene.load_json(path)
            self.gizmo.stop_drag()

    def _pick_polygon(self, mx, my):
        return self.scene.pick_polygon(tuple(self.camera.pos), self.camera.screen_ray(mx, my))

    def _pick_edge(self, mx, my):
        return self.scene.pick_edge(tuple(self.camera.pos), self.camera.screen_ray(mx, my))

    def _pick_vertex(self, mx, my):
        return self.scene.pick_vertex(tuple(self.camera.pos), self.camera.screen_ray(mx, my))

    def _apply_vertex_selection(self, vertex, ctrl_held):
        if vertex is None:
            if not ctrl_held:
                self.scene.selected_vertices.clear()
            return
        if ctrl_held:
            if vertex in self.scene.selected_vertices:
                self.scene.selected_vertices.discard(vertex)
            else:
                self.scene.selected_vertices.add(vertex)
        else:
            self.scene.selected_vertices = {vertex}

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
        group = self.scene.get_group_for_polygon(clicked_idx) if clicked_idx >= 0 else None
        to_select = group if group else ({clicked_idx} if clicked_idx >= 0 else set())

        if ctrl_held:
            if clicked_idx >= 0:
                if clicked_idx in self.scene.selected_indices:
                    self.scene.selected_indices -= to_select
                    self.scene.selected_idx = next(iter(self.scene.selected_indices), -1)
                else:
                    self.scene.selected_indices |= to_select
                    self.scene.selected_idx = clicked_idx
        else:
            self.scene.selected_idx     = clicked_idx
            self.scene.selected_indices = set(to_select) if clicked_idx >= 0 else set()

    # ── Mise à jour ───────────────────────────────────────────────────────────
    def _update_loop(self):
        now = time.time()
        dt  = now - self.last_time
        self.last_time = now

        if self.gizmo.dragging_axis and self.mouse_btn1:
            self.gizmo.update_drag(self.mouse_x, self.mouse_y, self.scene, self.camera)

        self.camera.apply_movement(self.keys_pressed, dt)

        self.root.after(16, self._update_loop)

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def _render(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glViewport(0, 0, VIEW_WIDTH, HEIGHT)
        glMatrixMode(GL_PROJECTION); glLoadIdentity()
        gluPerspective(FOV, VIEW_WIDTH / HEIGHT, NEAR, FAR)
        glMatrixMode(GL_MODELVIEW);  glLoadIdentity()
        glRotatef(-self.camera.pitch, 1, 0, 0)
        glRotatef(-self.camera.yaw,   0, 1, 0)
        glTranslatef(-self.camera.pos[0], -self.camera.pos[1], -self.camera.pos[2])

        draw_grid(30, 1)
        self.scene.draw()
        self.gizmo.draw(self.scene, self.camera)
