"""Classe App : initialisation Tkinter/pyopengltk, boucle principale, gestion des événements."""

import math
import time
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox
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

_SEP_WIDTH           = 5
_PANEL_MIN_WIDTH     = 100
_PANEL_MAX_WIDTH     = 700
_TOTAL_CONTENT_WIDTH = PANEL_WIDTH + VIEW_WIDTH

SNAP_VALUES = ["1", "0.5", "0.25", "0.1", "0.05", "0.01"]
from editor.camera        import Camera
from editor.scene         import Scene
from editor.gizmo         import Gizmo
from editor.renderer      import draw_grid
from editor.uv_selector   import UVSelector
from editor.group_panel   import GroupPanel
from editor.state_manager import StateManager
from editor.history       import (HistoryManager, AddPolygonsCommand,
                                   DeletePolygonsCommand, PolyDataCommand,
                                   GroupCommand, UngroupCommand)
from editor.group         import Group, all_polygons


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
        self.state          = StateManager(self.scene.root)
        self.scene._state   = self.state           # injection du StateManager dans Scene
        self.gizmo          = Gizmo()
        self.panel_width    = PANEL_WIDTH
        self.panning        = False
        self.pan_last_x     = 0
        self.pan_last_y     = 0
        self._resizing      = False
        self._resize_start_x = 0
        self._resize_start_pw = PANEL_WIDTH
        self.history           = HistoryManager()
        self.keys_pressed      = set()
        self.mouse_btn1        = False
        self.mouse_x           = 0
        self.mouse_y           = 0
        self.last_time         = time.time()
        self._viewport_focused = False

    # ── Cycle de vie ──────────────────────────────────────────────────────────
    def run(self):
        self.root = tk.Tk()
        self.root.title("3D Viewer")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.sel_mode_var = tk.StringVar(value='Polygon')
        self._build_menu()
        self._build_toolbar()
        self._build_toolbar2()
        self._build_statusbar()
        self._build_panel()
        self._build_resize_bar()
        self._build_viewport()
        self._bind_events()

        self.state.subscribe('selection_changed', lambda **_: self._sync_toolbar2_btns())

        self.root.bind('<Control-z>', lambda _: self.history.undo())
        self.root.bind('<Control-y>', lambda _: self.history.redo())

        self.scene.load_atlas(ATLAS_JSON)
        self.viewport.animate = 1
        self._update_loop()
        self.root.mainloop()

    def _on_close(self):
        if not messagebox.askyesno("Quitter", "Voulez-vous vraiment quitter l'application ?"):
            return
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
        m_file.add_command(label="Quitter",
                           command=self._on_close)
        menubar.add_cascade(label="File", menu=m_file)

        # ── Edit ──────────────────────────────────────────────────────────────
        m_edit = tk.Menu(menubar, tearoff=0)
        m_edit.add_command(label="Annuler", accelerator="Ctrl+Z",
                           command=lambda: self.history.undo())
        m_edit.add_command(label="Rétablir", accelerator="Ctrl+Y",
                           command=lambda: self.history.redo())
        m_edit.add_separator()
        m_edit.add_command(label="Dupliquer", accelerator="C",
                           command=self._cmd_duplicate)
        m_edit.add_command(label="Supprimer", accelerator="Suppr",
                           command=self._cmd_delete)
        m_edit.add_separator()
        m_edit.add_command(label="Grouper", accelerator="G",
                           command=self._cmd_group)
        m_edit.add_command(label="Dégrouper", accelerator="H",
                           command=self._cmd_ungroup)
        menubar.add_cascade(label="Edit", menu=m_edit)

        # ── Polygon ───────────────────────────────────────────────────────────
        m_poly = tk.Menu(menubar, tearoff=0)
        m_poly.add_command(label="Ajouter polygon",
                           command=self._cmd_add_polygon)
        m_poly.add_command(label="Ajouter triangle",
                           command=self._cmd_add_triangle)
        m_poly.add_separator()
        m_poly.add_command(label="Inverser orientation", accelerator="N",
                           command=self._cmd_flip_orientation)
        m_poly.add_command(label="Rotation UVs", accelerator="R",
                           command=self._cmd_rotate_uvs)
        m_poly.add_separator()
        m_poly.add_command(label="Rapprocher arêtes",
                           command=self._cmd_rapprocher_edges)
        m_poly.add_command(label="Créer polygon depuis arêtes",
                           command=self._cmd_create_from_edges)
        menubar.add_cascade(label="Polygon", menu=m_poly)

        self.root.config(menu=menubar)

    # ── Barre d'outils ────────────────────────────────────────────────────────
    def _build_toolbar(self):
        BG      = '#16161f'
        BG_ACT  = '#2a2a3a'
        BG_ON   = '#2d4080'
        self._BG_DIS = '#1e1e28'   # bouton désactivé
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
            btn.bind('<Enter>', lambda _e, b=btn: b.config(bg=BG_ACT) if b['bg'] != BG_ON and str(b['state']) != 'disabled' else None, add='+')
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
        add_btn(make_icon(ico_polygon),
                self._cmd_add_polygon,
                "Polygon")
        add_btn(make_icon(ico_triangle),
                self._cmd_add_triangle,
                "Triangle")
        add_sep()
        add_btn(make_icon(ico_duplicate),
                self._cmd_duplicate,
                "Dupliquer", "C")
        add_btn(make_icon(ico_delete),
                self._cmd_delete,
                "Supprimer", "Suppr")
        add_sep()
        add_btn(make_icon(ico_group),
                self._cmd_group,
                "Grouper", "G")
        add_btn(make_icon(ico_ungroup),
                self._cmd_ungroup,
                "Dégrouper", "H")
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
        BTN_SZ  = 34

        self.toolbar2 = tk.Frame(self.root, bg=BG, height=BTN_SZ + 4)
        self.toolbar2.pack(side=tk.TOP, fill=tk.X)
        self.toolbar2.pack_propagate(False)

        def add_btn(cmd, label='', shortcut=''):
            display = f"{label} [{shortcut}]" if shortcut else label
            btn = tk.Button(
                self.toolbar2, text=display, command=cmd,
                bg=BG, activebackground=BG_ACT,
                fg=IC, activeforeground=IC,
                relief='flat', bd=0,
                font=('Segoe UI', 8),
                padx=6, pady=4,
                cursor='hand2',
            )
            btn.pack(side=tk.LEFT, padx=1, pady=2)
            btn.bind('<Enter>', lambda _e, b=btn: b.config(bg=BG_ACT))
            btn.bind('<Leave>', lambda _e, b=btn: b.config(bg=BG))
            return btn

        # ── Placement ─────────────────────────────────────────────────────────
        add_btn(self._cmd_flip_orientation,
                "Inverser orientation", "N")
        add_btn(self._cmd_rotate_uvs,
                "Rotation UVs", "R")
        self._sep_edges = tk.Frame(self.toolbar2, width=1, bg='#38384a')
        self._sep_edges.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self._btn_rapprocher = add_btn(self._cmd_rapprocher_edges,
                                       "Rapprocher arêtes")
        self._btn_create_from_edges = add_btn(self._cmd_create_from_edges,
                                              "Créer polygon depuis arêtes")
        self._sync_toolbar2_btns()

    def _on_snap_change(self, *_):
        v = float(self._snap_var.get())
        self.gizmo.translate_snap = v
        self.gizmo.scale_snap     = v

    def _sync_toolbar2_btns(self):
        two_edges = len(self.state.selected_edges) == 2
        widgets = [self._sep_edges, self._btn_rapprocher, self._btn_create_from_edges]
        for w in widgets:
            if two_edges:
                w.pack(side=tk.LEFT, fill=tk.Y if w is self._sep_edges else tk.NONE,
                       padx=5 if w is self._sep_edges else 1,
                       pady=5 if w is self._sep_edges else 2)
            else:
                w.pack_forget()

    def _refresh_group_panel(self):
        if hasattr(self, 'group_panel'):
            self.group_panel.refresh()

    def _sync_gizmo_btns(self):
        restricted = self.state.selection_mode in ('vertex', 'edge')
        for mode, (btn, bg_off, bg_on) in self._gizmo_btns.items():
            disabled = restricted and mode in ('rotate', 'scale')
            if disabled:
                btn.config(state='disabled', bg=self._BG_DIS, cursor='')
            else:
                btn.config(state='normal', cursor='hand2',
                           bg=bg_on if self.gizmo.mode == mode else bg_off)

    def _sync_sel_mode_btns(self):
        for mode, (btn, bg_off, bg_on) in self._sel_btns.items():
            btn.config(bg=bg_on if self.state.selection_mode == mode else bg_off)

    # ── Construction de l'interface ───────────────────────────────────────────
    def _build_panel(self):
        self.panel = tk.Frame(self.root, width=self.panel_width, bg='#1a1a21')
        self.panel.pack(side=tk.LEFT, fill=tk.Y)
        self.panel.pack_propagate(False)

        self._tab_btns   = {}
        self._tab_frames = {}
        self._active_tab = None

        # ── Barre d'onglets ───────────────────────────────────────────────────
        _TAB_BG     = '#111118'
        _TAB_BG_ON  = '#1a1a21'
        _TAB_FG     = '#666678'
        _TAB_FG_ON  = '#c8c8d8'
        _TAB_ACT    = '#16161f'

        tab_bar = tk.Frame(self.panel, bg=_TAB_BG)
        tab_bar.pack(side=tk.TOP, fill=tk.X)

        # Séparateur sous la barre
        tk.Frame(self.panel, height=1, bg='#2a2a3a').pack(side=tk.TOP, fill=tk.X)

        # Zone de contenu partagée
        self._tab_content = tk.Frame(self.panel, bg='#1a1a21')
        self._tab_content.pack(fill=tk.BOTH, expand=True)

        def _switch_tab(name):
            if self._active_tab == name:
                return
            if self._active_tab and self._active_tab in self._tab_frames:
                self._tab_frames[self._active_tab].pack_forget()
                self._tab_btns[self._active_tab].config(
                    bg=_TAB_BG, fg=_TAB_FG, relief='flat')
            self._active_tab = name
            self._tab_frames[name].pack(fill=tk.BOTH, expand=True)
            self._tab_btns[name].config(
                bg=_TAB_BG_ON, fg=_TAB_FG_ON, relief='flat')

        self._switch_tab = _switch_tab

        def _add_tab(name, widget_factory):
            btn = tk.Button(
                tab_bar, text=name,
                bg=_TAB_BG, fg=_TAB_FG,
                activebackground=_TAB_ACT, activeforeground=_TAB_FG_ON,
                relief='flat', bd=0,
                font=('Segoe UI', 8),
                padx=10, pady=5,
                cursor='hand2',
                command=lambda n=name: _switch_tab(n),
            )
            btn.pack(side=tk.LEFT)
            frame = tk.Frame(self._tab_content, bg='#1a1a21')
            self._tab_btns[name]   = btn
            self._tab_frames[name] = frame
            return widget_factory(frame)

        self.uv_selector = _add_tab('UV Selector',
                                    lambda f: UVSelector(f, self.scene,
                                                         on_uv_assigned=self._cmd_uv_assigned))
        self.uv_selector.pack(fill=tk.BOTH, expand=True)

        self.group_panel = _add_tab('Groupes',
                                    lambda f: GroupPanel(f, self.scene, self))
        self.group_panel.pack(fill=tk.BOTH, expand=True)

        _switch_tab('UV Selector')

    def _build_statusbar(self):
        BG = '#111118'
        FG = '#888899'
        FG_HI = '#c8c8d8'

        self._statusbar = tk.Frame(self.root, bg=BG, height=22)
        self._statusbar.pack(side=tk.BOTTOM, fill=tk.X)
        self._statusbar.pack_propagate(False)

        tk.Frame(self._statusbar, height=1, bg='#2a2a3a').pack(side=tk.TOP, fill=tk.X)

        self._status_sel_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG_HI,
                                        font=('Segoe UI', 8), anchor='w', padx=8)
        self._status_sel_lbl.pack(side=tk.LEFT)

        tk.Frame(self._statusbar, width=1, bg='#2a2a3a').pack(side=tk.LEFT, fill=tk.Y, pady=3)

        self._status_group_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG,
                                          font=('Segoe UI', 8), anchor='w', padx=8)
        self._status_group_lbl.pack(side=tk.LEFT)

        self._status_right_lbl = tk.Label(self._statusbar, text='', bg=BG, fg=FG,
                                          font=('Segoe UI', 8), anchor='e', padx=8)
        self._status_right_lbl.pack(side=tk.RIGHT)

    def _update_statusbar(self):
        n = len(self.scene.selected_indices)
        if n == 0:
            sel_text = 'Aucune sélection'
        elif n == 1:
            sel_text = '1 polygon sélectionné'
        else:
            sel_text = f'{n} polygons sélectionnés'
        self._status_sel_lbl.config(text=sel_text)

        grp = self.state.current_group
        grp_name = getattr(grp, 'name', None) or 'Racine'
        self._status_group_lbl.config(text=f'Groupe : {grp_name}')

        mode_labels = {'translate': 'Translater', 'rotate': 'Rotation', 'scale': 'Échelle'}
        sel_mode_labels = {'polygon': 'Polygon', 'edge': 'Arête', 'vertex': 'Vertex'}
        right = (f"Gizmo : {mode_labels.get(self.gizmo.mode, self.gizmo.mode)}   "
                 f"Mode : {sel_mode_labels.get(self.state.selection_mode, self.state.selection_mode)}")
        self._status_right_lbl.config(text=right)

    def _build_resize_bar(self):
        self._sep = tk.Frame(self.root, width=_SEP_WIDTH, bg='#2a2a3a',
                             cursor='sb_h_double_arrow')
        self._sep.pack(side=tk.LEFT, fill=tk.Y)
        self._sep.bind('<ButtonPress-1>',   self._on_sep_press)
        self._sep.bind('<ButtonRelease-1>', self._on_sep_release)
        self._sep.bind('<Motion>',          self._on_sep_motion)
        self._sep.bind('<Enter>', lambda _: self._sep.config(bg='#3e3e5a'))
        self._sep.bind('<Leave>', lambda _: self._sep.config(bg='#2a2a3a'
                                            if not self._resizing else '#3e3e5a'))

    def _build_viewport(self):
        vw = _TOTAL_CONTENT_WIDTH - self.panel_width - _SEP_WIDTH
        self.viewport = Viewport3D(self.root, self, width=vw, height=HEIGHT)
        self.viewport.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.viewport.bind('<FocusIn>',  self._on_viewport_focus_in)
        self.viewport.bind('<FocusOut>', self._on_viewport_focus_out)

    def _on_sep_press(self, event):
        self._resizing       = True
        self._resize_start_x  = event.x_root
        self._resize_start_pw = self.panel_width

    def _on_sep_release(self, _):
        self._resizing = False
        self._sep.config(bg='#2a2a3a')

    def _on_sep_motion(self, event):
        if not self._resizing:
            return
        dx = event.x_root - self._resize_start_x
        new_pw = max(_PANEL_MIN_WIDTH, min(_PANEL_MAX_WIDTH,
                                           self._resize_start_pw + dx))
        new_vw = self.root.winfo_width() - new_pw - _SEP_WIDTH
        if new_vw < 200:
            return
        self.panel_width = new_pw
        self.panel.config(width=new_pw)
        self.viewport.config(width=new_vw)
        self.camera.vw = new_vw

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
        self.viewport.focus_set()
        self.mouse_btn1 = True
        self.mouse_x, self.mouse_y = event.x, event.y
        self._handle_mouse_down_3d(event.x, event.y)

    def _on_mouse_up(self, event):
        self.mouse_btn1 = False
        self.gizmo.finish_drag(self.history, self.state)

    def _on_mouse_wheel(self, event):
        self.camera.apply_scroll(event.delta / 120)

    def _on_middle_down(self, event):
        self.viewport.focus_set()
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
                cx = self.viewport.winfo_rootx() + self.viewport.winfo_width() // 2
                cy = self.viewport.winfo_rooty() + self.viewport.winfo_height() // 2
                ctypes.windll.user32.SetCursorPos(cx, cy)
                self.pan_last_x = cx
                self.pan_last_y = cy

    # ── Focus viewport ────────────────────────────────────────────────────────
    def _on_viewport_focus_in(self, _event):
        self._viewport_focused = True

    def _on_viewport_focus_out(self, _event):
        self._viewport_focused = False
        self.keys_pressed.clear()

    # ── Événements clavier ────────────────────────────────────────────────────
    def _on_key_press(self, event):
        if not self._viewport_focused:
            return
        key = event.keysym.lower()
        self.keys_pressed.add(key)
        self._handle_keyboard(key)

    def _on_key_release(self, event):
        self.keys_pressed.discard(event.keysym.lower())

    def _on_selection_mode_change(self, event=None):
        mode_map = {'Polygon': 'polygon', 'Arête': 'edge', 'Vertex': 'vertex'}
        new_mode = mode_map[self.sel_mode_var.get()]
        self.state.set_selection_mode(new_mode)
        if new_mode in ('vertex', 'edge'):
            self.gizmo.mode = 'translate'
        self._sync_sel_mode_btns()
        self._sync_gizmo_btns()

    def _handle_keyboard(self, key):
        if key == 't' and self.scene.selected_idx >= 0:
            if self.scene.tex_preview_win:
                self.scene.close_tex_preview()
            else:
                self.scene.open_tex_preview(self.root)

        if key == 'delete' and self.scene.selected_indices:
            self._cmd_delete()

        if key == 'c':
            self._cmd_duplicate()

        if key == 'space' and self.scene.selected_indices:
            self.gizmo.cycle_mode(len(self.scene.selected_indices) > 1)
            self._sync_gizmo_btns()

        if key == 'g' and len(self.scene.selected_indices) >= 2:
            self._cmd_group()

        if key == 'h' and self.scene.selected_indices:
            self._cmd_ungroup()

        if key == 'r' and self.scene.selected_indices:
            self._cmd_rotate_uvs()

        if key == 'n' and self.scene.selected_indices:
            self._cmd_flip_orientation()

        if key == 'e':
            modes = ['polygon', 'edge', 'vertex']
            next_mode = modes[(modes.index(self.state.selection_mode) + 1) % len(modes)]
            self.sel_mode_var.set({'polygon': 'Polygon', 'edge': 'Arête', 'vertex': 'Vertex'}[next_mode])
            self._on_selection_mode_change()

        if key in ('prior', 'next'):   # Page Up / Page Down
            idx = SNAP_VALUES.index(self._snap_var.get()) if self._snap_var.get() in SNAP_VALUES else 0
            if key == 'prior' and idx > 0:
                self._snap_var.set(SNAP_VALUES[idx - 1])
            elif key == 'next' and idx < len(SNAP_VALUES) - 1:
                self._snap_var.set(SNAP_VALUES[idx + 1])
            self._on_snap_change()


    # ── Commandes avec historique ──────────────────────────────────────────────

    def _record_added_polygons(self, before_ids: set) -> None:
        """Enregistre les polygones ajoutés depuis before_ids comme commande."""
        new_polys = [p for p in all_polygons(self.scene.root)
                     if id(p) not in before_ids]
        if new_polys:
            self.history.record(AddPolygonsCommand(self.state, new_polys))

    def _cmd_add_polygon(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.add_polygon(self.camera.pos, self.camera.yaw,
                               self.state.current_group)
        self._record_added_polygons(before_ids)

    def _cmd_add_triangle(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.add_triangle(self.camera.pos, self.camera.yaw,
                                self.state.current_group)
        self._record_added_polygons(before_ids)

    def _cmd_duplicate(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.duplicate_selected()
        self._record_added_polygons(before_ids)

    def _cmd_delete(self) -> None:
        polys = self.state.selected_polygons
        if not polys:
            return
        saved = []
        for p in polys:
            if p.group is not None:
                try:
                    idx = p.group.polygons.index(p)
                except ValueError:
                    idx = len(p.group.polygons)
                saved.append((p, p.group, idx))
        if not saved:
            return
        self.history.push(DeletePolygonsCommand(self.state, saved))
        self.gizmo.stop_drag()

    def _cmd_uv_assigned(self, before: dict, after: dict) -> None:
        if before and any(before[p] != after.get(p) for p in before):
            self.history.record(PolyDataCommand(self.state, before, after))

    def _cmd_rotate_uvs(self) -> None:
        polys = self.state.selected_polygons
        if not polys:
            return
        before = {p: (list(p.vertices), list(p.uvs)) for p in polys}
        self.scene.rotate_uvs()
        after = {p: (list(p.vertices), list(p.uvs)) for p in polys}
        self.history.record(PolyDataCommand(self.state, before, after))

    def _cmd_flip_orientation(self) -> None:
        polys = self.state.selected_polygons
        if not polys:
            return
        before = {p: (list(p.vertices), list(p.uvs)) for p in polys}
        self.scene.flip_orientation()
        after = {p: (list(p.vertices), list(p.uvs)) for p in polys}
        self.history.record(PolyDataCommand(self.state, before, after))

    def _cmd_rapprocher_edges(self) -> None:
        edges = self.state.selected_edges
        if len(edges) != 2:
            return
        affected = list({poly for poly, _ in edges})
        before = {p: (list(p.vertices), list(p.uvs)) for p in affected}
        self.scene.rapprocher_edges()
        after = {p: (list(p.vertices), list(p.uvs)) for p in affected}
        self.history.record(PolyDataCommand(self.state, before, after))

    def _cmd_create_from_edges(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.create_polygon_from_edges(self.state.current_group)
        self._record_added_polygons(before_ids)

    def _cmd_group(self) -> None:
        polys = self.state.selected_polygons
        if len(polys) < 2:
            return
        old_groups = {p: (p.group, p.group.polygons.index(p)) for p in polys}
        parent = self.scene.root
        new_group = Group(name="Groupe")
        self.history.push(GroupCommand(self.state, polys, old_groups,
                                       new_group, parent))

    def _cmd_ungroup(self) -> None:
        polys = self.state.selected_polygons
        if not polys:
            return
        groups_to_dissolve = {p.group for p in polys
                              if p.group is not self.scene.root}
        if not groups_to_dissolve:
            return
        groups_info = []
        for group in groups_to_dissolve:
            parent = group.parent if group.parent is not None else self.scene.root
            polys_idx = [(p, group.polygons.index(p))
                         for p in list(group.polygons)]
            groups_info.append((group, parent, polys_idx))
        self.history.push(UngroupCommand(self.state, groups_info))

    def _handle_mouse_down_3d(self, mx, my):
        ctrl_held = 'shift_l' in self.keys_pressed
        multi     = len(self.scene.selected_indices) > 1
        sel_mode  = self.state.selection_mode

        if sel_mode == 'edge' and self.state.selected_edges:
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            else:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            return

        if sel_mode == 'vertex' and self.state.selected_vertices:
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            else:
                self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if sel_mode == 'vertex':
            self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if self.gizmo.mode == 'translate' or (multi and self.gizmo.mode == 'scale'):
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)

        elif self.gizmo.mode == 'rotate':
            axis = self.gizmo.pick_rotate_axis(mx, my, self.state, self.camera)
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)

        else:  # scale
            handle = self.gizmo.pick_scale_handle(mx, my, self.state, self.camera)
            if handle:
                self.gizmo.start_drag(handle, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._apply_selection(self._pick_polygon(mx, my), ctrl_held)

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
                self.state.set_selection(vertices=[])
            return
        flat = all_polygons(self.scene.root)
        poly_idx, vert_idx = vertex
        if poly_idx >= len(flat):
            return
        vert_ref = (flat[poly_idx], vert_idx)
        current = list(self.state.selected_vertices)
        if ctrl_held:
            if vert_ref in current:
                current.remove(vert_ref)
            else:
                current.append(vert_ref)
            self.state.set_selection(vertices=current)
        else:
            self.state.set_selection(vertices=[vert_ref])

    def _apply_edge_selection(self, edge, ctrl_held):
        if edge is None:
            if not ctrl_held:
                self.state.set_selection(edges=[])
            return
        flat = all_polygons(self.scene.root)
        poly_idx, edge_idx = edge
        if poly_idx >= len(flat):
            return
        edge_ref = (flat[poly_idx], edge_idx)
        current = list(self.state.selected_edges)
        if ctrl_held:
            if edge_ref in current:
                current.remove(edge_ref)
            else:
                current.append(edge_ref)
            self.state.set_selection(edges=current)
        else:
            self.state.set_selection(edges=[edge_ref])

    def _apply_selection(self, clicked_idx, ctrl_held):
        """Applique la sélection selon Ctrl — passe par le StateManager."""
        flat = all_polygons(self.scene.root)
        if ctrl_held:
            if clicked_idx >= 0 and clicked_idx < len(flat):
                poly    = flat[clicked_idx]
                current = list(self.state._selected_polygons)
                if poly in current:
                    current.remove(poly)
                else:
                    current.append(poly)
                self.state.set_selection(polygons=current)
        else:
            if clicked_idx >= 0 and clicked_idx < len(flat):
                self.state.set_selection(polygons=[flat[clicked_idx]])
            else:
                self.state.clear_selection()

    # ── Mise à jour ───────────────────────────────────────────────────────────
    def _update_loop(self):
        now = time.time()
        dt  = now - self.last_time
        self.last_time = now

        if self.gizmo.dragging_axis and self.mouse_btn1:
            self.gizmo.update_drag(self.mouse_x, self.mouse_y, self.state, self.camera)

        self.camera.apply_movement(self.keys_pressed, dt)
        self._update_statusbar()

        self.root.after(16, self._update_loop)

    # ── Rendu ─────────────────────────────────────────────────────────────────
    def _render(self):
        vw = self.viewport.winfo_width() or self.camera.vw
        vh = self.viewport.winfo_height() or self.camera.vh
        self.camera.vw, self.camera.vh = vw, vh
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glViewport(0, 0, vw, vh)
        glMatrixMode(GL_PROJECTION); glLoadIdentity()
        gluPerspective(FOV, vw / vh, NEAR, FAR)
        glMatrixMode(GL_MODELVIEW);  glLoadIdentity()
        glRotatef(-self.camera.pitch, 1, 0, 0)
        glRotatef(-self.camera.yaw,   0, 1, 0)
        glTranslatef(-self.camera.pos[0], -self.camera.pos[1], -self.camera.pos[2])

        draw_grid(30, 1)
        self.scene.draw()
        self.gizmo.draw(self.state, self.camera)
