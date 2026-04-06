"""StateManager — Single source of truth for scene state."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Literal

from editor.core.group import Group, Polygon, all_polygons
from editor.utils.texture_atlas import TextureAtlas


SelectionMode = Literal["polygon", "edge", "vertex"]
EventName = Literal[
    "scene_changed",
    "selection_changed",
    "current_group_changed",
    "polygon_transformed",
    "textures_changed",
]


class StateManager:
    """Single source of truth for scene state.

    Centralizes all significant data (hierarchy, selection, current group)
    and notifies subscribers via an observer system.
    Contains neither rendering logic nor UI logic.
    """

    # ------------------------------------------------------------------ #
    # Construction                                                         #
    # ------------------------------------------------------------------ #

    def __init__(self, root_group: Group) -> None:
        self._root_group: Group = root_group
        self._current_group: Group = root_group
        self._selection_mode: SelectionMode = "polygon"
        self._selected_polygons: list[Polygon] = []
        self._selected_edges: list[tuple[Polygon, int]] = []
        self._selected_vertices: list[tuple[Polygon, int]] = []
        self._selected_groups: list[Group] = []
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._emitting: bool = False  # guard against notification loops
        self._modified: bool = False  # True as soon as an unsaved change exists
        self._project_name: str = ""   # project name (without extension)
        self._project_path: str = ""   # absolute path to the project JSON file
        self._vertex_glue: bool = False
        self._tool_active: bool = False
        self._active_tool_name: str = ""
        self._textures_atlases: list[TextureAtlas] = []
        self._selection_enable: bool = True
        self._gizmo_enable: bool = True

    # ------------------------------------------------------------------ #
    # Accessors (read)                                                     #
    # ------------------------------------------------------------------ #

    @property
    def root_group(self) -> Group:
        return self._root_group

    @property
    def current_group(self) -> Group:
        return self._current_group

    @property
    def selection_mode(self) -> SelectionMode:
        return self._selection_mode

    @property
    def selected_polygons(self) -> list[Polygon]:
        return list(self._selected_polygons)

    @property
    def selected_edges(self) -> list[tuple[Polygon, int]]:
        return list(self._selected_edges)

    @property
    def selected_vertices(self) -> list[tuple[Polygon, int]]:
        return list(self._selected_vertices)

    @property
    def selected_groups(self) -> list[Group]:
        return list(self._selected_groups)

    @selected_groups.setter
    def selected_groups(self, value: list[Group]) -> None:
        new = list(value)
        if new == self._selected_groups:
            return
        self._selected_groups = new
        self._emit(
            "selection_changed",
            polygons=self.selected_polygons,
            edges=self.selected_edges,
            vertices=self.selected_vertices,
            mode=self._selection_mode,
        )

    @property
    def textures_atlases(self) -> list[TextureAtlas]:
        return self._textures_atlases

    @textures_atlases.setter
    def textures_atlases(self, value: list[TextureAtlas]) -> None:
        self._textures_atlases = value

    def change_textures(self, atlases: list[TextureAtlas]) -> None:
        """Replaces the texture atlas list and notifies subscribers."""
        self._textures_atlases = atlases
        self._modified = True
        self._emit("textures_changed", atlases=atlases)

    @property
    def vertex_glue(self) -> bool:
        """When True, vertices at the same position as moved vertices move together."""
        return self._vertex_glue

    @vertex_glue.setter
    def vertex_glue(self, value: bool) -> None:
        self._vertex_glue = value

    @property
    def tool_active(self) -> bool:
        """When True, a tool is currently active."""
        return self._tool_active

    @tool_active.setter
    def tool_active(self, value: bool) -> None:
        self._tool_active = value

    @property
    def active_tool_name(self) -> str:
        """Name of the currently active tool, or empty string if none."""
        return self._active_tool_name

    @active_tool_name.setter
    def active_tool_name(self, value: str) -> None:
        self._active_tool_name = value

    @property
    def selection_enable(self) -> bool:
        """When True, selection interactions are enabled."""
        return self._selection_enable

    @selection_enable.setter
    def selection_enable(self, value: bool) -> None:
        self._selection_enable = value

    @property
    def gizmo_enable(self) -> bool:
        """When True, the gizmo is enabled."""
        return self._gizmo_enable

    @gizmo_enable.setter
    def gizmo_enable(self, value: bool) -> None:
        self._gizmo_enable = value

    @property
    def modified(self) -> bool:
        """True if the scene has been modified since the last save."""
        return self._modified

    def mark_saved(self) -> None:
        """Marks the scene as saved (resets the modification flag)."""
        self._modified = False

    @property
    def project_name(self) -> str:
        """Project name (without extension)."""
        return self._project_name

    @project_name.setter
    def project_name(self, value: str) -> None:
        self._project_name = value

    @property
    def project_path(self) -> str:
        """Absolute path to the project JSON file."""
        return self._project_path

    @project_path.setter
    def project_path(self, value: str) -> None:
        self._project_path = value

    # ------------------------------------------------------------------ #
    # Scene mutators                                                       #
    # ------------------------------------------------------------------ #

    def add_polygon(self, polygon: Polygon, group: Group | None = None) -> None:
        """Adds a polygon to the given group (or current_group by default)."""
        target = group if group is not None else self._current_group
        target.adopt_polygon(polygon)
        self._modified = True
        self._emit("scene_changed", change_type="polygon_added", polygon=polygon, group=target)

    def delete_polygons(self, polygons: list[Polygon]) -> None:
        """Removes polygons from the scene and updates the selection."""
        to_delete = set(polygons)
        for polygon in polygons:
            if polygon.group is not None:
                polygon.group.remove_polygon(polygon)
        # Clean up selection
        self._selected_polygons = [p for p in self._selected_polygons if p not in to_delete]
        self._selected_edges = [(p, i) for p, i in self._selected_edges if p not in to_delete]
        self._selected_vertices = [(p, i) for p, i in self._selected_vertices if p not in to_delete]
        self._modified = True
        self._emit("scene_changed", change_type="polygons_deleted", polygons=list(polygons))
        self._emit("selection_changed",
                   polygons=self.selected_polygons,
                   edges=self.selected_edges,
                   vertices=self.selected_vertices,
                   mode=self._selection_mode)

    def move_polygon(self, polygon: Polygon, new_group: Group) -> None:
        """Moves a polygon to another group."""
        new_group.adopt_polygon(polygon)
        self._modified = True
        self._emit("scene_changed", change_type="polygon_moved", polygon=polygon, new_group=new_group)

    def add_group(self, name: str, parent: Group | None = None) -> Group:
        """Creates a new child group."""
        target_parent = parent if parent is not None else self._current_group
        new_group = target_parent.add_group(name)
        self._modified = True
        self._emit("scene_changed", change_type="group_added", group=new_group, parent=target_parent)
        return new_group

    def delete_group(self, group: Group) -> None:
        """Deletes a group and all its children (and updates the selection)."""
        deleted_polys = set(all_polygons(group))
        if group.parent is not None:
            group.parent.remove_group(group)
        # If the current group was in the deleted tree, return to root
        if self._is_descendant_or_equal(self._current_group, group):
            self._current_group = self._root_group
        # Clean up selection
        if deleted_polys:
            self._selected_polygons = [p for p in self._selected_polygons if p not in deleted_polys]
            self._selected_edges = [(p, i) for p, i in self._selected_edges if p not in deleted_polys]
            self._selected_vertices = [(p, i) for p, i in self._selected_vertices if p not in deleted_polys]
        self._modified = True
        self._emit("scene_changed", change_type="group_deleted", group=group)
        if deleted_polys:
            self._emit("selection_changed",
                       polygons=self.selected_polygons,
                       edges=self.selected_edges,
                       vertices=self.selected_vertices,
                       mode=self._selection_mode)

    def rename_group(self, group: Group, name: str) -> None:
        """Renames a group."""
        old_name = group.name
        group.name = name
        self._modified = True
        self._emit("scene_changed", change_type="group_renamed", group=group, old_name=old_name)

    def move_group(self, group: Group, new_parent: Group) -> None:
        """Moves a group in the hierarchy."""
        new_parent.adopt_group(group)
        self._modified = True
        self._emit("scene_changed", change_type="group_moved", group=group, new_parent=new_parent)

    def notify_polygon_transformed(self, polygons: list[Polygon]) -> None:
        """To be called by the Gizmo after each drag frame."""
        self._modified = True
        self._emit("polygon_transformed", polygons=polygons)

    # ------------------------------------------------------------------ #
    # Selection mutators                                                   #
    # ------------------------------------------------------------------ #

    def set_selection(
        self,
        polygons: list[Polygon] | None = None,
        edges: list[tuple[Polygon, int]] | None = None,
        vertices: list[tuple[Polygon, int]] | None = None,
    ) -> None:
        """Replaces the entire selection. Passing None keeps the current value."""
        changed = False
        if polygons is not None:
            new = list(polygons)
            if new != self._selected_polygons:
                self._selected_polygons = new
                changed = True
        if edges is not None:
            new = list(edges)
            if new != self._selected_edges:
                self._selected_edges = new
                changed = True
        if vertices is not None:
            new = list(vertices)
            if new != self._selected_vertices:
                self._selected_vertices = new
                changed = True
        if not changed:
            return
        self._emit("selection_changed",
                   polygons=self.selected_polygons,
                   edges=self.selected_edges,
                   vertices=self.selected_vertices,
                   mode=self._selection_mode)

    def clear_selection(self) -> None:
        """Clears the selection completely."""
        self._selected_polygons = []
        self._selected_edges = []
        self._selected_vertices = []
        self._emit("selection_changed",
                   polygons=[],
                   edges=[],
                   vertices=[],
                   mode=self._selection_mode)

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """Changes the selection mode and clears incompatible selection."""
        if mode == self._selection_mode:
            return
        self._selection_mode = mode
        self._selected_groups = []
        # Clear selections incompatible with the new mode
        if mode == "polygon":
            self._selected_edges = []
            self._selected_vertices = []
        elif mode == "edge":
            self._selected_polygons = []
            self._selected_vertices = []
        elif mode == "vertex":
            self._selected_polygons = []
            self._selected_edges = []
        self._emit("selection_changed",
                   polygons=self.selected_polygons,
                   edges=self.selected_edges,
                   vertices=self.selected_vertices,
                   mode=self._selection_mode)

    def set_current_group(self, group: Group) -> None:
        """Changes the current group."""
        if group is self._current_group:
            return
        self._current_group = group
        self._emit("current_group_changed", group=group)

    # ------------------------------------------------------------------ #
    # Observer system                                                      #
    # ------------------------------------------------------------------ #

    def subscribe(self, event: EventName, callback: Callable) -> None:
        """Subscribes callback to the event. Idempotent."""
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)

    def unsubscribe(self, event: EventName, callback: Callable) -> None:
        """Unsubscribes callback. Does not raise an error if not found."""
        self._listeners[event] = [
            cb for cb in self._listeners[event] if cb != callback
        ]

    def _emit(self, event: str, **payload) -> None:
        """Emits an event to all subscribers (after the mutation)."""
        if self._emitting:
            return  # guard against notification loops
        self._emitting = True
        try:
            for callback in list(self._listeners[event]):
                callback(**payload)
        finally:
            self._emitting = False

    # ------------------------------------------------------------------ #
    # Internal utilities                                                   #
    # ------------------------------------------------------------------ #

    def _is_descendant_or_equal(self, group: Group, ancestor: Group) -> bool:
        """Checks if group is in the subtree of ancestor (or equal to it)."""
        current = group
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False
