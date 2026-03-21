# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Stack

- **Python 3** + **Tkinter** (windowing & UI)
- **PyOpenGL** — fixed-function pipeline (no shaders)
- **pyopengltk** — `OpenGLFrame` widget bridging Tkinter ↔ OpenGL
- **Pillow** — texture atlas loading

**Language**: UI text and code comments are in English.
**Keyboard layout**: AZERTY (Z/Q/S/D for camera movement).

---

## Architecture

The project is a modular 3D polygon editor split into multiple Python modules under `editor/`.

```
main.py                    # Entry point (~9 lines): instantiates App and calls run()
editor/
├── app.py                 # Main App class (1022 lines): window, menu, toolbar, event loop
├── scene.py               # Scene management, polygon ops, picking, save/load JSON
├── group_panel.py         # Hierarchical tree UI (drag-drop, visibility toggles)
├── gizmo.py               # Transform gizmo (translate/rotate/scale)
├── history.py             # Undo/redo via Command Pattern
├── state_manager.py       # Centralized state + observer/event system
├── uv_selector.py         # Interactive texture atlas widget
├── group.py               # Data structures: Polygon, Group, traversal helpers
├── camera.py              # Camera state, projection, ray casting
├── math3d.py              # Pure vector math & ray intersections
├── renderer.py            # Stateless grid renderer
└── constants.py           # Window dimensions, FOV, gizmo config, asset paths
```

---

## Key Data Structures

### `Polygon` (`editor/group.py`)
- `vertices: List[Tuple[float, float, float]]` — 3D coordinates
- `uvs: List[Tuple[float, float]]` — texture coords in [0,1]×[0,1]
- `group: Optional[Group]` — parent group reference

### `Group` (`editor/group.py`)
- `name: str`, `hidden: bool`
- `parent: Optional[Group]` — `None` only for root
- `children: List[Group]`, `polygons: List[Polygon]`
- Unbounded tree depth; traversal helpers: `iter_polygons()`, `all_polygons()`

### `StateManager` (`editor/state_manager.py`)
Single source of truth. Holds:
- `root_group: Group` — scene root
- `current_group: Group` — context for new polygon creation
- `selection_mode: Literal["polygon", "edge", "vertex"]`
- `selected_polygons: List[Polygon]`
- `selected_edges: List[Tuple[Polygon, int]]`
- `selected_vertices: List[Tuple[Polygon, int]]`

Observer pattern — components subscribe to events emitted on mutation:

| Event | Emitted when |
|-------|-------------|
| `scene_changed` | Hierarchy modified (polygon added, deleted, grouped, …) |
| `selection_changed` | Selection updated |
| `current_group_changed` | Active group switched |
| `polygon_transformed` | Vertices mutated during drag |

```python
state.subscribe("selection_changed", lambda **kw: ...)
```

---

## Modules in Detail

### `app.py` — Main controller
- Creates Tkinter window, menu bar, two toolbars, left panel, OpenGL viewport
- Owns the main frame loop (via Tkinter's `after`)
- Dispatches mouse/keyboard events to `Scene`, `Gizmo`, `Camera`
- **Toolbar 1**: File (Save/Load), Edit (Undo/Redo, Duplicate, Delete), Polygon (Add Quad/Triangle), Group ops
- **Toolbar 2**: Gizmo mode selector, snap sliders, selection mode toggle
- Left panel: `GroupPanel` (tree) + `UVSelector` (atlas preview), resizable via drag separator

### `scene.py` — Scene state
- Stores polygon list; wraps `StateManager` for mutations
- `pick_polygon(ray)` / `pick_edge(ray)` / `pick_vertex(ray)` — ray cast selection
- `draw()` — OpenGL polygon rendering (textured faces, edge outlines, selection highlights)
- `save_json()` / `load_json()` — hierarchical JSON format; supports legacy flat format

### `gizmo.py` — Transform gizmo (464 lines)
Three modes (cycle with **Space**):
1. **Translate** — move along X/Y/Z axes
2. **Rotate** — rotate around center point
3. **Scale** — scale width/height/uniform (single polygon)

State machine per drag:
- Mouse-down → `pick_*_axis()` ray cast → sets `dragging_axis`
- Mouse-move → `update_*_drag()` computes delta, mutates vertices via `StateManager`
- Mouse-up → `finish_drag()` records `TransformCommand` in history

### `history.py` — Undo/redo
Command Pattern (max 100 commands):
- `TransformCommand` — stores vertices before/after, replays via `polygon.vertices = …`
- `CompoundCommand` — groups multiple commands into one entry
- `HistoryManager` — maintains undo/redo stacks

### `camera.py` — Camera
- State: `pos`, `yaw`, `pitch`
- `screen_ray(vx, vy)` — viewport coords → 3D ray direction
- Movement: Z/S (forward/back), Q/D (strafe), right-drag (rotate), wheel (zoom)

### `math3d.py` — Pure math
- Vector ops: `vadd`, `vsub`, `vscale`, `dot`, `cross`, `normalize`
- Intersections: `ray_triangle`, `ray_plane`, `ray_line` (Möller–Trumbore)

### `constants.py`
- Window: `PANEL_WIDTH`, `VIEW_WIDTH`, `HEIGHT`
- Camera: `FOV`, `NEAR`, `FAR`, `MOVE_SPEED`, `MOUSE_SENSITIVITY`
- Assets: `TEXTURE_PATH`, `ATLAS_JSON` — **hardcoded absolute paths** (`C:\Dev\Paris\assets\…`)
- Gizmo: `GIZMO_MODES`, `GIZMO_AXES`, `SCALE_COLORS`

---

## UI Layout

```
┌──────────────────────────────────────────────────────┐
│  Menu Bar (File, Édition, …)                         │
│  Toolbar 1 (actions)                                 │
│  Toolbar 2 (gizmo mode, snap, selection mode)        │
├──────────────────┬───────────────────────────────────┤
│  GroupPanel      │  3D Viewport (OpenGL)             │
│  (tree + icons)  │  Grid + polygons + gizmo          │
│                  │                                   │
│  ─────────────── │  Middle-click: focus camera       │
│  UVSelector      │  Right-drag: orbit camera         │
│  (atlas preview) │  Wheel: zoom                      │
├──────────────────┴───────────────────────────────────┤
│  Status bar (selection info)                         │
└──────────────────────────────────────────────────────┘
```

Left panel width: resizable via drag separator (100px–700px).

---

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Z / S | Camera forward / backward |
| Q / D | Camera strafe left / right |
| Space | Cycle gizmo mode (Translate → Rotate → Scale) |
| Tab | Cycle selection mode (polygon ↔ edge ↔ vertex) |
| A | Add quad |
| T | Add triangle |
| C | Duplicate selected |
| Delete | Delete selected |
| G | Group selected |
| H | Ungroup selected |
| R | Rotate UVs |
| F | Flip polygon orientation |
| K | Split selected polygon |
| W | Align edge centers |
| E | Create polygon from selected edges |
| Ctrl+Z | Undo |
| Ctrl+Y | Redo |

---

## Rendering Pipeline

Each frame (via Tkinter `after` loop):

1. `glClear` — color + depth buffers
2. Perspective projection + camera transform (`glRotate` / `glTranslate`)
3. Grid (`renderer.py`) — horizontal plane, colored X/Z axes
4. `scene.draw()`:
   - `GL_BACK` culling, `GL_CW` winding
   - Textured faces: `glBindTexture(atlas)` + `GL_TRIANGLE_FAN` with UV coords
   - Edge outlines: orange (root-level), blue (grouped), red (selected)
   - Selected edges: thick blue lines, no depth test
   - Selected vertices: green points, no depth test
5. `gizmo.draw()` — arrows, arcs, or scale boxes depending on mode
6. Buffer swap

---

## Save / Load Format

JSON, hierarchical:
```json
{
  "root": {
    "name": "Scène",
    "groups": [
      {
        "name": "Groupe1",
        "polygons": [
          { "vertices": [[x,y,z], ...], "uvs": [[u,v], ...] }
        ],
        "groups": [...]
      }
    ],
    "polygons": [...]
  }
}
```

Legacy flat format (`polygons[]` / `quads[]`) is supported on load.

---

## Design Patterns

| Pattern | Where |
|---------|-------|
| Observer / Event Emitter | `StateManager` — decouples components |
| Single Source of Truth | `StateManager` — all mutations routed here |
| Command Pattern | `history.py` — reversible undo/redo |
| MVC (implicit) | Model: StateManager+Scene+Group/Polygon · View: Viewport+GroupPanel+UVSelector · Controller: App+Gizmo |
