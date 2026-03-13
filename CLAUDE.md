# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py
```

## Architecture

Single-file Python 3D editor ([main.py](main.py), ~565 lines) using Pygame for windowing and PyOpenGL (fixed-function pipeline) for rendering.

**Layout**: 1530×720 window split into a 250px left UI panel and a 1280×720 3D viewport.

**Global state** (module-level variables):
- Camera: `cam_pos`, `cam_yaw`, `cam_pitch`
- Scene: `quads` list, `selected_obj`, `gizmo_mode` (0=translate, 1=rotate, 2=scale)
- Drag state: `drag_axis`, `drag_start_*` variables for in-progress gizmo operations

**Core systems in [main.py](main.py)**:

| Lines | System |
|-------|--------|
| 52–61 | Inline vector math (`vadd`, `vsub`, `vscale`, `dot`, `cross`, `normalize`) |
| 63–90 | Camera helpers: `world_to_screen`, `screen_ray` |
| 92–125 | Ray intersection: ray-triangle, ray-quad, ray-plane, ray-line |
| 127–183 | Geometry utilities + gizmo configuration (axis colors, scale handle positions) |
| 185–290 | Gizmo draw + pick functions for translate/rotate/scale |
| 292–314 | `add_quad`, `draw_quads` |
| 316–377 | Drag update handlers (apply transform each frame during drag) |
| 379–456 | Grid, 2D text, and side-panel rendering |
| 458–560 | Main event loop |

**Gizmo system**: Space bar cycles `gizmo_mode`. On mouse-down, `pick_*_axis` casts a ray and sets `drag_axis`. Each frame, the matching `update_*_drag` function reads the current mouse ray, computes delta from drag-start geometry, and mutates the selected quad's position/rotation/size.

**Keyboard layout**: AZERTY (ZQSD for camera movement).

**Language**: UI text and code comments are in French.
