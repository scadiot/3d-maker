"""Camera class: state and projection/ray helpers."""

import math

from editor.constants import VIEW_WIDTH, HEIGHT, FOV, MOVE_SPEED, MOUSE_SENSITIVITY
from editor import math3d


class Camera:
    def __init__(self):
        self.pos   = [0.0, 3.0, 8.0]
        self.yaw   = 0.0
        self.pitch = -20.0
        self.vw    = VIEW_WIDTH
        self.vh    = HEIGHT

    # ── Directions ────────────────────────────────────────────────────────────
    def forward_xz(self):
        """Forward direction taking pitch into account."""
        yr, pr = math.radians(self.yaw), math.radians(self.pitch)
        return (math.cos(pr)*math.sin(yr), math.sin(pr), math.cos(pr)*math.cos(yr))

    def right_xz(self):
        r = math.radians(self.yaw)
        return (math.cos(r), 0.0, -math.sin(r))

    def up_vector(self):
        """Camera local up direction in world space."""
        yr, pr = math.radians(self.yaw), math.radians(self.pitch)
        return (math.sin(pr)*math.sin(yr), math.cos(pr), math.sin(pr)*math.cos(yr))

    # ── Projection ────────────────────────────────────────────────────────────
    def world_to_screen(self, wx, wy, wz):
        """Projects a world point to viewport coordinates. Returns (px, py) or None."""
        tx, ty, tz = wx - self.pos[0], wy - self.pos[1], wz - self.pos[2]
        yr = math.radians(self.yaw);  cy, sy = math.cos(yr), math.sin(yr)
        cx2 = tx*cy - tz*sy;  cy2 = ty;  cz2 = tx*sy + tz*cy
        pr = math.radians(self.pitch);  cp, sp = math.cos(pr), math.sin(pr)
        cx3 = cx2;  cy3 = cy2*cp + cz2*sp;  cz3 = -cy2*sp + cz2*cp
        if cz3 >= -1e-4: return None
        aspect = self.vw / self.vh;  t = math.tan(math.radians(FOV / 2))
        return ((cx3/(-cz3*aspect*t)+1)/2*self.vw, (1 - cy3/(-cz3*t))/2*self.vh)

    def screen_ray(self, vx, vy):
        """Ray from a viewport pixel. Returns the normalized direction."""
        aspect = self.vw / self.vh;  t = math.tan(math.radians(FOV / 2))
        rcx = ((2*vx/self.vw) - 1) * aspect * t
        rcy = (1 - (2*vy/self.vh)) * t;  rcz = -1.0
        rcx, rcy, rcz = math3d.normalize((rcx, rcy, rcz))
        pr = math.radians(self.pitch);  cp, sp = math.cos(pr), math.sin(pr)
        rx1 = rcx;  ry1 = rcy*cp - rcz*sp;  rz1 = rcy*sp + rcz*cp
        yr = math.radians(self.yaw);  cy, sy = math.cos(yr), math.sin(yr)
        return math3d.normalize((rx1*cy + rz1*sy, ry1, -rx1*sy + rz1*cy))

    # ── Input ─────────────────────────────────────────────────────────────────
    def apply_movement(self, keys, dt, panning=False):
        """keys: set of lowercase Tkinter keysyms (e.g. {'z', 'd'}).
        panning: when True, Z/S move forward/backward; otherwise Z/S move vertically."""
        speed = MOVE_SPEED * dt
        fwd, rgt = self.forward_xz(), self.right_xz()
        if panning:
            if 'z' in keys: self.pos[0] -= fwd[0]*speed; self.pos[1] += fwd[1]*speed; self.pos[2] -= fwd[2]*speed
            if 's' in keys: self.pos[0] += fwd[0]*speed; self.pos[1] -= fwd[1]*speed; self.pos[2] += fwd[2]*speed
        else:
            up = self.up_vector()
            if 'z' in keys: self.pos[0] += up[0]*speed; self.pos[1] += up[1]*speed; self.pos[2] += up[2]*speed
            if 's' in keys: self.pos[0] -= up[0]*speed; self.pos[1] -= up[1]*speed; self.pos[2] -= up[2]*speed
        if 'q' in keys: self.pos[0] -= rgt[0]*speed; self.pos[2] -= rgt[2]*speed
        if 'd' in keys: self.pos[0] += rgt[0]*speed; self.pos[2] += rgt[2]*speed

    def apply_mouse_look(self, dx, dy):
        self.yaw   = (self.yaw   - dx * MOUSE_SENSITIVITY) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch - dy * MOUSE_SENSITIVITY))

    def apply_scroll(self, delta):
        """Moves the camera forward/backward based on mouse wheel scroll."""
        fwd = self.forward_xz()
        speed = MOVE_SPEED * 0.1 * delta
        self.pos[0] -= fwd[0] * speed
        self.pos[1] += fwd[1] * speed
        self.pos[2] -= fwd[2] * speed
