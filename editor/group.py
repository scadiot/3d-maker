"""Hierarchical data structures: Polygon and Group."""

from __future__ import annotations
from typing import Iterator, List, Optional, Tuple, Union


Vertex  = Tuple[float, float, float]
UV      = Tuple[float, float]


class Polygon:
    """A polygon: list of 3D vertices + associated UV coordinates."""

    def __init__(
        self,
        vertices: List[Vertex],
        uvs:      List[UV],
        group:    Optional['Group'] = None,
    ):
        self.vertices:        List[Vertex]     = list(vertices)
        self.uvs:             List[UV]         = list(uvs)
        self.group:           Optional['Group'] = group
        self.texture_atlas_id: int              = 0

    def __repr__(self) -> str:
        return f"Polygon({len(self.vertices)} vertices)"


class Group:
    """Scene hierarchy node. Contains child Groups and Polygons."""

    def __init__(self, name: str = "Group", parent: Optional['Group'] = None):
        self.name:     str                = name
        self.parent:   Optional['Group'] = parent
        self.children: List['Group']     = []
        self.polygons: List[Polygon]     = []
        self.hidden:   bool              = False
        self.locked:   bool              = False

    # ── Add ────────────────────────────────────────────────────────────────────

    def add_polygon(self, vertices: List[Vertex], uvs: List[UV]) -> Polygon:
        """Creates a Polygon, adds it to this group and returns the created object."""
        poly = Polygon(vertices, uvs, group=self)
        self.polygons.append(poly)
        return poly

    def add_group(self, name: str = "Group") -> 'Group':
        """Creates a child group, adds it to this group and returns the created object."""
        child = Group(name=name, parent=self)
        self.children.append(child)
        return child

    def adopt_polygon(self, poly: Polygon) -> None:
        """Moves an existing Polygon into this group."""
        old_parent = poly.group
        if old_parent is not None and old_parent is not self:
            old_parent.polygons.remove(poly)
        poly.group = self
        if poly not in self.polygons:
            self.polygons.append(poly)

    def adopt_group(self, child: 'Group') -> None:
        """Moves an existing Group into this group."""
        old_parent = child.parent
        if old_parent is not None and old_parent is not self:
            old_parent.children.remove(child)
        child.parent = self
        if child not in self.children:
            self.children.append(child)

    # ── Remove ─────────────────────────────────────────────────────────────────

    def remove_polygon(self, poly: Polygon) -> None:
        """Removes a direct Polygon from this group (without deleting from memory)."""
        self.polygons.remove(poly)
        poly.group = None

    def remove_group(self, child: 'Group') -> None:
        """Removes a direct child Group from this group (without deleting from memory)."""
        self.children.remove(child)
        child.parent = None

    # ── Utilities ──────────────────────────────────────────────────────────────

    @property
    def is_root(self) -> bool:
        return self.parent is None

    def __repr__(self) -> str:
        return f"Group({self.name!r}, {len(self.children)} children, {len(self.polygons)} polygons)"


# ── Traversal helpers ──────────────────────────────────────────────────────────

def iter_polygons(node: Union[Group, Polygon]) -> Iterator[Polygon]:
    """Recursively traverses the subtree and yields all Polygons."""
    if isinstance(node, Polygon):
        yield node
    else:
        yield from node.polygons
        for child in node.children:
            yield from iter_polygons(child)


def iter_groups(node: Group) -> Iterator[Group]:
    """Recursively traverses the subtree and yields all Groups (except the root itself)."""
    for child in node.children:
        yield child
        yield from iter_groups(child)


def iter_children(node: Group) -> Iterator[Union[Group, Polygon]]:
    """Recursively traverses the subtree and yields all children (groups and polygons)."""
    yield from node.polygons
    for child in node.children:
        yield child
        yield from iter_children(child)


def all_polygons(node: Union[Group, Polygon]) -> List[Polygon]:
    """Returns the list of all Polygons in the subtree."""
    return list(iter_polygons(node))


def is_visible(poly: Polygon) -> bool:
    """Returns True if the polygon is visible (no ancestor group is hidden)."""
    node = poly.group
    while node is not None:
        if node.hidden:
            return False
        node = node.parent
    return True
