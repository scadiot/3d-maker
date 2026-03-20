"""UV Selector component: displays the texture atlas in the left panel."""

import tkinter as tk
from PIL import Image, ImageTk

from editor.constants import TEXTURE_PATH, PANEL_WIDTH

_ZOOM_MIN = 1.0
_ZOOM_MAX = 8.0
_SRC_MAX  = 1024   # max resolution of the source image kept in memory


class UVSelector(tk.Frame):
    """Widget embedded in the left panel to select a UV region from the atlas."""

    def __init__(self, master, scene, on_uv_assigned=None, **kw):
        super().__init__(master, bg='#1a1a21', **kw)
        self._scene            = scene
        self._on_uv_assigned   = on_uv_assigned   # callback(polys_before) called after assignment
        self._src_img     = None   # source PIL image (aspect ratio preserved)
        self._photo       = None   # current PhotoImage (prevents GC)
        self._zoom        = 1.0
        self._pan_x       = 0.0
        self._pan_y       = 0.0
        self._drag_last_x = 0
        self._drag_last_y = 0
        self._uv_drag_vertex = None   # (poly, idx) being dragged, or None
        self._uv_drag_before = None   # {poly: (vertices_snap, uvs_snap)} before drag
        self._canvas_w    = PANEL_WIDTH
        self._canvas_h    = PANEL_WIDTH
        # Image size at zoom=1 (aspect ratio preserved, fitted to canvas)
        self._fit_w       = PANEL_WIDTH
        self._fit_h       = PANEL_WIDTH

        tk.Label(
            self, text="UV Selector",
            bg='#1a1a21', fg='#c8c8d8',
            font=('Segoe UI', 8, 'bold'),
        ).pack(pady=(6, 2))

        self._canvas = tk.Canvas(
            self,
            width=PANEL_WIDTH, height=PANEL_WIDTH,
            bg='#111118', highlightthickness=0,
            cursor='crosshair',
        )
        self._canvas.pack(fill=tk.BOTH, expand=True)

        self._canvas.bind('<Configure>',       self._on_configure)
        self._canvas.bind('<Button-1>',        self._on_left_down)
        self._canvas.bind('<ButtonRelease-1>', self._on_left_up)
        self._canvas.bind('<MouseWheel>',      self._on_wheel)
        self._canvas.bind('<Button-2>',        self._on_middle_down)
        self._canvas.bind('<ButtonRelease-2>', self._on_middle_up)
        self._canvas.bind('<Motion>',          self._on_motion)

        self._load_texture()

        state = getattr(scene, '_state', None)
        if state is not None:
            state.subscribe("selection_changed",   lambda **_: self._redraw())
            state.subscribe("polygon_transformed", lambda **_: self._redraw())

    # ── Loading ───────────────────────────────────────────────────────────────
    def _load_texture(self):
        try:
            img = Image.open(TEXTURE_PATH)
            scale = min(1.0, _SRC_MAX / max(img.width, img.height))
            self._src_img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.LANCZOS,
            )
            self._compute_fit()
            self._redraw()
        except Exception:
            self._canvas.create_text(
                self._canvas_w // 2, self._canvas_h // 2,
                text="Texture\nnot found",
                fill='#666680',
                font=('Segoe UI', 9),
                justify='center',
            )

    # ── Fit computation (aspect ratio preserved, centered in canvas) ───────────
    def _compute_fit(self):
        if self._src_img is None:
            return
        src_w, src_h = self._src_img.size
        scale = min(self._canvas_w / src_w, self._canvas_h / src_h)
        self._fit_w = max(1, int(src_w * scale))
        self._fit_h = max(1, int(src_h * scale))
        # Initial pan = image centered in canvas
        self._zoom  = 1.0
        self._pan_x = (self._canvas_w - self._fit_w) / 2
        self._pan_y = (self._canvas_h - self._fit_h) / 2

    # ── Canvas resize ─────────────────────────────────────────────────────────
    def _on_configure(self, event):
        if event.width == self._canvas_w and event.height == self._canvas_h:
            return
        self._canvas_w = max(1, event.width)
        self._canvas_h = max(1, event.height)
        self._compute_fit()
        self._redraw()

    # ── Rendering ─────────────────────────────────────────────────────────────
    def _redraw(self):
        if self._src_img is None:
            return
        sz_w = max(1, int(self._fit_w * self._zoom))
        sz_h = max(1, int(self._fit_h * self._zoom))
        img  = self._src_img.resize((sz_w, sz_h), Image.NEAREST)
        self._photo = ImageTk.PhotoImage(img)
        self._canvas.delete('all')
        self._canvas.create_image(int(self._pan_x), int(self._pan_y),
                                   anchor='nw', image=self._photo)
        self._draw_uv_overlay()

    def _uv_to_canvas(self, u, v):
        x = self._pan_x + u * self._fit_w * self._zoom
        y = self._pan_y + (1.0 - v) * self._fit_h * self._zoom
        return x, y

    def _canvas_to_uv(self, cx, cy):
        u = (cx - self._pan_x) / (self._fit_w * self._zoom)
        v = 1.0 - (cy - self._pan_y) / (self._fit_h * self._zoom)
        return u, v

    def _get_visible_uv_vertices(self):
        """Returns list of (poly, idx) for all currently visible UV vertices."""
        state = getattr(self._scene, '_state', None)
        if state is None:
            return []
        mode = state.selection_mode
        if mode == "polygon":
            return [(poly, i) for poly in state.selected_polygons
                    for i in range(len(poly.uvs))]
        elif mode == "edge":
            result = []
            for poly, i in state.selected_edges:
                result.append((poly, i))
                result.append((poly, (i + 1) % len(poly.uvs)))
            return result
        elif mode == "vertex":
            return list(state.selected_vertices)
        return []

    def _hit_uv_vertex(self, cx, cy, radius=6):
        """Returns (poly, idx) of the first UV vertex within radius pixels, or None."""
        for poly, idx in self._get_visible_uv_vertices():
            u, v = poly.uvs[idx]
            vx, vy = self._uv_to_canvas(u, v)
            if abs(cx - vx) <= radius and abs(cy - vy) <= radius:
                return poly, idx
        return None

    def _draw_uv_overlay(self):
        state = getattr(self._scene, '_state', None)
        if state is None:
            return

        mode = state.selection_mode

        if mode == "polygon":
            polys = state.selected_polygons
            for poly in polys:
                n = len(poly.uvs)
                if n < 2:
                    continue
                # edges
                for i in range(n):
                    u0, v0 = poly.uvs[i]
                    u1, v1 = poly.uvs[(i + 1) % n]
                    x0, y0 = self._uv_to_canvas(u0, v0)
                    x1, y1 = self._uv_to_canvas(u1, v1)
                    self._canvas.create_line(x0, y0, x1, y1, fill='#ff8800', width=1)
                # vertices
                for u, v in poly.uvs:
                    cx, cy = self._uv_to_canvas(u, v)
                    self._canvas.create_oval(cx-3, cy-3, cx+3, cy+3,
                                             fill='#ffffff', outline='#ff8800', width=1)

        elif mode == "edge":
            for poly, i in state.selected_edges:
                n = len(poly.uvs)
                u0, v0 = poly.uvs[i]
                u1, v1 = poly.uvs[(i + 1) % n]
                x0, y0 = self._uv_to_canvas(u0, v0)
                x1, y1 = self._uv_to_canvas(u1, v1)
                self._canvas.create_line(x0, y0, x1, y1, fill='#4488ff', width=2)
                for u, v in (poly.uvs[i], poly.uvs[(i + 1) % n]):
                    cx, cy = self._uv_to_canvas(u, v)
                    self._canvas.create_oval(cx-3, cy-3, cx+3, cy+3,
                                             fill='#ffffff', outline='#4488ff', width=1)

        elif mode == "vertex":
            for poly, i in state.selected_vertices:
                u, v = poly.uvs[i]
                cx, cy = self._uv_to_canvas(u, v)
                self._canvas.create_oval(cx-4, cy-4, cx+4, cy+4,
                                         fill='#44ff88', outline='#ffffff', width=1)

    # ── Zoom (mouse wheel) ────────────────────────────────────────────────────
    def _on_wheel(self, event):
        factor   = 1.15 if event.delta > 0 else 1 / 1.15
        old_zoom = self._zoom
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        ratio = self._zoom / old_zoom
        self._pan_x = event.x - (event.x - self._pan_x) * ratio
        self._pan_y = event.y - (event.y - self._pan_y) * ratio
        self._clamp_pan()
        self._redraw()

    # ── Drag (middle button held) ─────────────────────────────────────────────
    def _on_middle_down(self, event):
        self._drag_last_x = event.x
        self._drag_last_y = event.y
        self._canvas.config(cursor='fleur')

    def _on_middle_up(self, event):
        self._canvas.config(cursor='crosshair')

    def _on_motion(self, event):
        if event.state & 0x0200:   # button 2 held → pan
            dx = event.x - self._drag_last_x
            dy = event.y - self._drag_last_y
            self._drag_last_x = event.x
            self._drag_last_y = event.y
            self._pan_x += dx
            self._pan_y += dy
            self._clamp_pan()
            self._redraw()
        elif (event.state & 0x0100) and self._uv_drag_vertex is not None:
            poly, idx = self._uv_drag_vertex
            u, v = self._canvas_to_uv(event.x, event.y)
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
            uvs = list(poly.uvs)
            uvs[idx] = (u, v)
            poly.uvs = uvs
            state = getattr(self._scene, '_state', None)
            if state is not None:
                state.notify_polygon_transformed([poly])
            self._redraw()

    # ── Left click / UV vertex drag ───────────────────────────────────────────
    def _on_left_down(self, event):
        hit = self._hit_uv_vertex(event.x, event.y)
        if hit is not None:
            poly = hit[0]
            self._uv_drag_vertex = hit
            self._uv_drag_before = {poly: (list(poly.vertices), list(poly.uvs))}
            return
        # No vertex hit → UV assignment
        img_x = (event.x - self._pan_x) / self._zoom
        img_y = (event.y - self._pan_y) / self._zoom
        atlas_x = int(img_x * self._scene.atlas_w / self._fit_w)
        atlas_y = int(img_y * self._scene.atlas_h / self._fit_h)
        if self._on_uv_assigned:
            polys = self._scene._state.selected_polygons if self._scene._state else []
            before = {p: (list(p.vertices), list(p.uvs)) for p in polys}
            self._scene.assign_uv_at_atlas_pixel(atlas_x, atlas_y)
            after = {p: (list(p.vertices), list(p.uvs)) for p in polys}
            self._on_uv_assigned(before, after)
        else:
            self._scene.assign_uv_at_atlas_pixel(atlas_x, atlas_y)

    def _on_left_up(self, event):
        if self._uv_drag_vertex is not None and self._uv_drag_before is not None:
            poly = self._uv_drag_vertex[0]
            after = {poly: (list(poly.vertices), list(poly.uvs))}
            if self._on_uv_assigned:
                self._on_uv_assigned(self._uv_drag_before, after)
        self._uv_drag_vertex = None
        self._uv_drag_before = None

    # ── Utility ───────────────────────────────────────────────────────────────
    def _clamp_pan(self):
        """Prevents the image from going entirely out of the canvas."""
        sz_w = self._fit_w * self._zoom
        sz_h = self._fit_h * self._zoom
        self._pan_x = max(self._canvas_w * 0.25 - sz_w,
                          min(self._canvas_w * 0.75, self._pan_x))
        self._pan_y = max(self._canvas_h * 0.25 - sz_h,
                          min(self._canvas_h * 0.75, self._pan_y))
