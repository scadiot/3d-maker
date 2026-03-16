"""Composant UV Selector : affiche l'atlas de texture dans le panneau gauche."""

import tkinter as tk
from PIL import Image, ImageTk

from editor.constants import TEXTURE_PATH, PANEL_WIDTH

_ZOOM_MIN = 1.0
_ZOOM_MAX = 8.0
_SRC_MAX  = 1024   # résolution max de l'image source conservée en mémoire


class UVSelector(tk.Frame):
    """Widget intégré dans le panneau gauche pour sélectionner une région UV dans l'atlas."""

    def __init__(self, master, scene, **kw):
        super().__init__(master, bg='#1a1a21', **kw)
        self._scene       = scene
        self._src_img     = None   # image PIL source (ratio préservé)
        self._photo       = None   # PhotoImage courant (évite le GC)
        self._zoom        = 1.0
        self._pan_x       = 0.0
        self._pan_y       = 0.0
        self._drag_last_x = 0
        self._drag_last_y = 0
        self._canvas_w    = PANEL_WIDTH
        self._canvas_h    = PANEL_WIDTH
        # Taille de l'image au zoom=1 (ratio préservé, inscrite dans le canvas)
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
        self._canvas.bind('<Button-1>',        self._on_click)
        self._canvas.bind('<MouseWheel>',      self._on_wheel)
        self._canvas.bind('<Button-2>',        self._on_middle_down)
        self._canvas.bind('<ButtonRelease-2>', self._on_middle_up)
        self._canvas.bind('<Motion>',          self._on_motion)

        self._load_texture()

    # ── Chargement ────────────────────────────────────────────────────────────
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
                text="Texture\nnon trouvée",
                fill='#666680',
                font=('Segoe UI', 9),
                justify='center',
            )

    # ── Calcul du fit (ratio préservé, centré dans le canvas) ─────────────────
    def _compute_fit(self):
        if self._src_img is None:
            return
        src_w, src_h = self._src_img.size
        scale = min(self._canvas_w / src_w, self._canvas_h / src_h)
        self._fit_w = max(1, int(src_w * scale))
        self._fit_h = max(1, int(src_h * scale))
        # Pan initial = image centrée dans le canvas
        self._zoom  = 1.0
        self._pan_x = (self._canvas_w - self._fit_w) / 2
        self._pan_y = (self._canvas_h - self._fit_h) / 2

    # ── Redimensionnement du canvas ───────────────────────────────────────────
    def _on_configure(self, event):
        if event.width == self._canvas_w and event.height == self._canvas_h:
            return
        self._canvas_w = max(1, event.width)
        self._canvas_h = max(1, event.height)
        self._compute_fit()
        self._redraw()

    # ── Rendu ─────────────────────────────────────────────────────────────────
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

    # ── Zoom (molette) ────────────────────────────────────────────────────────
    def _on_wheel(self, event):
        factor   = 1.15 if event.delta > 0 else 1 / 1.15
        old_zoom = self._zoom
        self._zoom = max(_ZOOM_MIN, min(_ZOOM_MAX, self._zoom * factor))
        ratio = self._zoom / old_zoom
        self._pan_x = event.x - (event.x - self._pan_x) * ratio
        self._pan_y = event.y - (event.y - self._pan_y) * ratio
        self._clamp_pan()
        self._redraw()

    # ── Drag (molette maintenue) ──────────────────────────────────────────────
    def _on_middle_down(self, event):
        self._drag_last_x = event.x
        self._drag_last_y = event.y
        self._canvas.config(cursor='fleur')

    def _on_middle_up(self, event):
        self._canvas.config(cursor='crosshair')

    def _on_motion(self, event):
        if not (event.state & 0x0200):   # bouton 2 non enfoncé → rien
            return
        dx = event.x - self._drag_last_x
        dy = event.y - self._drag_last_y
        self._drag_last_x = event.x
        self._drag_last_y = event.y
        self._pan_x += dx
        self._pan_y += dy
        self._clamp_pan()
        self._redraw()

    # ── Clic gauche → assignation UV ─────────────────────────────────────────
    def _on_click(self, event):
        # Coordonnées dans l'espace image fit (zoom=1)
        img_x = (event.x - self._pan_x) / self._zoom
        img_y = (event.y - self._pan_y) / self._zoom
        # Reprojection vers les coordonnées pixel de l'atlas
        atlas_x = int(img_x * self._scene.atlas_w / self._fit_w)
        atlas_y = int(img_y * self._scene.atlas_h / self._fit_h)
        self._scene.assign_uv_at_atlas_pixel(atlas_x, atlas_y)

    # ── Utilitaire ────────────────────────────────────────────────────────────
    def _clamp_pan(self):
        """Empêche l'image de sortir entièrement du canvas."""
        sz_w = self._fit_w * self._zoom
        sz_h = self._fit_h * self._zoom
        self._pan_x = max(self._canvas_w * 0.25 - sz_w,
                          min(self._canvas_w * 0.75, self._pan_x))
        self._pan_y = max(self._canvas_h * 0.25 - sz_h,
                          min(self._canvas_h * 0.75, self._pan_y))
