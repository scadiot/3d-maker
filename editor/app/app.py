"""App class: Tkinter/pyopengltk initialization, main loop, event handling."""

import time
import tkinter as tk
from tkinter import messagebox

from pyopengltk import OpenGLFrame
from OpenGL.GL import (
    glEnable, glClearColor, glClear, glViewport,
    glMatrixMode, glLoadIdentity, glRotatef, glTranslatef,
    GL_DEPTH_TEST, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_PROJECTION, GL_MODELVIEW,
)
from OpenGL.GL import glOrtho
from OpenGL.GLU import gluPerspective

from editor.utils.constants import (PANEL_WIDTH, FOV, NEAR, FAR)
from editor.render.camera        import Camera
from editor.core.scene         import Scene
from editor.render.gizmo         import Gizmo
from editor.render.view_cube     import ViewCube
from editor.render.renderer      import draw_grid
from editor.core.state_manager import StateManager
from editor.core.history       import HistoryManager

from editor.app.toolbar   import AppToolbarMixin
from editor.app.layout    import AppLayoutMixin
from editor.app.events    import AppEventsMixin
from editor.app.selection import AppSelectionMixin
from editor.app.commands  import AppCommandsMixin
from editor.app.file      import AppFileMixin
from editor.tools.split_tool    import SplitTool
from editor.tools.extrude_tool  import ExtrudeTool
from editor.tools.add_quad_tool import AddQuadTool
from editor.tools.circle_tool   import CircleTool


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


class App(AppToolbarMixin, AppLayoutMixin, AppEventsMixin,
          AppSelectionMixin, AppCommandsMixin, AppFileMixin):

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
        self._btn_move_gizmo   = None
        self._btn_ortho        = None
        self.history           = HistoryManager()
        self.keys_pressed      = set()
        self.mouse_btn1        = False
        self.mouse_x           = 0
        self.mouse_y           = 0
        self.last_time         = time.time()
        self._viewport_focused = False
        # ── Tools ─────────────────────────────────────────────────────────────
        self.tools = [SplitTool(self), ExtrudeTool(self), AddQuadTool(self), CircleTool(self)]

    @property
    def active_tool(self):
        """Returns the currently active tool, or None if no tool is active."""
        name = self.state.active_tool_name
        return next((t for t in self.tools if t.name == name), None)

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

    # ── Update loop ───────────────────────────────────────────────────────────
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

        if self.state.tool_active:
            t = self.active_tool
            if t:
                t.update(self.mouse_x, self.mouse_y)

        if self.state.gizmo_enable and self.gizmo.dragging_axis and self.mouse_btn1:
            self.gizmo.update_drag(self.mouse_x, self.mouse_y, self.state, self.camera)

        if self.state.gizmo_enable:
            self.gizmo.update_hover(self.mouse_x, self.mouse_y, self.state, self.camera)

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
        if self.camera.ortho:
            h = self.camera.ortho_half_h()
            w = h * (vw / vh)
            glOrtho(-w, w, -h, h, NEAR, FAR)
        else:
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

        # ── Tool overlays ──────────────────────────────────────────────────
        if self.state.tool_active:
            t = self.active_tool
            if t:
                t.draw()
