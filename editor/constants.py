# ── Dimensions ──────────────────────────────────────────────────────────────────
PANEL_WIDTH    = 250
VIEW_WIDTH     = 1280
HEIGHT         = 720
TOTAL_WIDTH    = PANEL_WIDTH + VIEW_WIDTH
FOV            = 60.0
NEAR, FAR      = 0.05, 2000.0

TEXTURE_PATH   = r"C:\Dev\Paris\assets\textures\atlas_1.png"
ATLAS_JSON     = r"C:\Dev\Paris\assets\textures\atlas_1.json"
PREVIEW_MAX_SZ = 512

# ── Caméra ──────────────────────────────────────────────────────────────────────
MOVE_SPEED        = 8.0
MOUSE_SENSITIVITY = 0.15

# ── Gizmo ───────────────────────────────────────────────────────────────────────
GIZMO_MODES = ['translate', 'rotate', 'scale']

GIZMO_AXES = {
    'x': ((1, 0, 0), (1.0,  0.25, 0.25)),
    'y': ((0, 1, 0), (0.25, 1.0,  0.25)),
    'z': ((0, 0, 1), (0.25, 0.5,  1.0)),
}

SCALE_COLORS = {
    'width':   (1.0,  0.55, 0.0),
    'height':  (0.0,  0.80, 0.80),
    'uniform': (0.90, 0.90, 0.90),
}
