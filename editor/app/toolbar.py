"""AppToolbarMixin: menu bar, toolbars, and toolbar sync helpers."""

import math
import tkinter as tk
from PIL import Image, ImageDraw, ImageTk

from editor.utils.constants import FOV, SNAP_VALUES


class AppToolbarMixin:

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
        m_poly.add_command(label="Rotate Vertices", accelerator="T",
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
            d.polygon([3, 3,  s-3-fold, 3,  s-3, 3+fold,  s-3, s-3,  3, s-3],
                      outline=c, fill='#16161f')
            d.line([s-3-fold, 3, s-3, 3+fold], fill=c, width=1)
            cx, cy = s//2, s//2 + 2
            d.line([cx-3, cy, cx+3, cy], fill=c, width=2)
            d.line([cx, cy-3, cx, cy+3], fill=c, width=2)

        def ico_save(d, s, c):
            d.rectangle([3, 4, s-3, s-3], outline=c, width=1)
            d.rectangle([5, 3, s-7, 8],   fill=c)
            d.rectangle([s-8, 3, s-5, 7], fill='#16161f')
            d.rectangle([6, 13, s-6, s-4], outline=c, width=1)

        def ico_save_current(d, s, c):
            d.rectangle([3, 4, s-3, s-3], outline=c, width=1)
            d.rectangle([5, 3, s-7, 8],   fill=c)
            d.rectangle([s-8, 3, s-5, 7], fill='#16161f')
            d.rectangle([6, 13, s-6, s-4], outline=c, width=1)
            cx = s // 2
            d.line([cx, 14, cx, s-6], fill='#16161f', width=2)
            d.polygon([cx-3, s-9, cx+3, s-9, cx, s-5], fill='#16161f')

        def ico_load(d, s, c):
            d.rectangle([3, 7, s-3, s-3], outline=c, width=1)
            d.polygon([3, 7, 3, 4, 9, 4, 11, 7], outline=c, fill='#16161f')
            d.line([3, 7, 11, 7], fill=c, width=1)

        def ico_import(d, s, c):
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
            d.rectangle([s-5, 3, s-6+1, s-6+1], fill='#16161f')

        def ico_delete(d, s, c):
            d.rectangle([4, 7, s-4, s-3], outline=c, width=1)
            d.line([4, 7, s-4, 7], fill=c, width=1)
            d.rectangle([7, 4, s-7, 7], outline=c, width=1)
            d.line([8, 11, 8, s-5],  fill=c, width=1)
            d.line([s-8, 11, s-8, s-5], fill=c, width=1)

        def ico_group(d, s, c):
            d.line([4, 4, 4, s-4],   fill=c, width=2)
            d.line([4, 4, 7, 4],     fill=c, width=2)
            d.line([4, s-4, 7, s-4], fill=c, width=2)
            d.line([s-4, 4, s-4, s-4],   fill=c, width=2)
            d.line([s-7, 4, s-4, 4],     fill=c, width=2)
            d.line([s-7, s-4, s-4, s-4], fill=c, width=2)
            d.line([7, s//2, s-7, s//2], fill=c, width=1)

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
            d.ellipse([2, cy-r, 2+2*r, cy+r], fill=c)
            d.ellipse([s-2-2*r, cy-r, s-2, cy+r], fill=c)
            d.rectangle([cx-4, cy-2, cx-1, cy+2], outline=c, width=1)
            d.rectangle([cx+1, cy-2, cx+4, cy+2], outline=c, width=1)

        def ico_scale(d, s, c):
            d.line([3, s-3, s-3, 3], fill=c, width=1)
            d.polygon([3, s-3, 3, s-8, 8, s-3], fill=c)
            d.polygon([s-3, 3, s-3, 8, s-8, 3], fill=c)

        def ico_universal(d, s, c):
            cx, cy, a = s//2, s//2, 5
            for dx, dy in [(0, -1), (1, 0)]:
                ex, ey = cx + dx*a, cy + dy*a
                d.line([cx, cy, ex, ey], fill=c, width=1)
                nx, ny = -dy, dx
                d.polygon([ex, ey,
                            ex - dx*3 + nx*2, ey - dy*3 + ny*2,
                            ex - dx*3 - nx*2, ey - dy*3 - ny*2], fill=c)
            r = s//2 - 2
            d.arc([cx-r, cy-r, cx+r, cy+r], start=0, end=360, fill=c, width=1)
            bs = 2
            bx, by = cx - a + 1, cy + a - 1
            d.rectangle([bx-bs, by-bs, bx+bs, by+bs], outline=c, width=1)

        def ico_move_gizmo(d, s, c):
            cx, cy = s // 2, s // 2
            r = 3
            d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=c, width=1)
            a = 5
            for dx, dy in [(0, -1), (0, 1), (-1, 0), (1, 0)]:
                bx, by = cx + dx * (r + 2), cy + dy * (r + 2)
                ex, ey = cx + dx * (r + 2 + a), cy + dy * (r + 2 + a)
                d.line([bx, by, ex, ey], fill=c, width=1)
                nx, ny = -dy, dx
                d.polygon([ex + dx * 3, ey + dy * 3,
                           ex - dx * 2 + nx * 2, ey - dy * 2 + ny * 2,
                           ex - dx * 2 - nx * 2, ey - dy * 2 - ny * 2], fill=c)

        def ico_sel_polygon(d, s, c):
            d.rectangle([4, 4, s-4, s-4], fill='#404060', outline=c, width=2)

        def ico_sel_edge(d, s, c):
            pts = [s//2, 3, s-3, s-3, 3, s-3]
            d.polygon(pts, outline='#505065')
            d.line([s//2, 3, s-3, s-3], fill=c, width=3)

        def ico_sel_vertex(d, s, c):
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

        # Gizmo buttons (radio-style)
        def set_gizmo(mode):
            self.gizmo.move_gizmo_mode = False
            self.gizmo.mode = mode
            self._sync_gizmo_btns()

        for mode, ifn, lbl in [('universal', ico_universal, "Universal"),
                                ('scale',     ico_scale,     "Scale")]:
            b = add_btn(make_icon(ifn), lambda m=mode: set_gizmo(m), lbl, "Space")
            self._gizmo_btns[mode] = (b, BG, BG_ON)

        self._sync_gizmo_btns()
        add_sep()

        self._btn_move_gizmo = add_btn(make_icon(ico_move_gizmo),
                                       self._toggle_move_gizmo_mode,
                                       "Move Gizmo")
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
        add_sep()

        def ico_ortho(d, s, c):
            m = s // 2
            for y in [m - 4, m + 4]:
                d.line([3, y, s - 3, y], fill=c, width=2)
            for x in [3, s - 3]:
                d.line([x, m - 6, x, m + 6], fill=c, width=1)

        self._btn_ortho = add_btn(make_icon(ico_ortho), self._toggle_ortho,
                                  "Orthographic view")

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

        add_btn(self._cmd_flip_orientation,
                "Flip orientation", "N")
        add_btn(self._cmd_rotate_vertices,
                "Rotate Vertices", "T")
        self._sep_edges = tk.Frame(self.toolbar2, width=1, bg='#38384a')
        self._sep_edges.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
        self._btn_create_from_edges = add_btn(self._cmd_create_from_edges,
                                              "Create polygon from edges")

        self._tool_btn_widgets = []  # list of (sep, btn, spec)
        for tool in self.tools:
            for spec in tool.toolbar_button_specs:
                sep = tk.Frame(self.toolbar2, width=1, bg='#38384a')
                btn = add_btn(spec["command"], spec["label"])
                self._tool_btn_widgets.append((sep, btn, spec))

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

    def _exit_ortho(self):
        """Exit orthographic mode and update the toolbar button."""
        if self.camera.ortho:
            self.camera.ortho = False
            self._btn_ortho.config(bg='#16161f')

    def _toggle_ortho(self):
        self.camera.ortho = not self.camera.ortho
        if self.camera.ortho:
            import math as _math
            dist = _math.sqrt(sum(p**2 for p in self.camera.pos))
            self.camera.ortho_scale = max(dist * _math.tan(_math.radians(FOV / 2)), 0.1)
            self._snap_camera_to_nearest_axis()
        self._btn_ortho.config(bg='#2d4080' if self.camera.ortho else '#16161f')

    def _snap_camera_to_nearest_axis(self):
        """Snap camera to the nearest canonical axis view (like clicking the view cube)."""
        import math as _math
        px, py, pz = self.camera.pos
        mag = _math.sqrt(px*px + py*py + pz*pz)
        if mag < 1e-6:
            return
        pos_dir = (px / mag, py / mag, pz / mag)
        face_normals = {
            'Right':  ( 1,  0,  0),
            'Left':   (-1,  0,  0),
            'Top':    ( 0,  1,  0),
            'Bottom': ( 0, -1,  0),
            'Front':  ( 0,  0, -1),
            'Back':   ( 0,  0,  1),
        }
        best_face = max(face_normals, key=lambda f: sum(pos_dir[i] * face_normals[f][i] for i in range(3)))
        self.view_cube.snap_to_face(best_face, self.camera)

    def _toggle_move_gizmo_mode(self):
        if self.gizmo.move_gizmo_mode:
            self.gizmo.move_gizmo_mode = False
        else:
            self.gizmo.position_override = self.gizmo.get_position(self.state)
            self.gizmo.move_gizmo_mode  = True
            self.gizmo.mode             = 'universal'
        self._sync_gizmo_btns()

    def _on_selection_changed(self):
        if self.state.tool_active and self.state.active_tool_name == 'extrude' and not self.state.selected_edges:
            t = self.active_tool
            if t:
                t.confirm()
            return
        self.gizmo.position_override = None
        self.gizmo.move_gizmo_mode   = False
        self._sync_gizmo_btns()
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

        for sep, btn, spec in self._tool_btn_widgets:
            if spec["visible"]():
                sep.pack(side=tk.LEFT, fill=tk.Y, padx=5, pady=5)
                btn.pack(side=tk.LEFT, padx=1, pady=2)
                enabled_fn = spec.get("enabled", lambda: True)
                if enabled_fn():
                    btn.config(state='normal', cursor='hand2', bg='#16161f')
                else:
                    btn.config(state='disabled', cursor='', bg=self._BG_DIS)
            else:
                sep.pack_forget()
                btn.pack_forget()

        if hasattr(self, 'tool_panel'):
            self._refresh_tool_panel()

    def _refresh_group_panel(self):
        if hasattr(self, 'group_panel'):
            self.group_panel.refresh()

    def _sync_gizmo_btns(self):
        BG    = '#16161f'
        BG_ON = '#2d4080'
        extruding  = self.state.tool_active and self.state.active_tool_name == 'extrude'
        move_gizmo = self.gizmo.move_gizmo_mode
        for mode, (btn, bg_off, bg_on) in self._gizmo_btns.items():
            if extruding or (move_gizmo and mode in ('scale',)):
                btn.config(state='disabled', bg=self._BG_DIS, cursor='')
            else:
                btn.config(state='normal', cursor='hand2',
                           bg=bg_on if self.gizmo.mode == mode else bg_off)
        if self._btn_move_gizmo is not None:
            if extruding:
                self._btn_move_gizmo.config(state='disabled', bg=self._BG_DIS, cursor='')
            else:
                self._btn_move_gizmo.config(state='normal', cursor='hand2',
                                            bg=BG_ON if self.gizmo.move_gizmo_mode else BG)

    def _sync_sel_mode_btns(self):
        for mode, (btn, bg_off, bg_on) in self._sel_btns.items():
            btn.config(bg=bg_on if self.state.selection_mode == mode else bg_off)
