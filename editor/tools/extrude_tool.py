"""ExtrudeTool: edge extrusion tool."""

from editor.tools.tool import Tool
from editor.core.group import Polygon
from editor.core.history import ExtrudeEdgesCommand


class ExtrudeTool(Tool):

    name = 'extrude'

    def __init__(self, app):
        super().__init__(app)
        self._prev_gizmo_mode = 'universal'
        self._history_depth   = 0

    # ── Toolbar integration ───────────────────────────────────────────────────

    @property
    def toolbar_button_specs(self):
        def visible():
            return (self.state.selection_mode == 'edge'
                    and len(self.state.selected_edges) >= 1
                    and not self.state.tool_active)

        return [{"label": "Extrude", "command": self.activate, "visible": visible}]

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def activate(self) -> None:
        """Enter extrusion mode: create a quad face for each selected edge, then
        select the new top edges so the translate gizmo can move them."""
        edges = list(self.state.selected_edges)
        if not edges:
            return

        new_polys: list     = []
        new_top_edges: list = []

        for poly, edge_idx in edges:
            n   = len(poly.vertices)
            v0  = tuple(poly.vertices[edge_idx])
            v1  = tuple(poly.vertices[(edge_idx + 1) % n])
            uv0 = tuple(poly.uvs[edge_idx]) if edge_idx < len(poly.uvs) else (0.0, 0.0)
            uv1 = tuple(poly.uvs[(edge_idx + 1) % n]) if len(poly.uvs) > 0 else (0.0, 0.0)

            new_poly = Polygon(
                vertices=[list(v1), list(v0), list(v0), list(v1)],
                uvs=[list(uv1), list(uv0), list(uv0), list(uv1)],
            )
            new_poly.texture_atlas_id = poly.texture_atlas_id
            target = poly.group if poly.group is not None else self.state.root_group
            target.adopt_polygon(new_poly)

            new_polys.append(new_poly)
            new_top_edges.append((new_poly, 2))  # edge 2 = v1_copy -> v0_copy

        self.state._emit("scene_changed", change_type="polygon_added")
        self._history_depth = self.history.depth
        cmd = ExtrudeEdgesCommand(self.state, new_polys, edges, new_top_edges)
        self.history.record(cmd)

        self.state.set_selection(edges=new_top_edges, polygons=[])

        self._prev_gizmo_mode = self.gizmo.mode
        self.state.active_tool_name  = self.name
        self.state.tool_active       = True
        self.state.selection_enable  = False
        self.gizmo.mode              = 'universal'
        self.app._sync_gizmo_btns()
        self.app._sync_toolbar2_btns()

    def confirm(self) -> None:
        """Keep the extruded faces and exit extrusion mode (Enter key)."""
        self.state.tool_active      = False
        self.state.active_tool_name = ""
        self.state.selection_enable = True
        self.gizmo.mode             = self._prev_gizmo_mode
        self.app._sync_gizmo_btns()
        self.app._sync_toolbar2_btns()

    def cancel(self) -> None:
        """Undo all extrusion actions and exit extrusion mode (Escape key)."""
        while self.history.depth > self._history_depth:
            self.history.undo()
        self.state.tool_active      = False
        self.state.active_tool_name = ""
        self.state.selection_enable = True
        self.gizmo.mode             = self._prev_gizmo_mode
        self.app._sync_gizmo_btns()
        self.app._sync_toolbar2_btns()

    def deactivate(self) -> None:
        self.cancel()
