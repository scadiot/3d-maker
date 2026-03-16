"""Structures de données hiérarchiques : Polygon et Group."""

from __future__ import annotations
from typing import Iterator, List, Optional, Tuple, Union


Vertex = Tuple[float, float, float]
UV     = Tuple[float, float]


class Polygon:
    """Un polygone : liste de sommets 3D + coordonnées UV associées."""

    def __init__(
        self,
        vertices: List[Vertex],
        uvs:      List[UV],
        group:    Optional['Group'] = None,
    ):
        self.vertices: List[Vertex] = list(vertices)
        self.uvs:      List[UV]     = list(uvs)
        self.group:    Optional['Group'] = group

    def __repr__(self) -> str:
        return f"Polygon({len(self.vertices)} sommets)"


class Group:
    """Nœud de la hiérarchie de scène. Contient des Group enfants et des Polygon."""

    def __init__(self, name: str = "Groupe", parent: Optional['Group'] = None):
        self.name:     str                = name
        self.parent:   Optional['Group'] = parent
        self.children: List['Group']     = []
        self.polygons: List[Polygon]     = []

    # ── Ajout ──────────────────────────────────────────────────────────────────

    def add_polygon(self, vertices: List[Vertex], uvs: List[UV]) -> Polygon:
        """Crée un Polygon, l'ajoute à ce groupe et retourne l'objet créé."""
        poly = Polygon(vertices, uvs, group=self)
        self.polygons.append(poly)
        return poly

    def add_group(self, name: str = "Groupe") -> 'Group':
        """Crée un groupe enfant, l'ajoute à ce groupe et retourne l'objet créé."""
        child = Group(name=name, parent=self)
        self.children.append(child)
        return child

    def adopt_polygon(self, poly: Polygon) -> None:
        """Déplace un Polygon existant dans ce groupe."""
        old_parent = poly.group
        if old_parent is not None and old_parent is not self:
            old_parent.polygons.remove(poly)
        poly.group = self
        if poly not in self.polygons:
            self.polygons.append(poly)

    def adopt_group(self, child: 'Group') -> None:
        """Déplace un Group existant dans ce groupe."""
        old_parent = child.parent
        if old_parent is not None and old_parent is not self:
            old_parent.children.remove(child)
        child.parent = self
        if child not in self.children:
            self.children.append(child)

    # ── Suppression ────────────────────────────────────────────────────────────

    def remove_polygon(self, poly: Polygon) -> None:
        """Retire un Polygon direct de ce groupe (sans le supprimer de la mémoire)."""
        self.polygons.remove(poly)
        poly.group = None

    def remove_group(self, child: 'Group') -> None:
        """Retire un Group enfant direct de ce groupe (sans le supprimer de la mémoire)."""
        self.children.remove(child)
        child.parent = None

    # ── Utilitaires ────────────────────────────────────────────────────────────

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def __repr__(self) -> str:
        return f"Group({self.name!r}, {len(self.children)} enfants, {len(self.polygons)} polygones)"


# ── Helpers de traversal ───────────────────────────────────────────────────────

def iter_polygons(node: Union[Group, Polygon]) -> Iterator[Polygon]:
    """Parcourt récursivement le sous-arbre et génère tous les Polygon."""
    if isinstance(node, Polygon):
        yield node
    else:
        yield from node.polygons
        for child in node.children:
            yield from iter_polygons(child)


def iter_groups(node: Group) -> Iterator[Group]:
    """Parcourt récursivement le sous-arbre et génère tous les Group (sauf la racine elle-même)."""
    for child in node.children:
        yield child
        yield from iter_groups(child)


def iter_children(node: Group) -> Iterator[Union[Group, Polygon]]:
    """Parcourt récursivement le sous-arbre et génère tous les enfants (groupes et polygones)."""
    yield from node.polygons
    for child in node.children:
        yield child
        yield from iter_children(child)


def all_polygons(node: Union[Group, Polygon]) -> List[Polygon]:
    """Retourne la liste de tous les Polygon du sous-arbre."""
    return list(iter_polygons(node))
