"""StateManager — Source unique de vérité pour l'état de la scène."""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, Literal

from editor.group import Group, Polygon, all_polygons


SelectionMode = Literal["polygon", "edge", "vertex"]
EventName = Literal[
    "scene_changed",
    "selection_changed",
    "current_group_changed",
    "polygon_transformed",
]


class StateManager:
    """Source unique de vérité pour l'état de la scène.

    Centralise toutes les données significatives (hiérarchie, sélection,
    groupe courant) et notifie les abonnés via un système d'observeurs.
    Ne contient ni logique de rendu, ni logique d'UI.
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
        self._listeners: dict[str, list[Callable]] = defaultdict(list)
        self._emitting: bool = False  # garde contre les boucles de notification

    # ------------------------------------------------------------------ #
    # Accesseurs (lecture)                                                 #
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

    # ------------------------------------------------------------------ #
    # Mutateurs scène                                                      #
    # ------------------------------------------------------------------ #

    def add_polygon(self, polygon: Polygon, group: Group | None = None) -> None:
        """Ajoute un polygone au groupe donné (ou current_group par défaut)."""
        target = group if group is not None else self._current_group
        target.adopt_polygon(polygon)
        self._emit("scene_changed", change_type="polygon_added", polygon=polygon, group=target)

    def delete_polygons(self, polygons: list[Polygon]) -> None:
        """Supprime les polygones de la scène et met à jour la sélection."""
        to_delete = set(polygons)
        for polygon in polygons:
            if polygon.group is not None:
                polygon.group.remove_polygon(polygon)
        # Nettoyer la sélection
        self._selected_polygons = [p for p in self._selected_polygons if p not in to_delete]
        self._selected_edges = [(p, i) for p, i in self._selected_edges if p not in to_delete]
        self._selected_vertices = [(p, i) for p, i in self._selected_vertices if p not in to_delete]
        self._emit("scene_changed", change_type="polygons_deleted", polygons=list(polygons))
        self._emit("selection_changed",
                   polygons=self.selected_polygons,
                   edges=self.selected_edges,
                   vertices=self.selected_vertices,
                   mode=self._selection_mode)

    def move_polygon(self, polygon: Polygon, new_group: Group) -> None:
        """Déplace un polygone vers un autre groupe."""
        new_group.adopt_polygon(polygon)
        self._emit("scene_changed", change_type="polygon_moved", polygon=polygon, new_group=new_group)

    def add_group(self, name: str, parent: Group | None = None) -> Group:
        """Crée un nouveau groupe enfant."""
        target_parent = parent if parent is not None else self._current_group
        new_group = target_parent.add_group(name)
        self._emit("scene_changed", change_type="group_added", group=new_group, parent=target_parent)
        return new_group

    def delete_group(self, group: Group) -> None:
        """Supprime un groupe et tous ses enfants (et met à jour la sélection)."""
        deleted_polys = set(all_polygons(group))
        if group.parent is not None:
            group.parent.remove_group(group)
        # Si le groupe courant était dans l'arbre supprimé, revenir à la racine
        if self._is_descendant_or_equal(self._current_group, group):
            self._current_group = self._root_group
        # Nettoyer la sélection
        if deleted_polys:
            self._selected_polygons = [p for p in self._selected_polygons if p not in deleted_polys]
            self._selected_edges = [(p, i) for p, i in self._selected_edges if p not in deleted_polys]
            self._selected_vertices = [(p, i) for p, i in self._selected_vertices if p not in deleted_polys]
        self._emit("scene_changed", change_type="group_deleted", group=group)
        if deleted_polys:
            self._emit("selection_changed",
                       polygons=self.selected_polygons,
                       edges=self.selected_edges,
                       vertices=self.selected_vertices,
                       mode=self._selection_mode)

    def rename_group(self, group: Group, name: str) -> None:
        """Renomme un groupe."""
        old_name = group.name
        group.name = name
        self._emit("scene_changed", change_type="group_renamed", group=group, old_name=old_name)

    def move_group(self, group: Group, new_parent: Group) -> None:
        """Déplace un groupe dans la hiérarchie."""
        new_parent.adopt_group(group)
        self._emit("scene_changed", change_type="group_moved", group=group, new_parent=new_parent)

    def notify_polygon_transformed(self, polygons: list[Polygon]) -> None:
        """À appeler par le Gizmo après chaque frame de drag."""
        self._emit("polygon_transformed", polygons=polygons)

    # ------------------------------------------------------------------ #
    # Mutateurs sélection                                                  #
    # ------------------------------------------------------------------ #

    def set_selection(
        self,
        polygons: list[Polygon] | None = None,
        edges: list[tuple[Polygon, int]] | None = None,
        vertices: list[tuple[Polygon, int]] | None = None,
    ) -> None:
        """Remplace toute la sélection. Passer None conserve la valeur actuelle."""
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
        """Vide la sélection complètement."""
        self._selected_polygons = []
        self._selected_edges = []
        self._selected_vertices = []
        self._emit("selection_changed",
                   polygons=[],
                   edges=[],
                   vertices=[],
                   mode=self._selection_mode)

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """Change le mode de sélection et vide la sélection incompatible."""
        if mode == self._selection_mode:
            return
        self._selection_mode = mode
        # Vider les sélections incompatibles avec le nouveau mode
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
        """Change le groupe courant."""
        if group is self._current_group:
            return
        self._current_group = group
        self._emit("current_group_changed", group=group)

    # ------------------------------------------------------------------ #
    # Système d'observeurs                                                 #
    # ------------------------------------------------------------------ #

    def subscribe(self, event: EventName, callback: Callable) -> None:
        """Abonne callback à l'événement. Idempotent."""
        if callback not in self._listeners[event]:
            self._listeners[event].append(callback)

    def unsubscribe(self, event: EventName, callback: Callable) -> None:
        """Désabonne callback. Ne lève pas d'erreur si absent."""
        self._listeners[event] = [
            cb for cb in self._listeners[event] if cb != callback
        ]

    def _emit(self, event: str, **payload) -> None:
        """Émet un événement vers tous les abonnés (après la mutation)."""
        if self._emitting:
            return  # garde contre les boucles de notification
        self._emitting = True
        try:
            for callback in list(self._listeners[event]):
                callback(**payload)
        finally:
            self._emitting = False

    # ------------------------------------------------------------------ #
    # Utilitaires internes                                                 #
    # ------------------------------------------------------------------ #

    def _is_descendant_or_equal(self, group: Group, ancestor: Group) -> bool:
        """Vérifie si group est dans le sous-arbre de ancestor (ou égal)."""
        current = group
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False
