"""App class: Tkinter/pyopengltk initialization, main loop, event handling."""

import math
import time
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageDraw, ImageTk

from pyopengltk import OpenGLFrame
from OpenGL.GL import (
    glEnable, glDisable, glClearColor, glClear, glViewport,
    glMatrixMode, glLoadIdentity, glRotatef, glTranslatef,
    glColor3f, glBegin, glEnd, glVertex3f, glLineWidth,
    GL_DEPTH_TEST, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_PROJECTION, GL_MODELVIEW, GL_LINES,
)
from OpenGL.GLU import gluPerspective

from editor.constants import (PANEL_WIDTH, VIEW_WIDTH, HEIGHT,
                               FOV, NEAR, FAR)

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
from editor.uv_selector          import UVSelector
from editor.group_panel          import GroupPanel
from editor.gizmo_position_panel import GizmoPositionPanel
from editor.state_manager import StateManager
from editor.history       import (HistoryManager, AddPolygonsCommand,
                                   DeletePolygonsCommand, PolyDataCommand,
                                   GroupCommand, UngroupCommand,
                                   ExtrudeEdgesCommand, AddGroupCommand,
                                   DeleteGroupCommand, CompoundCommand)
from editor.group         import Group, Polygon, all_polygons
from editor.math3d        import (normalize, cross, vsub, vadd, vscale, dot,
                                  vlength, ray_plane_intersect,
                                  closest_point_on_seg)
from editor.texture_atlas import TextureAtlas


class Viewport3D(OpenGLFrame):
    """OpenGL widget embedded in Tkinter via pyopengltk."""

    def __init__(self, master, app, **kw):
        super().__init__(master, **kw)
        self._app = app

    def initgl(self):
        glEnable(GL_DEPTH_TEST)
        glClearColor(0.08, 0.08, 0.12, 1.0)

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
        # ── Extrusion mode state ──────────────────────────────────────────────
        self._extrude_prev_gizmo_mode  = 'translate'  # mode to restore on exit
        self._extrude_history_depth    = 0            # undo depth before extrusion

        # ── Polygon-split drag state ──────────────────────────────────────────
        self._split_polygon    = None   # Polygon being split
        self._split_dir        = None   # Direction parallel to nearest edge
        self._split_perp       = None   # Perpendicular direction in polygon plane
        self._split_origin     = None   # Reference vertex for local coords
        self._split_seg        = None   # (pt_a, pt_b) current 3D segment or None
        self._splitting_active = False  # True while mouse button is held

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

        self.state.subscribe('selection_changed', lambda **_: self._on_selection_changed())
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
        add_btn(make_icon(ico_save_current), self._save_json,         "Save (Ctrl+S)")
        add_btn(make_icon(ico_save),         self._save_json_dialog,  "Save as…")
        add_sep()
        add_btn(make_icon(ico_import),       self._import_json_dialog, "Import")
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
        self._btn_split = add_btn(self._cmd_split_polygon, "Split [K]")
        self._sep_extrude = tk.Frame(self.toolbar2, width=1, bg='#38384a')
        self._btn_extrude = add_btn(self._cmd_start_extrusion, "Extrude")
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

    def _on_selection_changed(self):
        if self.state.extrusion_mode and not self.state.selected_edges:
            self._cmd_exit_extrusion(confirm=True)
            return
        self._sync_toolbar2_btns()

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

        one_poly = (self.state.selection_mode == 'polygon'
                    and len(self.state.selected_polygons) == 1)
        for w in (self._sep_split, self._btn_split):
            if one_poly:
                w.pack(side=tk.LEFT, fill=tk.Y if w is self._sep_split else tk.NONE,
                       padx=5 if w is self._sep_split else 1,
                       pady=5 if w is self._sep_split else 2)
            else:
                w.pack_forget()
        if one_poly:
            coplanar = self._poly_is_coplanar(self.state.selected_polygons[0])
            if coplanar:
                self._btn_split.config(state='normal', cursor='hand2',
                                       bg='#16161f')
            else:
                self._btn_split.config(state='disabled', cursor='',
                                       bg=self._BG_DIS)

        has_edges = (self.state.selection_mode == 'edge'
                     and len(self.state.selected_edges) >= 1
                     and not self.state.extrusion_mode)
        for w in (self._sep_extrude, self._btn_extrude):
            if has_edges:
                w.pack(side=tk.LEFT, fill=tk.Y if w is self._sep_extrude else tk.NONE,
                       padx=5 if w is self._sep_extrude else 1,
                       pady=5 if w is self._sep_extrude else 2)
            else:
                w.pack_forget()

    def _refresh_group_panel(self):
        if hasattr(self, 'group_panel'):
            self.group_panel.refresh()

    def _sync_gizmo_btns(self):
        restricted = self.state.selection_mode in ('vertex', 'edge')
        extruding  = self.state.extrusion_mode
        for mode, (btn, bg_off, bg_on) in self._gizmo_btns.items():
            disabled = extruding or (restricted and mode in ('rotate', 'scale'))
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

        self.gizmo_position_panel = GizmoPositionPanel(
            self.right_panel, self.state, self.gizmo, self.history)
        self.gizmo_position_panel.pack(fill=tk.X)

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
        self._splitting_active = False
        self.gizmo.finish_drag(self.history, self.state)

    def _on_mouse_wheel(self, event):
        self.camera.apply_scroll(event.delta / 120)

    def _on_middle_down(self, event):
        self.viewport.focus_set()
        self.panning = True
        self.pan_anchor_x = event.x_root
        self.pan_anchor_y = event.y_root
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
            ctypes.windll.user32.SetCursorPos(self.pan_anchor_x, self.pan_anchor_y)
            self.pan_last_x = self.pan_anchor_x
            self.pan_last_y = self.pan_anchor_y

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
        if key == 'delete' and (self.scene.selected_indices or self.state.selected_groups):
            self._cmd_delete()

        if key == 'c':
            self._cmd_duplicate()

        if key == 'space' and (self.scene.selected_indices or self.state.selected_groups) and not self.state.extrusion_mode:
            self.gizmo.cycle_mode()
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

        if key == 'k':
            one_poly = (self.state.selection_mode == 'polygon'
                        and len(self.state.selected_polygons) == 1)
            if one_poly and self._poly_is_coplanar(self.state.selected_polygons[0]):
                self._cmd_split_polygon()

        if key == 'return':
            if self.state.polygon_splitting_mode:
                self._cmd_confirm_polygon_split()
            elif self.state.extrusion_mode:
                self._cmd_exit_extrusion(confirm=True)

        if key == 'escape':
            if self.state.polygon_splitting_mode:
                self._cmd_split_polygon_escape()
            elif self.state.extrusion_mode:
                self._cmd_exit_extrusion(confirm=False)
            else:
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
        if self.state.selected_groups:
            new_groups = self.scene.duplicate_selected_groups()
            if not new_groups:
                return
            cmds = [AddGroupCommand(self.state, g, g.parent) for g in new_groups]
            if self.state.selected_polygons:
                before_ids = {id(p) for p in all_polygons(self.scene.root)}
                self.scene.duplicate_selected()
                new_polys = [p for p in all_polygons(self.scene.root)
                             if id(p) not in before_ids]
                if new_polys:
                    cmds.append(AddPolygonsCommand(self.state, new_polys))
            cmd = cmds[0] if len(cmds) == 1 else CompoundCommand(cmds)
            self.history.record(cmd)
        else:
            before_ids = {id(p) for p in all_polygons(self.scene.root)}
            self.scene.duplicate_selected()
            self._record_added_polygons(before_ids)

    def _cmd_delete(self) -> None:
        commands = []

        groups = self.state.selected_groups
        if groups:
            for g in groups:
                commands.append(DeleteGroupCommand(self.state, g))

        polys = self.state.selected_polygons
        if polys:
            saved = []
            for p in polys:
                if p.group is not None:
                    try:
                        idx = p.group.polygons.index(p)
                    except ValueError:
                        idx = len(p.group.polygons)
                    saved.append((p, p.group, idx))
            if saved:
                commands.append(DeletePolygonsCommand(self.state, saved))

        if not commands:
            return
        if len(commands) == 1:
            self.history.push(commands[0])
        else:
            self.history.push(CompoundCommand(commands))
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

    def _poly_is_coplanar(self, poly) -> bool:
        """Returns True if all vertices of the polygon lie in the same plane."""
        v = poly.vertices
        if len(v) <= 3:
            return True
        n0 = normalize(cross(vsub(v[1], v[0]), vsub(v[2], v[0])))
        for i in range(3, len(v)):
            ni = normalize(cross(vsub(v[i - 1], v[0]), vsub(v[i], v[0])))
            if dot(n0, ni) <= 0.9998:
                return False
        return True

    def _cmd_start_extrusion(self) -> None:
        """Enter extrusion mode: create a quad face for each selected edge, then
        select the new top edges so the translate gizmo can move them."""
        edges = list(self.state.selected_edges)
        if not edges:
            return

        new_polys: list[Polygon] = []
        new_top_edges: list[tuple] = []

        for poly, edge_idx in edges:
            n = len(poly.vertices)
            v0 = tuple(poly.vertices[edge_idx])
            v1 = tuple(poly.vertices[(edge_idx + 1) % n])
            uv0 = tuple(poly.uvs[edge_idx]) if edge_idx < len(poly.uvs) else (0.0, 0.0)
            uv1 = tuple(poly.uvs[(edge_idx + 1) % n]) if len(poly.uvs) > 0 else (0.0, 0.0)

            # New quad: bottom=original edge (reversed for correct outward normal),
            # top=copy at same position. Vertex layout: [v1, v0, v0_copy(2), v1_copy(3)]
            new_poly = Polygon(
                vertices=[list(v1), list(v0), list(v0), list(v1)],
                uvs=[list(uv1), list(uv0), list(uv0), list(uv1)],
            )
            new_poly.texture_atlas_id = poly.texture_atlas_id
            target = poly.group if poly.group is not None else self.state.root_group
            target.adopt_polygon(new_poly)

            new_polys.append(new_poly)
            new_top_edges.append((new_poly, 2))  # edge 2 = v1_copy -> v0_copy

        self.state._emit("scene_changed", change_type="polygon_added")
        self._extrude_history_depth = self.history.depth  # depth before recording
        cmd = ExtrudeEdgesCommand(self.state, new_polys, edges, new_top_edges)
        self.history.record(cmd)

        self.state.set_selection(edges=new_top_edges, polygons=[])

        self._extrude_prev_gizmo_mode = self.gizmo.mode
        self.state.extrusion_mode = True
        self.state.selection_enable = False
        self.gizmo.mode = 'translate'
        self._sync_gizmo_btns()
        self._sync_toolbar2_btns()

    def _cmd_exit_extrusion(self, confirm: bool = True) -> None:
        """Exit extrusion mode.
        confirm=True  (Enter)  — keep the extruded faces.
        confirm=False (Escape) — undo all actions done during extrusion.
        """
        if not confirm:
            # Undo every command recorded since extrusion started
            # (gizmo transforms + the ExtrudeEdgesCommand itself)
            while self.history.depth > self._extrude_history_depth:
                self.history.undo()
        self.state.extrusion_mode = False
        self.state.selection_enable = True
        self.gizmo.mode = self._extrude_prev_gizmo_mode
        self._sync_gizmo_btns()
        self._sync_toolbar2_btns()

    def _cmd_split_polygon(self) -> None:
        self.state.polygon_splitting_mode = True
        self.state.selection_enable = False
        self.state.gizmo_enable = False

    def _cmd_split_polygon_escape(self) -> None:
        self.state.polygon_splitting_mode = False
        self.state.selection_enable = True
        self.state.gizmo_enable = True
        self._split_polygon = None
        self._split_seg = None
        self._splitting_active = False

    # ── Polygon-split helpers ────────────────────────────────────────────────────

    def _start_polygon_split(self, mx, my):
        """Begin a polygon-split drag: create a blue segment parallel to the
        nearest edge of the polygon under the cursor."""
        ray_o = tuple(self.camera.pos)
        ray_d = self.camera.screen_ray(mx, my)

        poly_idx = self.scene.pick_polygon(ray_o, ray_d)
        if poly_idx < 0:
            return

        poly_obj = all_polygons(self.scene.root)[poly_idx]
        verts = [tuple(v) for v in poly_obj.vertices]
        if len(verts) < 3:
            return

        # Polygon normal and hit point on its plane
        normal = normalize(cross(vsub(verts[1], verts[0]), vsub(verts[2], verts[0])))
        hit = ray_plane_intersect(ray_o, ray_d, verts[0], normal)
        if hit is None:
            return

        # Find the nearest edge to the hit point
        best_edge, best_dist = 0, float('inf')
        n = len(verts)
        for ei in range(n):
            cp = closest_point_on_seg(hit, verts[ei], verts[(ei + 1) % n])
            d = vlength(vsub(hit, cp))
            if d < best_dist:
                best_dist, best_edge = d, ei

        # Split direction = direction of the nearest edge
        ea = verts[best_edge]
        eb = verts[(best_edge + 1) % n]
        split_dir = normalize(vsub(eb, ea))
        split_perp = normalize(cross(normal, split_dir))

        self._split_polygon = poly_obj
        self._split_dir = split_dir
        self._split_perp = split_perp
        self._split_origin = verts[0]
        self._splitting_active = True

        # Initial segment position at the hit point
        pv = dot(vsub(hit, verts[0]), split_perp)
        self._split_seg = self._compute_split_segment(verts, split_dir, split_perp, verts[0], pv)

    def _compute_split_segment(self, verts, split_dir, split_perp, origin, pv):
        """Return (pt_a, pt_b) where the parallel line at perpendicular
        offset pv intersects the polygon's boundary edges, or None."""
        intersections = []
        n = len(verts)
        for ei in range(n):
            a = verts[ei]
            b = verts[(ei + 1) % n]
            av = dot(vsub(a, origin), split_perp)
            bv = dot(vsub(b, origin), split_perp)
            dv = bv - av
            if abs(dv) < 1e-8:
                continue  # edge parallel to split line
            t = (pv - av) / dv
            if -1e-5 <= t <= 1.0 + 1e-5:
                t = max(0.0, min(1.0, t))
                pt = vadd(a, vscale(vsub(b, a), t))
                intersections.append(pt)
        if len(intersections) >= 2:
            intersections.sort(key=lambda p: dot(vsub(p, origin), split_dir))
            return (intersections[0], intersections[-1])
        return None

    def _update_polygon_split(self, mx, my):
        """Update the split segment to stay under the mouse pointer."""
        if self._split_polygon is None:
            return
        verts = [tuple(v) for v in self._split_polygon.vertices]
        if len(verts) < 3:
            return
        normal = normalize(cross(vsub(verts[1], verts[0]), vsub(verts[2], verts[0])))
        hit = ray_plane_intersect(
            tuple(self.camera.pos), self.camera.screen_ray(mx, my), verts[0], normal
        )
        if hit is None:
            return
        pv = dot(vsub(hit, self._split_origin), self._split_perp)
        self._split_seg = self._compute_split_segment(
            verts, self._split_dir, self._split_perp, self._split_origin, pv
        )

    def _cmd_confirm_polygon_split(self):
        """Confirm the current split segment: create two polygons and delete the original."""
        if self._split_seg is None or self._split_polygon is None:
            return
        pt_a, pt_b = self._split_seg
        poly = self._split_polygon
        verts = [tuple(v) for v in poly.vertices]
        uvs   = [tuple(u) for u in poly.uvs]
        n = len(verts)

        def find_edge_and_t(pt):
            """Return (edge_index, t) of the closest edge to pt."""
            best_ei, best_t, best_dist = 0, 0.0, float('inf')
            for ei in range(n):
                a, b = verts[ei], verts[(ei + 1) % n]
                ab   = vsub(b, a)
                len2 = dot(ab, ab)
                t    = max(0.0, min(1.0, dot(vsub(pt, a), ab) / len2)) if len2 > 1e-10 else 0.0
                cp   = vadd(a, vscale(ab, t))
                d    = vlength(vsub(pt, cp))
                if d < best_dist:
                    best_dist, best_ei, best_t = d, ei, t
            return best_ei, best_t

        def lerp_uv(uv0, uv1, t):
            return (uv0[0] + t * (uv1[0] - uv0[0]), uv0[1] + t * (uv1[1] - uv0[1]))

        ei_a, t_a = find_edge_and_t(pt_a)
        ei_b, t_b = find_edge_and_t(pt_b)
        if ei_a == ei_b:
            return  # both endpoints on the same edge — degenerate, skip

        uv_a = lerp_uv(uvs[ei_a], uvs[(ei_a + 1) % n], t_a)
        uv_b = lerp_uv(uvs[ei_b], uvs[(ei_b + 1) % n], t_b)

        def walk_polygon(start_pt, start_uv, from_idx, stop_idx, end_pt, end_uv):
            """Collect vertices walking from from_idx up to (but not including) stop_idx."""
            vs, us = [start_pt], [start_uv]
            i = from_idx % n
            while i != stop_idx % n:
                vs.append(verts[i])
                us.append(uvs[i])
                i = (i + 1) % n
            vs.append(end_pt)
            us.append(end_uv)
            return vs, us

        # Polygon 1: pt_a → vertices from (ei_a+1) to ei_b included → pt_b
        verts1, uvs1 = walk_polygon(pt_a, uv_a, (ei_a + 1) % n, (ei_b + 1) % n, pt_b, uv_b)
        # Polygon 2: pt_b → vertices from (ei_b+1) to ei_a included → pt_a
        verts2, uvs2 = walk_polygon(pt_b, uv_b, (ei_b + 1) % n, (ei_a + 1) % n, pt_a, uv_a)

        if len(verts1) < 3 or len(verts2) < 3:
            return

        from editor.group import Polygon as PolyObj
        new_poly1 = PolyObj(verts1, uvs1)
        new_poly1.texture_atlas_id = poly.texture_atlas_id
        new_poly2 = PolyObj(verts2, uvs2)
        new_poly2.texture_atlas_id = poly.texture_atlas_id

        from editor.history import SplitPolygonCommand
        cmd = SplitPolygonCommand(self.state, poly, new_poly1, new_poly2)
        self.history.push(cmd)

        # Exit split mode after confirming
        self._cmd_split_polygon_escape()

    def _cmd_create_from_edges(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.create_polygon_from_edges(self.state.current_group)
        self._record_added_polygons(before_ids)

    def _cmd_group(self) -> None:
        polys       = self.state.selected_polygons
        sub_groups  = self.state.selected_groups
        if len(polys) + len(sub_groups) < 2:
            return
        old_groups  = {p: (p.group, p.group.polygons.index(p)) for p in polys}
        old_parents = {g: (g.parent, g.parent.children.index(g)) for g in sub_groups}
        parent      = self.scene.root
        new_group   = Group(name="Group")
        self.history.push(GroupCommand(self.state, polys, old_groups,
                                       new_group, parent,
                                       sub_groups=sub_groups,
                                       old_parents=old_parents))

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
        if self.state.polygon_splitting_mode:
            self._start_polygon_split(mx, my)
            return

        ctrl_held = 'shift_l' in self.keys_pressed  # Shift for multi-select
        multi     = len(self.scene.selected_indices) > 1 or bool(self.state.selected_groups)
        sel_mode  = self.state.selection_mode
        gizmo_on  = self.state.gizmo_enable

        if sel_mode == 'edge' and self.state.selected_edges:
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera) if gizmo_on else None
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            else:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            return

        if sel_mode == 'vertex' and self.state.selected_vertices:
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera) if gizmo_on else None
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            else:
                self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if sel_mode == 'vertex':
            self._apply_vertex_selection(self._pick_vertex(mx, my), ctrl_held)
            return

        if self.gizmo.mode == 'translate' or (multi and self.gizmo.mode == 'scale'):
            axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera) if gizmo_on else None
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._handle_polygon_click(mx, my, ctrl_held)

        elif self.gizmo.mode == 'rotate':
            axis = self.gizmo.pick_rotate_axis(mx, my, self.state, self.camera) if gizmo_on else None
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._handle_polygon_click(mx, my, ctrl_held)

        else:  # scale
            handle = self.gizmo.pick_scale_handle(mx, my, self.state, self.camera) if gizmo_on else None
            if handle:
                self.gizmo.start_drag(handle, mx, my, self.state, self.camera)
            elif sel_mode == 'edge':
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            else:
                self._handle_polygon_click(mx, my, ctrl_held)

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
        # Reset camera
        self.camera.pos   = [0.0, 3.0, 8.0]
        self.camera.yaw   = 0.0
        self.camera.pitch = -20.0
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

    def _pick_locked_group(self, mx, my):
        return self.scene.pick_locked_group(tuple(self.camera.pos), self.camera.screen_ray(mx, my))

    def _apply_locked_group_selection(self, group, shift_held):
        current = list(self.state.selected_groups)
        if shift_held:
            if group in current:
                current.remove(group)
            else:
                current.append(group)
        else:
            current = [group]
            self.state.set_selection(polygons=[], edges=[], vertices=[])
        self.state.selected_groups = current

    def _handle_polygon_click(self, mx, my, shift_held):
        idx = self._pick_polygon(mx, my)
        if idx >= 0:
            if not shift_held:
                self.state.selected_groups = []
            self._apply_selection(idx, shift_held)
        else:
            group = self._pick_locked_group(mx, my)
            if group is not None:
                self._apply_locked_group_selection(group, shift_held)
            else:
                if not shift_held:
                    self.state.selected_groups = []
                self._apply_selection(-1, shift_held)

    def _apply_vertex_selection(self, vertex, ctrl_held):
        if not self.state.selection_enable:
            return
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
        if not self.state.selection_enable:
            return
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
        if not self.state.selection_enable:
            return
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

        if self.state.polygon_splitting_mode and self._splitting_active and self.mouse_btn1:
            self._update_polygon_split(self.mouse_x, self.mouse_y)
        elif self.state.gizmo_enable and self.gizmo.dragging_axis and self.mouse_btn1:
            self.gizmo.update_drag(self.mouse_x, self.mouse_y, self.state, self.camera)

        self.camera.apply_movement(self.keys_pressed, dt, panning=self.panning)
        self.view_cube.update(self.camera, dt)
        self._update_statusbar()

        self.root.after(16, self._update_loop)

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
        if self.state.gizmo_enable:
            self.gizmo.draw(self.state, self.camera)
        self.view_cube.draw(self.camera, vw, vh)

        # ── Quad-split segment ─────────────────────────────────────────────
        if self.state.polygon_splitting_mode and self._split_seg is not None:
            pt_a, pt_b = self._split_seg
            glDisable(GL_DEPTH_TEST)
            glLineWidth(2.5)
            glColor3f(0.1, 0.45, 1.0)
            glBegin(GL_LINES)
            glVertex3f(*pt_a)
            glVertex3f(*pt_b)
            glEnd()
            glLineWidth(1.0)
            glEnable(GL_DEPTH_TEST)
