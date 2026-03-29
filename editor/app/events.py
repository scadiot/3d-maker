"""AppEventsMixin: mouse, keyboard, and focus event handling."""

import ctypes

from editor.utils.constants import SNAP_VALUES


class AppEventsMixin:

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
        self.split_tool.on_mouse_up(event.x, event.y)
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
        self._sync_sel_mode_btns()
        self._sync_gizmo_btns()

    def _handle_keyboard(self, key):
        if key == 'delete' and (self.scene.selected_indices or self.state.selected_groups):
            self._cmd_delete()

        if key == 'c':
            self._cmd_duplicate()

        if key == 'space' and (self.scene.selected_indices or self.state.selected_groups or self.state.selected_edges or self.state.selected_vertices) and not self.state.extrusion_mode and not self.gizmo.move_gizmo_mode:
            self.gizmo.cycle_mode()
            self._sync_gizmo_btns()

        if key == 'g' and len(self.scene.selected_indices) >= 2:
            self._cmd_group()

        if key == 'h' and self.scene.selected_indices:
            self._cmd_ungroup()

        if key == 't' and self.scene.selected_indices and not self.camera.ortho:
            self._cmd_rotate_vertices()

        if key == 'n' and self.scene.selected_indices:
            self._cmd_flip_orientation()

        if key == 'v':
            self._toggle_vertex_glue()

        if key == 'k':
            one_poly = (self.state.selection_mode == 'polygon'
                        and len(self.state.selected_polygons) == 1)
            if one_poly and self._poly_is_coplanar(self.state.selected_polygons[0]):
                self.split_tool.activate()

        if key == 'return':
            if self.state.polygon_splitting_mode:
                self.split_tool.confirm()
            elif self.state.extrusion_mode:
                self.extrude_tool.confirm()

        if key == 'escape':
            if self.state.polygon_splitting_mode:
                self.split_tool.cancel()
            elif self.state.extrusion_mode:
                self.extrude_tool.cancel()
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
