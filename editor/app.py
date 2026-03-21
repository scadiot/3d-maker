"""App class: Tkinter/pyopengltk initialization, main loop, event handling."""

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
_PANEL_MIN_WIDTH     = 200
_PANEL_MAX_WIDTH     = 1500
_TOTAL_CONTENT_WIDTH = PANEL_WIDTH + VIEW_WIDTH

SNAP_VALUES = ["1", "0.5", "0.25", "0.1", "0.05", "0.01"]
from editor.camera        import Camera
from editor.scene         import Scene
from editor.gizmo         import Gizmo
from editor.view_cube     import ViewCube
from editor.renderer      import draw_grid
from editor.uv_selector   import UVSelector
from editor.group_panel   import GroupPanel
from editor.state_manager import StateManager
from editor.history       import (HistoryManager, AddPolygonsCommand,
                                   DeletePolygonsCommand, PolyDataCommand,
                                   GroupCommand, UngroupCommand)
from editor.group         import Group, all_polygons
from editor.math3d        import normalize, cross, vsub, dot
from editor.texture_atlas import TextureAtlas


class Viewport3D(OpenGLFrame):
    """OpenGL widget embedded in Tkinter via pyopengltk."""

    def __init__(self, master, app, **kw):
        super().__init__(master, **kw)
        self._app = app

    def initgl(self):
        glEnable(GL_DEPTH_TEST)
        glClearColor(0.08, 0.08, 0.12, 1.0)
        ta = TextureAtlas(TEXTURE_PATH, ATLAS_JSON)
        self._app.scene.load_atlas(ta)
        if not self._app.state.textures_atlases:
            self._app.state.textures_atlases = [ta]

    def redraw(self):
        self._app._render()


class App:
    def __init__(self):
        self.camera         = Camera()
        self.scene          = Scene()
        self.state          = StateManager(self.scene.root)
        self.scene._state   = self.state           # inject StateManager into Scene
        self.gizmo          = Gizmo()
        self.view_cube      = ViewCube()
        self.panel_width    = PANEL_WIDTH
        self.right_panel_width = PANEL_WIDTH
        self.panning        = False
        self.pan_last_x     = 0
        self.pan_last_y     = 0
        self._resizing      = False
        self._resize_start_x = 0
        self._resize_start_pw = PANEL_WIDTH
        self._right_resizing      = False
        self._right_resize_start_x = 0
        self._right_resize_start_pw = PANEL_WIDTH
        self.history           = HistoryManager()
        self.keys_pressed      = set()
        self.mouse_btn1        = False
        self.mouse_x           = 0
        self.mouse_y           = 0
        self.last_time         = time.time()
        self._viewport_focused = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    def run(self):
        self.root = tk.Tk()
        self.root.title("Quad Maker")
        self.root.resizable(True, True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.sel_mode_var = tk.StringVar(value='Polygon')
        self._build_menu()
        self._build_toolbar()
        self._build_toolbar2()
        self._build_statusbar()
        self._build_panel()
        self._build_resize_bar()
        self._build_right_panel()
        self._build_right_resize_bar()
        self._build_viewport()
        self._bind_events()

        self.state.subscribe('selection_changed', lambda **_: self._sync_toolbar2_btns())
        self.state.subscribe('scene_changed', lambda **_: self._update_title())
        self.state.subscribe('polygon_transformed', lambda **_: self._update_title())
        self.state.subscribe('textures_changed', lambda atlases, **_: [self.scene.load_atlas(a) for a in atlases])

        self.root.bind('<Control-z>', lambda _: self.history.undo())
        self.root.bind('<Control-y>', lambda _: self.history.redo())
        self.root.bind('<Control-s>', lambda _: self._save_json())
        self.root.bind('<Control-n>', lambda _: self._new_project())

        self.viewport.animate = 1
        self._update_loop()
        self.root.mainloop()

    def _on_close(self):
        if self.state.modified:
            if not messagebox.askyesno("Quit", "The project has unsaved changes. Do you really want to quit?"):
                return
        self.scene.close_tex_preview()
        self.root.destroy()

    # ── Menu bar ──────────────────────────────────────────────────────────────
    def _build_menu(self):
        menubar = tk.Menu(self.root)

        # ── File ──────────────────────────────────────────────────────────────
        m_file = tk.Menu(menubar, tearoff=0)
        m_file.add_command(label="New project", accelerator="Ctrl+N",
                           command=self._new_project)
        m_file.add_separator()
        m_file.add_command(label="Open",
                           command=self._load_json_dialog)
        m_file.add_command(label="Save", accelerator="Ctrl+S",
                           command=self._save_json)
        m_file.add_command(label="Save as…",
                           command=self._save_json_dialog)
        m_file.add_separator()
        m_file.add_command(label="Quit",
                           command=self._on_close)
        menubar.add_cascade(label="File", menu=m_file)

        # ── Edit ──────────────────────────────────────────────────────────────
        m_edit = tk.Menu(menubar, tearoff=0)
        m_edit.add_command(label="Undo", accelerator="Ctrl+Z",
                           command=lambda: self.history.undo())
        m_edit.add_command(label="Redo", accelerator="Ctrl+Y",
                           command=lambda: self.history.redo())
        m_edit.add_separator()
        m_edit.add_command(label="Duplicate", accelerator="C",
                           command=self._cmd_duplicate)
        m_edit.add_command(label="Delete", accelerator="Del",
                           command=self._cmd_delete)
        m_edit.add_separator()
        m_edit.add_command(label="Group", accelerator="G",
                           command=self._cmd_group)
        m_edit.add_command(label="Ungroup", accelerator="H",
                           command=self._cmd_ungroup)
        menubar.add_cascade(label="Edit", menu=m_edit)

        # ── Polygon ───────────────────────────────────────────────────────────
        m_poly = tk.Menu(menubar, tearoff=0)
        m_poly.add_command(label="Add polygon",
                           command=self._cmd_add_polygon)
        m_poly.add_command(label="Add triangle",
                           command=self._cmd_add_triangle)
        m_poly.add_separator()
        m_poly.add_command(label="Flip orientation", accelerator="N",
                           command=self._cmd_flip_orientation)
        m_poly.add_command(label="Rotate Vertices", accelerator="R",
                           command=self._cmd_rotate_vertices)
        m_poly.add_separator()
        m_poly.add_command(label="Create polygon from edges",
                           command=self._cmd_create_from_edges)
        menubar.add_cascade(label="Polygon", menu=m_poly)

        # ── Project ───────────────────────────────────────────────────────────
        m_project = tk.Menu(menubar, tearoff=0)
        m_project.add_command(label="Project info",
                              command=self._cmd_project_info)
        m_project.add_command(label="Textures Atlas",
                              command=self._cmd_textures_atlas)
        menubar.add_cascade(label="Project", menu=m_project)

        self.root.config(menu=menubar)

    # ── Toolbar ───────────────────────────────────────────────────────────────
    def _build_toolbar(self):
        BG      = '#16161f'
        BG_ACT  = '#2a2a3a'
        BG_ON   = '#2d4080'
        self._BG_DIS = '#1e1e28'   # disabled button
        IC      = '#c8c8d8'   # icon color
        SZ      = 22           # icon size in px
        BTN_SZ  = 34           # taille bouton

        self._icons       = []   # keep PhotoImage objects alive
        self._gizmo_btns  = {}   # gizmo buttons for highlighting
        self._sel_btns    = {}   # selection mode buttons

        self.toolbar = tk.Frame(self.root, bg=BG, height=BTN_SZ + 4)
        self.toolbar.pack(side=tk.TOP, fill=tk.X)
        self.toolbar.pack_propagate(False)

        # ── Icon factory ──────────────────────────────────────────────────────
        def make_icon(draw_fn):
            img = Image.new('RGBA', (SZ, SZ), (0, 0, 0, 0))
            draw_fn(ImageDraw.Draw(img), SZ, IC)
            ph = ImageTk.PhotoImage(img)
            self._icons.append(ph)
            return ph

        # ── Button factory with hover tooltip ─────────────────────────────────
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

        # ── Icon drawings ─────────────────────────────────────────────────────
        def ico_new(d, s, c):
            fold = 5
            # Page with folded top-right corner
            d.polygon([3, 3,  s-3-fold, 3,  s-3, 3+fold,  s-3, s-3,  3, s-3],
                      outline=c, fill='#16161f')
            d.line([s-3-fold, 3, s-3, 3+fold], fill=c, width=1)
            # «+» cross at center
            cx, cy = s//2, s//2 + 2
            d.line([cx-3, cy, cx+3, cy], fill=c, width=2)
            d.line([cx, cy-3, cx, cy+3], fill=c, width=2)

        def ico_save(d, s, c):
            d.rectangle([3, 4, s-3, s-3], outline=c, width=1)
            d.rectangle([5, 3, s-7, 8],   fill=c)               # label
            d.rectangle([s-8, 3, s-5, 7], fill='#16161f')        # label window
            d.rectangle([6, 13, s-6, s-4], outline=c, width=1)  # pocket

        def ico_save_current(d, s, c):
            d.rectangle([3, 4, s-3, s-3], outline=c, width=1)
            d.rectangle([5, 3, s-7, 8],   fill=c)
            d.rectangle([s-8, 3, s-5, 7], fill='#16161f')
            d.rectangle([6, 13, s-6, s-4], outline=c, width=1)
            # small downward arrow at center
            cx = s // 2
            d.line([cx, 14, cx, s-6], fill='#16161f', width=2)
            d.polygon([cx-3, s-9, cx+3, s-9, cx, s-5], fill='#16161f')

        def ico_load(d, s, c):
            d.rectangle([3, 7, s-3, s-3], outline=c, width=1)
            d.polygon([3, 7, 3, 4, 9, 4, 11, 7], outline=c, fill='#16161f')
            d.line([3, 7, 11, 7], fill=c, width=1)

        def ico_import(d, s, c):
            # Folder shape like ico_load, with a downward arrow inside
            d.rectangle([3, 7, s-3, s-3], outline=c, width=1)
            d.polygon([3, 7, 3, 4, 9, 4, 11, 7], outline=c, fill='#16161f')
            d.line([3, 7, 11, 7], fill=c, width=1)
            cx = s // 2
            d.line([cx, 10, cx, s-7], fill=c, width=2)
            d.polygon([cx-3, s-9, cx+3, s-9, cx, s-5], fill=c)

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
            d.rectangle([s-5, 3, s-6+1, s-6+1], fill='#16161f')  # erase corner

        def ico_delete(d, s, c):
            d.rectangle([4, 7, s-4, s-3], outline=c, width=1)
            d.line([4, 7, s-4, 7], fill=c, width=1)
            d.rectangle([7, 4, s-7, 7], outline=c, width=1)       # handle
            d.line([8, 11, 8, s-5],  fill=c, width=1)             # slot left
            d.line([s-8, 11, s-8, s-5], fill=c, width=1)          # slot right

        def ico_group(d, s, c):
            d.line([4, 4, 4, s-4],   fill=c, width=2)             # bracket left
            d.line([4, 4, 7, 4],     fill=c, width=2)
            d.line([4, s-4, 7, s-4], fill=c, width=2)
            d.line([s-4, 4, s-4, s-4],   fill=c, width=2)         # bracket right
            d.line([s-7, 4, s-4, 4],     fill=c, width=2)
            d.line([s-7, s-4, s-4, s-4], fill=c, width=2)
            d.line([7, s//2, s-7, s//2], fill=c, width=1)         # link

        def ico_ungroup(d, s, c):
            d.line([4, 4, 4, s//2-3],   fill=c, width=2)
            d.line([4, 4, 7, 4],        fill=c, width=2)
            d.line([4, s//2+3, 4, s-4], fill=c, width=2)
            d.line([4, s-4, 7, s-4],    fill=c, width=2)
            d.line([s-4, 4, s-4, s//2-3],   fill=c, width=2)
            d.line([s-7, 4, s-4, 4],        fill=c, width=2)
            d.line([s-4, s//2+3, s-4, s-4], fill=c, width=2)
            d.line([s-7, s-4, s-4, s-4],    fill=c, width=2)

        def ico_snap_grid(d, s, c):
            for i in [4, s//2, s-4]:
                d.line([i, 4, i, s-4], fill=c, width=1)
                d.line([4, i, s-4, i], fill=c, width=1)

        def ico_vertex_glue(d, s, c):
            r, cx, cy = 2, s//2, s//2
            # Two vertex dots
            d.ellipse([2, cy-r, 2+2*r, cy+r], fill=c)
            d.ellipse([s-2-2*r, cy-r, s-2, cy+r], fill=c)
            # Chain link between them
            d.rectangle([cx-4, cy-2, cx-1, cy+2], outline=c, width=1)
            d.rectangle([cx+1, cy-2, cx+4, cy+2], outline=c, width=1)

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
            # Selected face: square with dimmed fill + strong outline
            d.rectangle([4, 4, s-4, s-4], fill='#404060', outline=c, width=2)

        def ico_sel_edge(d, s, c):
            # Grey polygon + highlighted edge
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline='#505065')
            d.line([s//2, 3, s-3, s-3], fill=c, width=3)

        def ico_sel_vertex(d, s, c):
            # Grey polygon + highlighted vertex
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline='#505065')
            r = 3
            cx, cy = s//2, 3
            d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=c)

        # ── Layout ────────────────────────────────────────────────────────────
        add_btn(make_icon(ico_new),          self._new_project,       "New project (Ctrl+N)")
        add_sep()
        add_btn(make_icon(ico_load),         self._load_json_dialog,  "Open")
        add_btn(make_icon(ico_import),       self._import_json_dialog, "Import")
        add_btn(make_icon(ico_save),         self._save_json_dialog,  "Save as…")
        add_btn(make_icon(ico_save_current), self._save_json,         "Save (Ctrl+S)")
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
                "Duplicate", "C")
        add_btn(make_icon(ico_delete),
                self._cmd_delete,
                "Delete", "Del")
        add_sep()
        add_btn(make_icon(ico_group),
                self._cmd_group,
                "Group", "G")
        add_btn(make_icon(ico_ungroup),
                self._cmd_ungroup,
                "Ungroup", "H")
        add_sep()

        # Gizmo buttons (radio-style) — highlighted based on self.gizmo.mode
        def set_gizmo(mode):
            self.gizmo.mode = mode
            self._sync_gizmo_btns()

        for mode, ifn, lbl in [('translate', ico_translate, "Translate"),
                                ('rotate',    ico_rotate,    "Rotate"),
                                ('scale',     ico_scale,     "Scale")]:
            b = add_btn(make_icon(ifn), lambda m=mode: set_gizmo(m), lbl, "Space")
            self._gizmo_btns[mode] = (b, BG, BG_ON)

        self._sync_gizmo_btns()
        add_sep()

        # Selection mode buttons (radio-style)
        def set_sel_mode(mode):
            self.sel_mode_var.set({'polygon': 'Polygon', 'edge': 'Edge', 'vertex': 'Vertex'}[mode])
            self._on_selection_mode_change()

        for mode, ifn, lbl in [('polygon', ico_sel_polygon, "Polygon"),
                                ('edge',    ico_sel_edge,    "Edge"),
                                ('vertex',  ico_sel_vertex,  "Vertex")]:
            b = add_btn(make_icon(ifn), lambda m=mode: set_sel_mode(m), lbl, "E")
            self._sel_btns[mode] = (b, BG, BG_ON)

        self._sync_sel_mode_btns()
        add_sep()

        # ── Snap ─────────────────────────────────────────────────────────────
        tk.Label(self.toolbar, text="Snap:", bg=BG, fg='#c8c8d8',
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

        self._btn_snap_grid = add_btn(make_icon(ico_snap_grid), self._toggle_snap_grid,
                                      "Grid snap")
        self._btn_vertex_glue = add_btn(make_icon(ico_vertex_glue), self._toggle_vertex_glue,
                                        "Vertex Glue", "V")

    # ── Second toolbar ────────────────────────────────────────────────────────
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

        # ── Layout ────────────────────────────────────────────────────────────
        add_btn(self._cmd_flip_orientation,
                "Flip orientation", "N")
        add_btn(self._cmd_rotate_vertices,
                "Rotate Vertices", "R")
        self._sep_edges = tk.Frame(self.toolbar2, width=1, bg='#38384a')
        self._sep_edges.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self._btn_create_from_edges = add_btn(self._cmd_create_from_edges,
                                              "Create polygon from edges")
        self._sep_split = tk.Frame(self.toolbar2, width=1, bg='#38384a')
        self._btn_split = add_btn(self._cmd_split_quad, "Split")
        self._sync_toolbar2_btns()

    def _on_snap_change(self, *_):
        v = float(self._snap_var.get())
        self.gizmo.translate_snap = v
        self.gizmo.scale_snap     = v

    def _toggle_snap_grid(self):
        self.gizmo.snap_to_grid = not self.gizmo.snap_to_grid
        self._btn_snap_grid.config(bg='#2d4080' if self.gizmo.snap_to_grid else '#16161f')

    def _toggle_vertex_glue(self):
        self.state.vertex_glue = not self.state.vertex_glue
        self._btn_vertex_glue.config(bg='#2d4080' if self.state.vertex_glue else '#16161f')

    def _sync_toolbar2_btns(self):
        two_edges = len(self.state.selected_edges) == 2
        widgets = [self._sep_edges, self._btn_create_from_edges]
        for w in widgets:
            if two_edges:
                w.pack(side=tk.LEFT, fill=tk.Y if w is self._sep_edges else tk.NONE,
                       padx=5 if w is self._sep_edges else 1,
                       pady=5 if w is self._sep_edges else 2)
            else:
                w.pack_forget()

        one_quad = (self.state.selection_mode == 'polygon'
                    and len(self.state.selected_polygons) == 1
                    and len(self.state.selected_polygons[0].vertices) == 4)
        for w in (self._sep_split, self._btn_split):
            if one_quad:
                w.pack(side=tk.LEFT, fill=tk.Y if w is self._sep_split else tk.NONE,
                       padx=5 if w is self._sep_split else 1,
                       pady=5 if w is self._sep_split else 2)
            else:
                w.pack_forget()
        if one_quad:
            coplanar = self._quad_is_coplanar(self.state.selected_polygons[0])
            if coplanar:
                self._btn_split.config(state='normal', cursor='hand2',
                                       bg='#16161f')
            else:
                self._btn_split.config(state='disabled', cursor='',
                                       bg=self._BG_DIS)

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

    # ── UI construction ───────────────────────────────────────────────────────
    def _build_panel(self):
        self.panel = tk.Frame(self.root, width=self.panel_width, bg='#1a1a21')
        self.panel.pack(side=tk.LEFT, fill=tk.Y)
        self.panel.pack_propagate(False)

        self.uv_selector = UVSelector(self.panel, self.scene,
                                      on_uv_assigned=self._cmd_uv_assigned)
        self.uv_selector.pack(fill=tk.BOTH, expand=True)

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
            sel_text = 'No selection'
        elif n == 1:
            sel_text = '1 polygon selected'
        else:
            sel_text = f'{n} polygons selected'
        self._status_sel_lbl.config(text=sel_text)

        grp = self.state.current_group
        grp_name = getattr(grp, 'name', None) or 'Root'
        self._status_group_lbl.config(text=f'Group: {grp_name}')

        mode_labels = {'translate': 'Translate', 'rotate': 'Rotate', 'scale': 'Scale'}
        sel_mode_labels = {'polygon': 'Polygon', 'edge': 'Edge', 'vertex': 'Vertex'}
        right = (f"Gizmo: {mode_labels.get(self.gizmo.mode, self.gizmo.mode)}   "
                 f"Mode: {sel_mode_labels.get(self.state.selection_mode, self.state.selection_mode)}")
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

    def _build_right_panel(self):
        self.right_panel = tk.Frame(self.root, width=self.right_panel_width, bg='#1a1a21')
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self.right_panel.pack_propagate(False)

        self.group_panel = GroupPanel(self.right_panel, self.scene, self)
        self.group_panel.pack(fill=tk.BOTH, expand=True)

    def _build_right_resize_bar(self):
        self._right_sep = tk.Frame(self.root, width=_SEP_WIDTH, bg='#2a2a3a',
                                   cursor='sb_h_double_arrow')
        self._right_sep.pack(side=tk.RIGHT, fill=tk.Y)
        self._right_sep.bind('<ButtonPress-1>',   self._on_right_sep_press)
        self._right_sep.bind('<ButtonRelease-1>', self._on_right_sep_release)
        self._right_sep.bind('<Motion>',          self._on_right_sep_motion)
        self._right_sep.bind('<Enter>', lambda _: self._right_sep.config(bg='#3e3e5a'))
        self._right_sep.bind('<Leave>', lambda _: self._right_sep.config(
            bg='#2a2a3a' if not self._right_resizing else '#3e3e5a'))

    def _on_right_sep_press(self, event):
        self._right_resizing        = True
        self._right_resize_start_x  = event.x_root
        self._right_resize_start_pw = self.right_panel_width

    def _on_right_sep_release(self, _):
        self._right_resizing = False
        self._right_sep.config(bg='#2a2a3a')

    def _on_right_sep_motion(self, event):
        if not self._right_resizing:
            return
        dx = self._right_resize_start_x - event.x_root
        new_pw = max(_PANEL_MIN_WIDTH, min(_PANEL_MAX_WIDTH,
                                           self._right_resize_start_pw + dx))
        new_vw = self.root.winfo_width() - self.panel_width - _SEP_WIDTH * 2 - new_pw
        if new_vw < 200:
            return
        self.right_panel_width = new_pw
        self.right_panel.config(width=new_pw)
        self.viewport.config(width=new_vw)
        self.camera.vw = new_vw

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
        new_vw = self.root.winfo_width() - new_pw - _SEP_WIDTH * 2 - self.right_panel_width
        if new_vw < 200:
            return
        self.panel_width = new_pw
        self.panel.config(width=new_pw)
        self.viewport.config(width=new_vw)
        self.camera.vw = new_vw

    # ── Event bindings ────────────────────────────────────────────────────────
    def _bind_events(self):
        self.viewport.bind('<Button-1>',        self._on_mouse_down)
        self.viewport.bind('<ButtonRelease-1>', self._on_mouse_up)
        self.viewport.bind('<Button-2>',        self._on_middle_down)
        self.viewport.bind('<ButtonRelease-2>', self._on_middle_up)
        self.viewport.bind('<Motion>',          self._on_mouse_motion)
        self.viewport.bind('<B2-Motion>',       self._on_pan_motion)
        self.viewport.bind('<MouseWheel>',      self._on_mouse_wheel)
        self.root.bind('<KeyPress>',            self._on_key_press)
        self.root.bind('<KeyRelease>',          self._on_key_release)

    # ── Mouse events ──────────────────────────────────────────────────────────
    def _on_mouse_down(self, event):
        self.viewport.focus_set()
        self.mouse_btn1 = True
        self.mouse_x, self.mouse_y = event.x, event.y
        face = self.view_cube.hit_test(event.x, event.y, self.camera.vw, self.camera.vh, self.camera)
        if face:
            self.view_cube.snap_to_face(face, self.camera)
            return
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

    def _on_pan_motion(self, event):
        self.mouse_x, self.mouse_y = event.x, event.y
        if not self.panning:
            return
        dx = event.x_root - self.pan_last_x
        dy = event.y_root - self.pan_last_y
        if dx or dy:
            self.camera.apply_mouse_look(dx, dy)
            cx = self.viewport.winfo_rootx() + self.viewport.winfo_width() // 2
            cy = self.viewport.winfo_rooty() + self.viewport.winfo_height() // 2
            ctypes.windll.user32.SetCursorPos(cx, cy)
            self.pan_last_x = cx
            self.pan_last_y = cy

    # ── Viewport focus ────────────────────────────────────────────────────────
    def _on_viewport_focus_in(self, _event):
        self._viewport_focused = True

    def _on_viewport_focus_out(self, _event):
        self._viewport_focused = False
        self.keys_pressed.clear()

    # ── Keyboard events ───────────────────────────────────────────────────────
    def _on_key_press(self, event):
        if not self._viewport_focused:
            return
        key = event.keysym.lower()
        self.keys_pressed.add(key)
        self._handle_keyboard(key)

    def _on_key_release(self, event):
        self.keys_pressed.discard(event.keysym.lower())

    def _on_selection_mode_change(self, event=None):
        mode_map = {'Polygon': 'polygon', 'Edge': 'edge', 'Vertex': 'vertex'}
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
            self._cmd_rotate_vertices()

        if key == 'n' and self.scene.selected_indices:
            self._cmd_flip_orientation()

        if key == 'v':
            self._toggle_vertex_glue()

        if key == 'escape':
            self.state.clear_selection()

        if key == 'e':
            modes = ['polygon', 'edge', 'vertex']
            next_mode = modes[(modes.index(self.state.selection_mode) + 1) % len(modes)]
            self.sel_mode_var.set({'polygon': 'Polygon', 'edge': 'Edge', 'vertex': 'Vertex'}[next_mode])
            self._on_selection_mode_change()

        if key in ('prior', 'next'):   # PageUp / PageDown
            idx = SNAP_VALUES.index(self._snap_var.get()) if self._snap_var.get() in SNAP_VALUES else 0
            if key == 'prior' and idx > 0:
                self._snap_var.set(SNAP_VALUES[idx - 1])
            elif key == 'next' and idx < len(SNAP_VALUES) - 1:
                self._snap_var.set(SNAP_VALUES[idx + 1])
            self._on_snap_change()


    # ── Commands with history ─────────────────────────────────────────────────

    def _record_added_polygons(self, before_ids: set) -> None:
        """Records newly added polygons (since before_ids) as a history command."""
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

    def _cmd_rotate_vertices(self) -> None:
        polys = self.state.selected_polygons
        if not polys:
            return
        before = {p: (list(p.vertices), list(p.uvs)) for p in polys}
        self.scene.rotate_vertices()
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

    def _quad_is_coplanar(self, poly) -> bool:
        """Returns True if all 4 vertices of the quad lie in the same plane."""
        v = poly.vertices
        n1 = normalize(cross(vsub(v[1], v[0]), vsub(v[2], v[0])))
        n2 = normalize(cross(vsub(v[2], v[0]), vsub(v[3], v[0])))
        return dot(n1, n2) > 0.9998

    def _cmd_split_quad(self) -> None:
        self.state.quad_splitting_mode = True

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
        new_group = Group(name="Group")
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
        ctrl_held = 'shift_l' in self.keys_pressed  # Shift for multi-select
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

    def _cmd_project_info(self):
        from editor.project_info_dialog import ProjectInfoDialog
        dlg = ProjectInfoDialog(self.root, self.state)
        if dlg._confirmed:
            self._update_title()

    def _cmd_textures_atlas(self):
        from editor.texture_atlas_dialog import TextureAtlasDialog
        TextureAtlasDialog(self.root, self.state)

    def _new_project(self):
        if self.state.modified:
            if not messagebox.askyesno(
                "New project",
                "The current project has unsaved changes.\n"
                "Do you want to continue and lose the changes?",
                icon='warning',
            ):
                return
        # Reset the scene
        self.scene.root.children.clear()
        self.scene.root.polygons.clear()
        self.scene.root.hidden = False
        # Reset the state
        self.state._current_group = self.scene.root
        self.state._selected_polygons = []
        self.state._selected_edges = []
        self.state._selected_vertices = []
        self.state._project_path = ""
        self.state._project_name = ""
        self.state._modified = False
        # Reset history and gizmo
        self.history.clear()
        self.gizmo.stop_drag()
        # Notifie les composants
        self.state._emit("scene_changed", change_type="new_project")
        self.state._emit("selection_changed",
                         polygons=[], edges=[], vertices=[],
                         mode=self.state.selection_mode)
        self._update_title()

    def _save_json(self):
        path = self.state.project_path
        if not path:
            self._save_json_dialog()
            return
        self.scene.save_json(path)
        self.state.mark_saved()
        self._update_title()

    def _save_json_dialog(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Save scene",
        )
        if path:
            self.state.project_path = path
            self.scene.save_json(path)
            self.state.mark_saved()
            self._update_title()

    def _load_json_dialog(self):
        if self.state.modified:
            if not messagebox.askyesno(
                "Unsaved project",
                "The current project has unsaved changes.\n"
                "Do you still want to load another project and lose your changes?",
                parent=self.root,
            ):
                return

        path = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON", "*.json")],
            title="Load scene",
        )
        if path:
            # Clear the scene before loading
            self.scene.root.children.clear()
            self.scene.root.polygons.clear()
            self.state.clear_selection()
            self.state._current_group = self.scene.root
            self.history.clear()

            self.state.project_path = path
            self.scene.load_json(path)
            self.gizmo.stop_drag()
            self.state.mark_saved()
            self._update_title()

    def _import_json_dialog(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            filetypes=[("JSON", "*.json")],
            title="Import scene",
        )
        if path:
            self.scene.import_json(path)
            self.gizmo.stop_drag()
            self._update_title()

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
        """Applies selection based on Shift — goes through the StateManager."""
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

    # ── Update ────────────────────────────────────────────────────────────────
    def _update_title(self):
        name = self.state.project_name or "Unnamed Project"
        title = f"Quad Maker - {name}"
        if self.state.modified:
            title += " - [unsaved]"
        self.root.title(title)

    def _update_loop(self):
        now = time.time()
        dt  = now - self.last_time
        self.last_time = now

        if self.gizmo.dragging_axis and self.mouse_btn1:
            self.gizmo.update_drag(self.mouse_x, self.mouse_y, self.state, self.camera)

        self.camera.apply_movement(self.keys_pressed, dt, panning=self.panning)
        self.view_cube.update(self.camera, dt)
        self._update_statusbar()

        self.root.after(32, self._update_loop)

    # ── Rendering ─────────────────────────────────────────────────────────────
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
        self.view_cube.draw(self.camera, vw, vh)
