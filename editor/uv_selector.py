"""UV Selector component: displays the texture atlas in the left panel via OpenGL."""

import os
import tkinter as tk
from PIL import Image

from pyopengltk import OpenGLFrame
from OpenGL.GL import (
    glClearColor, glClear, GL_COLOR_BUFFER_BIT,
    glViewport,
    glMatrixMode, GL_PROJECTION, GL_MODELVIEW,
    glLoadIdentity, glOrtho,
    glEnable, glDisable,
    GL_TEXTURE_2D, GL_BLEND, GL_DEPTH_TEST,
    GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
    glBlendFunc,
    glBindTexture, glGenTextures, glDeleteTextures,
    glTexImage2D, glTexParameteri,
    GL_RGBA, GL_UNSIGNED_BYTE,
    GL_LINEAR, GL_NEAREST,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE,
    glBegin, glEnd,
    GL_QUADS, GL_LINE_LOOP, GL_LINES, GL_POINTS,
    glTexCoord2f, glVertex2f,
    glColor3f, glColor4f,
    glPointSize, glLineWidth,
)

from editor.constants import PANEL_WIDTH

_ZOOM_MIN = 1.0
_ZOOM_MAX = 32.0
_SRC_MAX  = 1024   # max resolution of the source image kept in memory


class _DarkDropdown(tk.Frame):
    """Dark-themed dropdown widget matching the application's dark design."""

    def __init__(self, master, textvariable, font=None, **kw):
        super().__init__(master, bg='#252530', bd=0,
                         highlightbackground='#3a3a4a', highlightthickness=1, **kw)
        self._sel_callbacks = []
        self._var    = textvariable
        self._values = []
        self._popup  = None
        _font = font or ('Segoe UI', 8)

        self._label = tk.Label(
            self, textvariable=self._var,
            bg='#252530', fg='#c8c8d8',
            font=_font, anchor='w', padx=6,
        )
        self._label.pack(side='left', fill='both', expand=True)

        self._arrow = tk.Label(
            self, text='▾',
            bg='#252530', fg='#666680',
            font=_font, padx=6,
        )
        self._arrow.pack(side='right')

        for w in (self, self._label, self._arrow):
            w.bind('<Button-1>', self._toggle_popup)
            w.bind('<Enter>',    lambda e: self._hover(True))
            w.bind('<Leave>',    lambda e: self._hover(False))

    def _hover(self, on):
        c = '#2e2e3e' if on else '#252530'
        self.configure(bg=c)
        self._label.configure(bg=c)
        self._arrow.configure(bg=c)

    def __setitem__(self, key, value):
        if key == 'values':
            self._values = list(value)
        else:
            super().__setitem__(key, value)

    def __getitem__(self, key):
        if key == 'values':
            return self._values
        return super().__getitem__(key)

    def bind(self, sequence=None, func=None, add=None):
        if sequence == '<<ComboboxSelected>>':
            self._sel_callbacks.append(func)
        else:
            super().bind(sequence, func, add)

    def _toggle_popup(self, event=None):
        if self._popup and self._popup.winfo_exists():
            self._close_popup()
        else:
            self._open_popup()

    def _open_popup(self):
        if not self._values:
            return
        self._popup = tk.Toplevel(self)
        self._popup.overrideredirect(True)
        self._popup.configure(bg='#1a1a28',
                              highlightbackground='#3a3a4a',
                              highlightthickness=1)

        lb = tk.Listbox(
            self._popup,
            bg='#1e1e2e', fg='#c8c8d8',
            selectbackground='#3a3a6a', selectforeground='#ffffff',
            activestyle='none',
            highlightthickness=0, bd=0,
            font=('Segoe UI', 8),
            height=min(len(self._values), 8),
            exportselection=False,
        )
        lb.pack(fill='both', expand=True, padx=1, pady=1)

        for val in self._values:
            lb.insert('end', val)

        current = self._var.get()
        if current in self._values:
            idx = self._values.index(current)
            lb.selection_set(idx)
            lb.see(idx)

        self._popup.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        w = self.winfo_width()
        h = lb.winfo_reqheight() + 4
        self._popup.geometry(f'{w}x{h}+{x}+{y}')

        lb.bind('<Motion>',          lambda e: self._lb_hover(e, lb))
        lb.bind('<ButtonRelease-1>', lambda e: self._select(lb) or 'break')
        self._popup.bind('<Escape>',   lambda e: self._close_popup())
        self._popup.grab_set()
        self._popup.focus_set()

    def _lb_hover(self, event, lb):
        lb.selection_clear(0, 'end')
        lb.selection_set(lb.nearest(event.y))

    def _select(self, lb):
        sel = lb.curselection()
        if sel:
            self._var.set(self._values[sel[0]])
            for cb in self._sel_callbacks:
                cb(None)
        self._close_popup()

    def _close_popup(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.grab_release()
            self._popup.destroy()
        self._popup = None


class _UVGLFrame(OpenGLFrame):
    """OpenGL canvas that renders the texture atlas and UV overlays."""

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self._owner       = None   # UVSelector instance
        self._tex_id      = None
        self._pending_img = None   # PIL Image queued for upload

    def initgl(self):
        glClearColor(0.067, 0.067, 0.094, 1.0)   # #111118
        glDisable(GL_DEPTH_TEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        # The GL context may have been recreated (resize on Windows invalidates it).
        # Discard the stale texture ID and re-queue the source image for upload.
        self._tex_id = None
        if self._owner is not None and self._owner._src_img is not None:
            self._pending_img = self._owner._src_img

    def load_image(self, pil_image):
        """Queue a PIL Image for upload on the next redraw (context-safe)."""
        self._pending_img = pil_image

    def _upload_texture(self, pil_image):
        if self._tex_id is not None:
            glDeleteTextures(1, [self._tex_id])
            self._tex_id = None
        img  = pil_image.convert('RGBA')
        w, h = img.size
        # stride=-1 reverses rows so data[0] = bottom row (OpenGL convention)
        data = img.tobytes('raw', 'RGBA', 0, -1)
        tex  = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tex)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        self._tex_id = tex

    def redraw(self):
        if self._owner is None:
            return
        w = self.winfo_width()
        h = self.winfo_height()
        if w < 1 or h < 1:
            return

        # Detect canvas resize and refit (more reliable than <Configure> on Windows)
        owner = self._owner
        if w != owner._canvas_w or h != owner._canvas_h:
            owner._on_gl_resize(w, h)

        # Upload texture if one is pending (GL context is current here)
        if self._pending_img is not None:
            self._upload_texture(self._pending_img)
            self._pending_img = None

        glViewport(0, 0, w, h)
        glClear(GL_COLOR_BUFFER_BIT)

        # Orthographic projection: pixel coordinates, y increases downward
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, w, h, 0, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        owner = self._owner
        px = owner._pan_x
        py = owner._pan_y
        fw = owner._fit_w * owner._zoom
        fh = owner._fit_h * owner._zoom

        # ── Texture quad ──────────────────────────────────────────────────────
        if self._tex_id is not None:
            glEnable(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, self._tex_id)
            glColor4f(1.0, 1.0, 1.0, 1.0)
            glBegin(GL_QUADS)
            # t=1 at top (y=py), t=0 at bottom (y=py+fh) — matches _uv_to_canvas
            glTexCoord2f(0.0, 1.0); glVertex2f(px,      py)
            glTexCoord2f(1.0, 1.0); glVertex2f(px + fw, py)
            glTexCoord2f(1.0, 0.0); glVertex2f(px + fw, py + fh)
            glTexCoord2f(0.0, 0.0); glVertex2f(px,      py + fh)
            glEnd()
            glDisable(GL_TEXTURE_2D)

        # ── UV overlay ────────────────────────────────────────────────────────
        owner._draw_uv_overlay_gl()


class UVSelector(tk.Frame):
    """Widget embedded in the left panel to select a UV region from the atlas."""

    def __init__(self, master, scene, on_uv_assigned=None, **kw):
        super().__init__(master, bg='#1a1a21', **kw)
        self._scene            = scene
        self._on_uv_assigned   = on_uv_assigned
        self._src_img          = None   # source PIL image (for fit computation)
        self._zoom             = 1.0
        self._pan_x            = 0.0
        self._pan_y            = 0.0
        self._drag_last_x      = 0
        self._drag_last_y      = 0
        self._uv_drag_vertex   = None
        self._uv_drag_before   = None
        self._canvas_w         = PANEL_WIDTH
        self._canvas_h         = PANEL_WIDTH
        self._fit_w            = PANEL_WIDTH
        self._fit_h            = PANEL_WIDTH

        tk.Label(
            self, text="UV Selector",
            bg='#1a1a21', fg='#c8c8d8',
            font=('Segoe UI', 8, 'bold'),
        ).pack(pady=(6, 2))

        self._atlas_var   = tk.StringVar(value="")
        self._atlas_combo = _DarkDropdown(
            self,
            textvariable=self._atlas_var,
            font=('Segoe UI', 8),
        )
        self._atlas_combo.pack(fill=tk.X, padx=4, pady=(0, 4))
        self._atlas_combo.bind('<<ComboboxSelected>>', self._on_atlas_selected)

        self._glframe = _UVGLFrame(self, width=PANEL_WIDTH, height=PANEL_WIDTH)
        self._glframe._owner = self
        self._glframe.animate = 1
        self._glframe.pack(fill=tk.BOTH, expand=True)

        self._glframe.bind('<Button-1>',        self._on_left_down)
        self._glframe.bind('<ButtonRelease-1>', self._on_left_up)
        self._glframe.bind('<MouseWheel>',      self._on_wheel)
        self._glframe.bind('<Button-2>',        self._on_middle_down)
        self._glframe.bind('<ButtonRelease-2>', self._on_middle_up)
        self._glframe.bind('<Motion>',          self._on_motion)

        state = getattr(scene, '_state', None)
        if state is not None:
            state.subscribe("selection_changed",   lambda **_: self._sync_atlas_to_selection())
            state.subscribe("polygon_transformed", lambda **_: None)   # GL redraws continuously
            state.subscribe("scene_changed",       lambda **_: self._refresh_atlas_list())
            state.subscribe("textures_changed",    lambda atlases, **_: self._on_textures_changed(atlases))
        self._refresh_atlas_list()

    # ── Atlas list ────────────────────────────────────────────────────────────
    def _refresh_atlas_list(self):
        state = getattr(self._scene, '_state', None)
        if state is None:
            return
        atlases = state.textures_atlases
        names = [os.path.basename(a.image_path) for a in atlases]
        self._atlas_combo['values'] = names
        if not names:
            return
        current = self._atlas_var.get()
        if current not in names:
            self._atlas_var.set(names[0])
            self._load_texture_from_path(atlases[0].image_path)

    def _on_textures_changed(self, atlases):
        names = [os.path.basename(a.image_path) for a in atlases]
        self._atlas_combo['values'] = names
        if not names:
            self._src_img = None
            self._glframe._pending_img = None
            return
        selected = self._atlas_var.get()
        if selected not in names:
            selected = names[0]
            self._atlas_var.set(selected)
        idx = names.index(selected)
        self._load_texture_from_path(atlases[idx].image_path)

    def _on_atlas_selected(self, _event=None):
        state = getattr(self._scene, '_state', None)
        if state is None:
            return
        atlases = state.textures_atlases
        names = [os.path.basename(a.image_path) for a in atlases]
        selected = self._atlas_var.get()
        if selected not in names:
            return
        idx = names.index(selected)
        atlas = atlases[idx]
        self._load_texture_from_path(atlas.image_path)
        for poly in state.selected_polygons:
            poly.texture_atlas_id = atlas.id
        if state.selected_polygons:
            state._modified = True
            state._emit("scene_changed", change_type="texture_assigned")

    def _sync_atlas_to_selection(self):
        state = getattr(self._scene, '_state', None)
        if state is None:
            return
        polys = state.selected_polygons
        if not polys:
            return
        atlas_id = polys[0].texture_atlas_id
        atlases  = state.textures_atlases
        atlas    = next((a for a in atlases if a.id == atlas_id), None)
        if atlas is None:
            return
        name = os.path.basename(atlas.image_path)
        if self._atlas_var.get() != name:
            self._atlas_var.set(name)
            self._load_texture_from_path(atlas.image_path)

    def _load_texture_from_path(self, path: str):
        try:
            img   = Image.open(path)
            scale = min(1.0, _SRC_MAX / max(img.width, img.height))
            self._src_img = img.resize(
                (max(1, int(img.width * scale)), max(1, int(img.height * scale))),
                Image.LANCZOS,
            )
            self._compute_fit()
            self._glframe.load_image(self._src_img)
        except Exception:
            self._src_img = None
            self._glframe._pending_img = None
            if self._glframe._tex_id is not None:
                # Will be cleaned up on next redraw; just clear the reference
                self._glframe._tex_id = None

    # ── Fit computation ───────────────────────────────────────────────────────
    def _compute_fit(self):
        if self._src_img is None:
            return
        src_w, src_h = self._src_img.size
        scale        = min(self._canvas_w / src_w, self._canvas_h / src_h)
        self._fit_w  = max(1, int(src_w * scale))
        self._fit_h  = max(1, int(src_h * scale))
        self._zoom   = 1.0
        self._pan_x  = (self._canvas_w - self._fit_w) / 2
        self._pan_y  = (self._canvas_h - self._fit_h) / 2

    # ── Canvas resize (called from _UVGLFrame.redraw on size change) ──────────
    def _on_gl_resize(self, new_w, new_h):
        if self._src_img is not None:
            cx  = self._canvas_w / 2
            cy  = self._canvas_h / 2
            u_c = (cx - self._pan_x) / (self._fit_w * self._zoom)
            v_c = 1.0 - (cy - self._pan_y) / (self._fit_h * self._zoom)

            self._canvas_w = new_w
            self._canvas_h = new_h

            src_w, src_h = self._src_img.size
            scale        = min(new_w / src_w, new_h / src_h)
            self._fit_w  = max(1, int(src_w * scale))
            self._fit_h  = max(1, int(src_h * scale))

            self._pan_x = new_w / 2 - u_c * self._fit_w * self._zoom
            self._pan_y = new_h / 2 - (1.0 - v_c) * self._fit_h * self._zoom
            self._clamp_pan()
        else:
            self._canvas_w = new_w
            self._canvas_h = new_h
            self._compute_fit()

    # ── UV coordinate helpers ─────────────────────────────────────────────────
    def _uv_to_canvas(self, u, v):
        x = self._pan_x + u * self._fit_w * self._zoom
        y = self._pan_y + (1.0 - v) * self._fit_h * self._zoom
        return x, y

    def _canvas_to_uv(self, cx, cy):
        u = (cx - self._pan_x) / (self._fit_w * self._zoom)
        v = 1.0 - (cy - self._pan_y) / (self._fit_h * self._zoom)
        return u, v

    # ── GL UV overlay (called from _UVGLFrame.redraw) ─────────────────────────
    def _draw_uv_overlay_gl(self):
        state = getattr(self._scene, '_state', None)
        if state is None:
            return
        mode = state.selection_mode

        if mode == "polygon":
            for poly in state.selected_polygons:
                n = len(poly.uvs)
                if n < 2:
                    continue
                # Orange outline
                glColor3f(1.0, 0.533, 0.0)   # #ff8800
                glLineWidth(1.0)
                glBegin(GL_LINE_LOOP)
                for u, v in poly.uvs:
                    x, y = self._uv_to_canvas(u, v)
                    glVertex2f(x, y)
                glEnd()
                # White vertex dots
                glColor3f(1.0, 1.0, 1.0)
                glPointSize(6.0)
                glBegin(GL_POINTS)
                for u, v in poly.uvs:
                    x, y = self._uv_to_canvas(u, v)
                    glVertex2f(x, y)
                glEnd()

        elif mode == "edge":
            glLineWidth(2.0)
            for poly, i in state.selected_edges:
                n        = len(poly.uvs)
                u0, v0   = poly.uvs[i]
                u1, v1   = poly.uvs[(i + 1) % n]
                x0, y0   = self._uv_to_canvas(u0, v0)
                x1, y1   = self._uv_to_canvas(u1, v1)
                glColor3f(0.267, 0.533, 1.0)   # #4488ff
                glBegin(GL_LINES)
                glVertex2f(x0, y0)
                glVertex2f(x1, y1)
                glEnd()
                glColor3f(1.0, 1.0, 1.0)
                glPointSize(6.0)
                glBegin(GL_POINTS)
                glVertex2f(x0, y0)
                glVertex2f(x1, y1)
                glEnd()

        elif mode == "vertex":
            glColor3f(0.267, 1.0, 0.533)   # #44ff88
            glPointSize(8.0)
            glBegin(GL_POINTS)
            for poly, i in state.selected_vertices:
                u, v = poly.uvs[i]
                x, y = self._uv_to_canvas(u, v)
                glVertex2f(x, y)
            glEnd()

    # ── Hit test ──────────────────────────────────────────────────────────────
    def _get_visible_uv_vertices(self):
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
        for poly, idx in self._get_visible_uv_vertices():
            u, v = poly.uvs[idx]
            vx, vy = self._uv_to_canvas(u, v)
            if abs(cx - vx) <= radius and abs(cy - vy) <= radius:
                return poly, idx
        return None

    # ── Zoom ──────────────────────────────────────────────────────────────────
    def _on_wheel(self, event):
        factor   = 1.15 if event.delta > 0 else 1 / 1.15
        old_zoom = self._zoom
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        ratio = self._zoom / old_zoom
        self._pan_x = event.x - (event.x - self._pan_x) * ratio
        self._pan_y = event.y - (event.y - self._pan_y) * ratio
        self._clamp_pan()

    # ── Pan (middle button) ───────────────────────────────────────────────────
    def _on_middle_down(self, event):
        self._drag_last_x = event.x
        self._drag_last_y = event.y

    def _on_middle_up(self, _event):
        pass

    def _on_motion(self, event):
        if event.state & 0x0200:   # button 2 held → pan
            dx = event.x - self._drag_last_x
            dy = event.y - self._drag_last_y
            self._drag_last_x = event.x
            self._drag_last_y = event.y
            self._pan_x += dx
            self._pan_y += dy
            self._clamp_pan()
        elif (event.state & 0x0100) and self._uv_drag_vertex is not None:
            poly, idx = self._uv_drag_vertex
            u, v = self._canvas_to_uv(event.x, event.y)
            atlas_w = getattr(self._scene, 'atlas_w', None)
            atlas_h = getattr(self._scene, 'atlas_h', None)
            if atlas_w and atlas_h:
                u = round(u * atlas_w) / atlas_w
                v = round(v * atlas_h) / atlas_h
            elif self._src_img is not None:
                sw, sh = self._src_img.size
                u = round(u * sw) / sw
                v = round(v * sh) / sh
            u = max(0.0, min(1.0, u))
            v = max(0.0, min(1.0, v))
            uvs       = list(poly.uvs)
            uvs[idx]  = (u, v)
            poly.uvs  = uvs
            state = getattr(self._scene, '_state', None)
            if state is not None:
                state.notify_polygon_transformed([poly])

    # ── Left click / UV vertex drag ───────────────────────────────────────────
    def _on_left_down(self, event):
        hit = self._hit_uv_vertex(event.x, event.y)
        if hit is not None:
            poly = hit[0]
            self._uv_drag_vertex = hit
            self._uv_drag_before = {poly: (list(poly.vertices), list(poly.uvs))}
            return
        img_x  = (event.x - self._pan_x) / self._zoom
        img_y  = (event.y - self._pan_y) / self._zoom
        atlas_x = int(img_x * self._scene.atlas_w / self._fit_w)
        atlas_y = int(img_y * self._scene.atlas_h / self._fit_h)
        if self._on_uv_assigned:
            polys  = self._scene._state.selected_polygons if self._scene._state else []
            before = {p: (list(p.vertices), list(p.uvs)) for p in polys}
            self._scene.assign_uv_at_atlas_pixel(atlas_x, atlas_y)
            after  = {p: (list(p.vertices), list(p.uvs)) for p in polys}
            self._on_uv_assigned(before, after)
        else:
            self._scene.assign_uv_at_atlas_pixel(atlas_x, atlas_y)

    def _on_left_up(self, event):
        if self._uv_drag_vertex is not None and self._uv_drag_before is not None:
            poly  = self._uv_drag_vertex[0]
            after = {poly: (list(poly.vertices), list(poly.uvs))}
            if self._on_uv_assigned:
                self._on_uv_assigned(self._uv_drag_before, after)
        self._uv_drag_vertex = None
        self._uv_drag_before = None

    # ── Utility ───────────────────────────────────────────────────────────────
    def _clamp_pan(self):
        sz_w = self._fit_w * self._zoom
        sz_h = self._fit_h * self._zoom
        self._pan_x = max(self._canvas_w * 0.25 - sz_w,
                          min(self._canvas_w * 0.75, self._pan_x))
        self._pan_y = max(self._canvas_h * 0.25 - sz_h,
                          min(self._canvas_h * 0.75, self._pan_y))
