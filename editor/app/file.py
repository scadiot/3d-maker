"""AppFileMixin: new project, save, load, and import."""

from tkinter import filedialog, messagebox


class AppFileMixin:

    def _new_project(self):
        if self.state.modified:
            if not messagebox.askyesno(
                "New project",
                "The current project has unsaved changes.\n"
                "Do you want to continue and lose the changes?",
                icon='warning',
            ):
                return
        self.scene.root.children.clear()
        self.scene.root.polygons.clear()
        self.scene.root.hidden = False
        self.state._current_group = self.scene.root
        self.state._selected_polygons = []
        self.state._selected_edges = []
        self.state._selected_vertices = []
        self.state._project_path = ""
        self.state._project_name = ""
        self.state._modified = False
        self.camera.pos   = [0.0, 3.0, 8.0]
        self.camera.yaw   = 0.0
        self.camera.pitch = -20.0
        self.history.clear()
        self.gizmo.stop_drag()
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
