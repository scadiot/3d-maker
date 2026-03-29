"""AppSelectionMixin: ray picking and selection application."""

from editor.core.group import all_polygons


class AppSelectionMixin:

    # ── Low-level picking ─────────────────────────────────────────────────────
    def _pick_polygon(self, mx, my):
        ro, rd = self.camera.pick_ray(mx, my)
        return self.scene.pick_polygon(ro, rd)

    def _pick_edge(self, mx, my):
        ro, rd = self.camera.pick_ray(mx, my)
        return self.scene.pick_edge(ro, rd)

    def _pick_vertex(self, mx, my):
        ro, rd = self.camera.pick_ray(mx, my)
        return self.scene.pick_vertex(ro, rd)

    def _pick_locked_group(self, mx, my):
        ro, rd = self.camera.pick_ray(mx, my)
        return self.scene.pick_locked_group(ro, rd)

    # ── Selection application ─────────────────────────────────────────────────
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

    # ── Mouse-down dispatch (3D viewport) ────────────────────────────────────
    def _handle_mouse_down_3d(self, mx, my):
        if self.state.polygon_splitting_mode:
            self.split_tool.on_mouse_down(mx, my)
            return

        ctrl_held = 'shift_l' in self.keys_pressed  # Shift for multi-select
        multi     = len(self.scene.selected_indices) > 1 or bool(self.state.selected_groups)
        sel_mode  = self.state.selection_mode
        gizmo_on  = self.state.gizmo_enable

        if sel_mode == 'edge' and self.state.selected_edges:
            if gizmo_on:
                if self.gizmo.mode == 'rotate':
                    axis = self.gizmo.pick_rotate_axis(mx, my, self.state, self.camera)
                elif self.gizmo.mode == 'scale':
                    axis = self.gizmo.pick_scale_handle(mx, my, self.state, self.camera)
                elif self.gizmo.mode == 'universal':
                    axis = self.gizmo.pick_universal_axis(mx, my, self.state, self.camera)
                else:
                    axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera)
            else:
                axis = None
            if axis:
                self.gizmo.start_drag(axis, mx, my, self.state, self.camera)
            else:
                self._apply_edge_selection(self._pick_edge(mx, my), ctrl_held)
            return

        if sel_mode == 'vertex' and self.state.selected_vertices:
            if gizmo_on:
                if self.gizmo.mode == 'rotate':
                    axis = self.gizmo.pick_rotate_axis(mx, my, self.state, self.camera)
                elif self.gizmo.mode == 'scale':
                    axis = self.gizmo.pick_scale_handle(mx, my, self.state, self.camera)
                elif self.gizmo.mode == 'universal':
                    axis = self.gizmo.pick_universal_axis(mx, my, self.state, self.camera)
                else:
                    axis = self.gizmo.pick_translate_axis(mx, my, self.state, self.camera)
            else:
                axis = None
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

        elif self.gizmo.mode == 'universal':
            axis = self.gizmo.pick_universal_axis(mx, my, self.state, self.camera) if gizmo_on else None
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
