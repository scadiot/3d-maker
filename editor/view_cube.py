"""ViewCube: orientation indicator overlay drawn in the top-right corner of the viewport.

Mirrors the camera's yaw/pitch rotation so the user always knows their orientation.
Clicking a face smoothly animates the camera to the corresponding canonical axis view.
"""

import math

from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f,
    glLineWidth, glEnable, glDisable,
    glMatrixMode, glLoadIdentity, glViewport,
    glPushAttrib, glPopAttrib,
    glPushMatrix, glPopMatrix,
    glRotatef, glScissor, glFrontFace,
    glClear, glOrtho,
    glCullFace,
    GL_MODELVIEW, GL_PROJECTION,
    GL_QUADS, GL_LINES,
    GL_DEPTH_TEST, GL_DEPTH_BUFFER_BIT,
    GL_SCISSOR_TEST,
    GL_ALL_ATTRIB_BITS,
    GL_CULL_FACE, GL_BACK, GL_CCW,
)

# ── Constants ──────────────────────────────────────────────────────────────────

CUBE_SIZE   = 80   # overlay square in pixels
CUBE_MARGIN = 10   # distance from top-right corner
ANIM_SECS   = 0.3  # animation duration for smooth snap

# ── Face data ─────────────────────────────────────────────────────────────────

_H = 0.5  # half-size

# (name, outward_normal, color_rgb, vertices_ccw_from_outside)
# Vertex winding verified: AB × BC = outward normal for each face.
FACES = [
    ('Right',  ( 1,  0,  0), (0.75, 0.25, 0.25),
     [( _H, -_H,  _H), ( _H, -_H, -_H), ( _H,  _H, -_H), ( _H,  _H,  _H)]),
    ('Left',   (-1,  0,  0), (0.55, 0.18, 0.18),
     [(-_H, -_H, -_H), (-_H, -_H,  _H), (-_H,  _H,  _H), (-_H,  _H, -_H)]),
    ('Top',    ( 0,  1,  0), (0.25, 0.75, 0.25),
     [(-_H,  _H,  _H), ( _H,  _H,  _H), ( _H,  _H, -_H), (-_H,  _H, -_H)]),
    ('Bottom', ( 0, -1,  0), (0.18, 0.55, 0.18),
     [(-_H, -_H, -_H), ( _H, -_H, -_H), ( _H, -_H,  _H), (-_H, -_H,  _H)]),
    ('Front',  ( 0,  0, -1), (0.25, 0.45, 0.85),
     [( _H, -_H, -_H), (-_H, -_H, -_H), (-_H,  _H, -_H), ( _H,  _H, -_H)]),
    ('Back',   ( 0,  0,  1), (0.18, 0.30, 0.65),
     [(-_H, -_H,  _H), ( _H, -_H,  _H), ( _H,  _H,  _H), (-_H,  _H,  _H)]),
]

# Camera target (yaw_or_None, pitch) for each face click.
# None = preserve current yaw (used for Top/Bottom to avoid disorienting spin).
FACE_TARGETS = {
    'Top':    (None,   -89.0),
    'Bottom': (None,    89.0),
    'Front':  (180.0,   0.0),
    'Back':   (  0.0,   0.0),
    'Right':  ( 90.0,   0.0),  # camera looks in -X (from right side)
    'Left':   (270.0,   0.0),  # camera looks in +X (from left side)
}

# For ray-plane intersection: (outward_normal_tuple, distance_from_origin)
FACE_PLANES = {
    'Right':  (( 1,  0,  0), 0.5),
    'Left':   ((-1,  0,  0), 0.5),
    'Top':    (( 0,  1,  0), 0.5),
    'Bottom': (( 0, -1,  0), 0.5),
    'Front':  (( 0,  0, -1), 0.5),
    'Back':   (( 0,  0,  1), 0.5),
}

# 8 corners of the unit cube (half-size 0.5)
_CORNERS = [
    (-_H, -_H, -_H), ( _H, -_H, -_H), ( _H,  _H, -_H), (-_H,  _H, -_H),
    (-_H, -_H,  _H), ( _H, -_H,  _H), ( _H,  _H,  _H), (-_H,  _H,  _H),
]
# 12 edges as corner index pairs
_EDGES = [
    (0, 1), (1, 2), (2, 3), (3, 0),   # front face (-Z)
    (4, 5), (5, 6), (6, 7), (7, 4),   # back face (+Z)
    (0, 4), (1, 5), (2, 6), (3, 7),   # connecting edges
]


def _ease_out(t):
    return 1.0 - (1.0 - t) ** 3


# ── ViewCube class ─────────────────────────────────────────────────────────────

class ViewCube:

    def __init__(self):
        self._animating    = False
        self._anim_elapsed = 0.0
        self._yaw_start    = 0.0
        self._pitch_start  = 0.0
        self._yaw_target   = 0.0
        self._pitch_target = 0.0

    # ── Public API ─────────────────────────────────────────────────────────────

    def update(self, camera, dt):
        """Advance the smooth camera-alignment animation (call every frame)."""
        if not self._animating:
            return
        self._anim_elapsed += dt
        t = min(self._anim_elapsed / ANIM_SECS, 1.0)
        t_eased = _ease_out(t)

        camera.yaw   = self._lerp_angle_yaw(self._yaw_start,   self._yaw_target,   t_eased)
        camera.pitch = self._lerp(          self._pitch_start,  self._pitch_target, t_eased)

        if t >= 1.0:
            camera.yaw   = self._yaw_target % 360.0
            camera.pitch = self._pitch_target
            self._animating = False

    def draw(self, camera, vw, vh):
        """Draw the orientation cube overlay in the top-right corner."""
        # Sub-viewport origin in OpenGL coordinates (y-up from bottom-left)
        x0 = vw - CUBE_SIZE - CUBE_MARGIN
        y0 = vh - CUBE_SIZE - CUBE_MARGIN

        # Save all GL state (viewport, matrices, enable bits, etc.)
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        glMatrixMode(GL_PROJECTION); glPushMatrix()
        glMatrixMode(GL_MODELVIEW);  glPushMatrix()

        # Clear only this sub-region's depth buffer using scissor
        glEnable(GL_SCISSOR_TEST)
        glScissor(x0, y0, CUBE_SIZE, CUBE_SIZE)
        glClear(GL_DEPTH_BUFFER_BIT)
        glDisable(GL_SCISSOR_TEST)

        # Set the small sub-viewport
        glViewport(x0, y0, CUBE_SIZE, CUBE_SIZE)

        # Orthographic projection: [-1.5, 1.5] in x/y, z range [-10, 10]
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(-1.5, 1.5, -1.5, 1.5, -10.0, 10.0)

        # Apply only the camera's rotation (no translation — cube stays at origin)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
        glRotatef(-camera.pitch, 1, 0, 0)
        glRotatef(-camera.yaw,   0, 1, 0)

        # Draw with depth test and back-face culling
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glCullFace(GL_BACK)
        glFrontFace(GL_CCW)

        self._draw_faces()
        self._draw_edges()

        # Restore all previously saved state
        glMatrixMode(GL_PROJECTION); glPopMatrix()
        glMatrixMode(GL_MODELVIEW);  glPopMatrix()
        glPopAttrib()

    def hit_test(self, mx, my, vw, vh, camera):
        """Return face name if click (mx, my) is inside the ViewCube, else None.

        mx, my: Tkinter widget coordinates (y=0 at top).
        """
        # Cube region in Tkinter coords (y=0 at top → cube is near top-right)
        x0_tk = vw - CUBE_SIZE - CUBE_MARGIN
        y0_tk = CUBE_MARGIN
        if not (x0_tk <= mx <= x0_tk + CUBE_SIZE and y0_tk <= my <= y0_tk + CUBE_SIZE):
            return None

        # Map click to ortho local coordinates matching the projection [-1.5, 1.5]
        lx = ((mx - x0_tk) / CUBE_SIZE) * 3.0 - 1.5
        ly = ((y0_tk + CUBE_SIZE - my) / CUBE_SIZE) * 3.0 - 1.5  # flip y

        # Orthographic ray in eye space (camera looks down -Z)
        ray_o_eye = (lx, ly, 10.0)   # start from +Z (far end of z range)
        ray_d_eye = (0.0, 0.0, -1.0) # toward -Z (into the screen)

        # Transform ray to cube model space (inverse of glRotatef(-pitch) then glRotatef(-yaw))
        ray_o = self._unrotate(ray_o_eye, camera)
        ray_d = self._unrotate(ray_d_eye, camera)

        return self._pick_face(ray_o, ray_d)

    def snap_to_face(self, face, camera):
        """Start a smooth animation to align the camera with the clicked face."""
        yaw_t, pitch_t = FACE_TARGETS[face]
        if yaw_t is None:
            yaw_t = camera.yaw  # preserve current yaw for top/bottom views
        self._yaw_start    = camera.yaw
        self._pitch_start  = camera.pitch
        self._yaw_target   = yaw_t
        self._pitch_target = pitch_t
        self._anim_elapsed = 0.0
        self._animating    = True

    # ── Drawing ────────────────────────────────────────────────────────────────

    def _draw_faces(self):
        glBegin(GL_QUADS)
        for _name, _normal, (r, g, b), verts in FACES:
            glColor3f(r, g, b)
            for v in verts:
                glVertex3f(*v)
        glEnd()

    def _draw_edges(self):
        glLineWidth(1.5)
        glColor3f(0.05, 0.05, 0.05)
        glBegin(GL_LINES)
        for a, b in _EDGES:
            glVertex3f(*_CORNERS[a])
            glVertex3f(*_CORNERS[b])
        glEnd()
        glLineWidth(1.0)

    # ── Hit-testing ────────────────────────────────────────────────────────────

    def _unrotate(self, v, camera):
        """Transform a vector from eye space to cube model space.

        Inverse of: Rx(-pitch) * Ry(-yaw)  (the OpenGL modelview transform).
        = Ry(yaw) * Rx(pitch) applied to v: first Rx(pitch), then Ry(yaw).
        """
        pr = math.radians(camera.pitch)
        cp, sp = math.cos(pr), math.sin(pr)
        x1 = v[0]
        y1 =  v[1] * cp - v[2] * sp
        z1 =  v[1] * sp + v[2] * cp

        yr = math.radians(camera.yaw)
        cy, sy = math.cos(yr), math.sin(yr)
        x2 =  x1 * cy + z1 * sy
        y2 =  y1
        z2 = -x1 * sy + z1 * cy
        return (x2, y2, z2)

    def _pick_face(self, ray_o, ray_d):
        """Return the name of the closest unit-cube face hit by the ray, or None."""
        best_t, best_face = float('inf'), None
        for name, (n, dist) in FACE_PLANES.items():
            denom = n[0] * ray_d[0] + n[1] * ray_d[1] + n[2] * ray_d[2]
            if abs(denom) < 1e-7:
                continue
            t = (dist - (n[0] * ray_o[0] + n[1] * ray_o[1] + n[2] * ray_o[2])) / denom
            if t < 0:
                continue
            hx = ray_o[0] + t * ray_d[0]
            hy = ray_o[1] + t * ray_d[1]
            hz = ray_o[2] + t * ray_d[2]
            # Verify hit point lies within the face (±0.5 on the two non-normal axes)
            if all(abs((hx, hy, hz)[i]) <= 0.5 + 1e-5 for i in range(3) if n[i] == 0):
                if t < best_t:
                    best_t, best_face = t, name
        return best_face

    # ── Animation helpers ──────────────────────────────────────────────────────

    def _lerp(self, a, b, t):
        return a + (b - a) * t

    def _lerp_angle_yaw(self, start, target, t):
        """Lerp yaw taking the shortest arc around the 0°/360° boundary."""
        delta = (target - start) % 360.0
        if delta > 180.0:
            delta -= 360.0
        return (start + delta * t) % 360.0
