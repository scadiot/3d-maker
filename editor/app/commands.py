"""AppCommandsMixin: edit commands (add, delete, duplicate, group, UV…)."""

from editor.core.group import Group, all_polygons
from editor.core.history import (AddPolygonsCommand, DeletePolygonsCommand,
                             PolyDataCommand, GroupCommand, UngroupCommand,
                             AddGroupCommand, DeleteGroupCommand, CompoundCommand)
from editor.utils.math3d import normalize, cross, vsub, dot


class AppCommandsMixin:

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

    def _cmd_create_from_edges(self) -> None:
        before_ids = {id(p) for p in all_polygons(self.scene.root)}
        self.scene.create_polygon_from_edges(self.state.current_group)
        self._record_added_polygons(before_ids)

    def _cmd_project_info(self):
        from editor.ui.project_info_dialog import ProjectInfoDialog
        dlg = ProjectInfoDialog(self.root, self.state)
        if dlg._confirmed:
            self._update_title()

    def _cmd_textures_atlas(self):
        from editor.ui.texture_atlas_dialog import TextureAtlasDialog
        TextureAtlasDialog(self.root, self.state)
