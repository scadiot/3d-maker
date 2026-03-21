"""Action history — Command Pattern for undo/redo."""
from __future__ import annotations

from abc import ABC, abstractmethod


# ── Base interface ─────────────────────────────────────────────────────────────

class Command(ABC):
    @abstractmethod
    def execute(self) -> None: ...

    @abstractmethod
    def undo(self) -> None: ...

    def redo(self) -> None:
        self.execute()


class CompoundCommand(Command):
    """Groups multiple commands into a single history entry."""

    def __init__(self, cmds: list) -> None:
        self._cmds = list(cmds)

    def execute(self) -> None:
        for cmd in self._cmds:
            cmd.execute()

    def undo(self) -> None:
        for cmd in reversed(self._cmds):
            cmd.undo()


class HistoryManager:
    def __init__(self, max_size: int = 100) -> None:
        self._undo: list[Command] = []
        self._redo: list[Command] = []
        self._max = max_size

    def clear(self) -> None:
        """Clears the undo/redo history."""
        self._undo.clear()
        self._redo.clear()

    def push(self, cmd: Command) -> None:
        """Executes cmd and records it in the history."""
        cmd.execute()
        self._append(cmd)

    def record(self, cmd: Command) -> None:
        """Records an already-executed command (e.g. gizmo drag)."""
        self._append(cmd)

    def _append(self, cmd: Command) -> None:
        self._undo.append(cmd)
        if len(self._undo) > self._max:
            self._undo.pop(0)
        self._redo.clear()

    def undo(self) -> bool:
        if not self._undo:
            return False
        cmd = self._undo.pop()
        cmd.undo()
        self._redo.append(cmd)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        cmd = self._redo.pop()
        cmd.redo()
        self._undo.append(cmd)
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)


# ── Gizmo commands ─────────────────────────────────────────────────────────────

class TransformCommand(Command):
    """Translate / rotate / scale of polygons via the gizmo."""

    def __init__(self, state, before: dict, after: dict) -> None:
        self._state  = state
        self._before = before   # {Polygon: list[vertex]}
        self._after  = after

    def execute(self) -> None:
        for p, vs in self._after.items():
            p.vertices = list(vs)
        self._state.notify_polygon_transformed(list(self._after))

    def undo(self) -> None:
        for p, vs in self._before.items():
            p.vertices = list(vs)
        self._state.notify_polygon_transformed(list(self._before))


# ── Polygon commands ───────────────────────────────────────────────────────────

class AddPolygonsCommand(Command):
    """Addition of one or more polygons (add, duplicate, create_from_edges…)."""

    def __init__(self, state, polys: list) -> None:
        self._state  = state
        self._polys  = list(polys)
        self._groups = {p: p.group for p in polys}

    def execute(self) -> None:
        for p in self._polys:
            g = self._groups[p]
            if p not in g.polygons:
                g.adopt_polygon(p)
        self._state.set_selection(polygons=self._polys)
        self._state._emit("scene_changed", change_type="polygon_added")

    def undo(self) -> None:
        self._state.delete_polygons(self._polys)


class DeletePolygonsCommand(Command):
    """Deletion of polygons."""

    def __init__(self, state, saved: list) -> None:
        # saved: [(Polygon, Group, int)] — polygon, parent group, index in group.polygons
        self._state = state
        self._saved = list(saved)

    def execute(self) -> None:
        self._state.delete_polygons([p for p, _, _ in self._saved])

    def undo(self) -> None:
        for poly, group, idx in self._saved:
            group.polygons.insert(min(idx, len(group.polygons)), poly)
            poly.group = group
        polys = [p for p, _, _ in self._saved]
        self._state._emit("scene_changed", change_type="polygon_added")
        self._state.set_selection(polygons=polys)


class PolyDataCommand(Command):
    """Mutation of vertices/UVs (rotate_uvs, flip_orientation, align_edges…)."""

    def __init__(self, state, before: dict, after: dict) -> None:
        # before/after: {Polygon: (list[vertex], list[uv])}
        self._state  = state
        self._before = before
        self._after  = after

    def execute(self) -> None:
        for p, (vs, uvs) in self._after.items():
            p.vertices = list(vs)
            p.uvs      = list(uvs)
        self._state._emit("scene_changed", change_type="polygon_transformed")

    def undo(self) -> None:
        for p, (vs, uvs) in self._before.items():
            p.vertices = list(vs)
            p.uvs      = list(uvs)
        self._state._emit("scene_changed", change_type="polygon_transformed")


# ── Group commands ─────────────────────────────────────────────────────────────

class GroupCommand(Command):
    """Grouping of polygons into a new sub-group."""

    def __init__(self, state, polys: list, old_groups: dict, new_group, parent) -> None:
        # old_groups: {Polygon: (Group, int)} — original group and index
        self._state      = state
        self._polys      = list(polys)
        self._old_groups = old_groups
        self._new_group  = new_group
        self._parent     = parent

    def execute(self) -> None:
        if self._new_group not in self._parent.children:
            self._parent.children.append(self._new_group)
            self._new_group.parent = self._parent
        for p in self._polys:
            self._new_group.adopt_polygon(p)
        self._state._emit("scene_changed", change_type="group_added",
                          group=self._new_group, parent=self._parent)

    def undo(self) -> None:
        for p, (old_g, idx) in self._old_groups.items():
            if p in self._new_group.polygons:
                self._new_group.polygons.remove(p)
            old_g.polygons.insert(min(idx, len(old_g.polygons)), p)
            p.group = old_g
        if (not self._new_group.polygons and not self._new_group.children
                and self._new_group in self._parent.children):
            self._parent.remove_group(self._new_group)
        self._state._emit("scene_changed", change_type="group_deleted",
                          group=self._new_group)


class UngroupCommand(Command):
    """Ungrouping of polygons."""

    def __init__(self, state, groups_info: list) -> None:
        # groups_info: [(Group, parent_Group, [(Polygon, int)])]
        self._state       = state
        self._groups_info = groups_info

    def execute(self) -> None:
        for group, parent, polys_idx in self._groups_info:
            for poly, _ in polys_idx:
                parent.adopt_polygon(poly)
            for child in list(group.children):
                parent.adopt_group(child)
            if group in parent.children:
                parent.remove_group(group)
        self._state._emit("scene_changed", change_type="group_deleted")

    def undo(self) -> None:
        for group, parent, polys_idx in self._groups_info:
            if group not in parent.children:
                parent.children.append(group)
                group.parent = parent
            for poly, idx in polys_idx:
                if poly.group is not None and poly.group is not group:
                    poly.group.polygons.remove(poly)
                poly.group = group
                group.polygons.insert(min(idx, len(group.polygons)), poly)
        self._state._emit("scene_changed", change_type="group_added")


class AddGroupCommand(Command):
    """Creation of a new group."""

    def __init__(self, state, group, parent) -> None:
        self._state  = state
        self._group  = group
        self._parent = parent

    def execute(self) -> None:
        if self._group not in self._parent.children:
            self._parent.children.append(self._group)
            self._group.parent = self._parent
        self._state._emit("scene_changed", change_type="group_added",
                          group=self._group, parent=self._parent)

    def undo(self) -> None:
        self._state.delete_group(self._group)


class DeleteGroupCommand(Command):
    """Deletion of a group and all its contents."""

    def __init__(self, state, group) -> None:
        self._state      = state
        self._group      = group
        self._parent     = group.parent
        self._parent_idx = (group.parent.children.index(group)
                            if group.parent else 0)
        from editor.group import all_polygons
        self._all_polys = all_polygons(group)

    def execute(self) -> None:
        self._state.delete_group(self._group)

    def undo(self) -> None:
        if self._parent is not None:
            self._group.parent = self._parent
            self._parent.children.insert(
                min(self._parent_idx, len(self._parent.children)),
                self._group,
            )
        for poly in self._all_polys:
            if poly.group is not None and poly not in poly.group.polygons:
                poly.group.polygons.append(poly)
        self._state._emit("scene_changed", change_type="group_added",
                          group=self._group, parent=self._parent)
        self._state.set_selection(polygons=self._all_polys)


class RenameGroupCommand(Command):
    """Renaming of a group."""

    def __init__(self, state, group, old_name: str, new_name: str) -> None:
        self._state = state
        self._group = group
        self._old   = old_name
        self._new   = new_name

    def execute(self) -> None:
        self._group.name = self._new
        self._state._emit("scene_changed", change_type="group_renamed",
                          group=self._group, old_name=self._old)

    def undo(self) -> None:
        self._group.name = self._old
        self._state._emit("scene_changed", change_type="group_renamed",
                          group=self._group, old_name=self._new)


class MovePolygonCommand(Command):
    """Moving a polygon to another group (drag & drop)."""

    def __init__(self, state, poly, old_group, new_group) -> None:
        self._state     = state
        self._poly      = poly
        self._old_group = old_group
        self._new_group = new_group

    def execute(self) -> None:
        self._state.move_polygon(self._poly, self._new_group)

    def undo(self) -> None:
        self._state.move_polygon(self._poly, self._old_group)


class MoveGroupCommand(Command):
    """Moving a group in the hierarchy (drag & drop)."""

    def __init__(self, state, group, old_parent, new_parent) -> None:
        self._state      = state
        self._group      = group
        self._old_parent = old_parent
        self._new_parent = new_parent

    def execute(self) -> None:
        self._state.move_group(self._group, self._new_parent)

    def undo(self) -> None:
        self._state.move_group(self._group, self._old_parent)


class SplitPolygonCommand(Command):
    """Split a polygon into two parts."""

    def __init__(self, state, quad, tri1, tri2) -> None:
        self._state = state
        self._quad  = quad
        self._group = quad.group
        self._idx   = quad.group.polygons.index(quad)
        self._tri1  = tri1
        self._tri2  = tri2

    def execute(self) -> None:
        if self._quad in self._group.polygons:
            self._group.polygons.remove(self._quad)
            self._quad.group = None
        self._group.adopt_polygon(self._tri1)
        self._group.adopt_polygon(self._tri2)
        self._state.set_selection(polygons=[self._tri1, self._tri2])
        self._state._emit("scene_changed", change_type="polygon_added")

    def undo(self) -> None:
        if self._tri1 in self._group.polygons:
            self._group.polygons.remove(self._tri1)
            self._tri1.group = None
        if self._tri2 in self._group.polygons:
            self._group.polygons.remove(self._tri2)
            self._tri2.group = None
        if self._quad not in self._group.polygons:
            self._group.polygons.insert(
                min(self._idx, len(self._group.polygons)), self._quad)
            self._quad.group = self._group
        self._state.set_selection(polygons=[self._quad])
        self._state._emit("scene_changed", change_type="polygon_added")
