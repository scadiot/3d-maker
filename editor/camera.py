"""Classe Camera : état et helpers de projection/rayon."""

import math
from pygame.locals import K_z, K_q, K_s, K_d

from editor.constants import VIEW_WIDTH, HEIGHT, FOV, MOVE_SPEED, MOUSE_SENSITIVITY
from editor import math3d


class Camera:
    def __init__(self):
        self.pos   = [0.0, 3.0, 8.0]
        self.yaw   = 0.0
        self.pitch = -20.0

    # ── Directions ────────────────────────────────────────────────────────────
    def forward_xz(self):
        """Direction avant tenant compte du pitch."""
        yr, pr = math.radians(self.yaw), math.radians(self.pitch)
        return (math.cos(pr)*math.sin(yr), math.sin(pr), math.cos(pr)*math.cos(yr))

    def right_xz(self):
        r = math.radians(self.yaw)
        return (math.cos(r), 0.0, -math.sin(r))

    # ── Projection ────────────────────────────────────────────────────────────
    def world_to_screen(self, wx, wy, wz):
        """Projette un point monde en coordonnées viewport. Retourne (px, py) ou None."""
        tx, ty, tz = wx - self.pos[0], wy - self.pos[1], wz - self.pos[2]
        yr = math.radians(self.yaw);  cy, sy = math.cos(yr), math.sin(yr)
        cx2 = tx*cy - tz*sy;  cy2 = ty;  cz2 = tx*sy + tz*cy
        pr = math.radians(self.pitch);  cp, sp = math.cos(pr), math.sin(pr)
        cx3 = cx2;  cy3 = cy2*cp + cz2*sp;  cz3 = -cy2*sp + cz2*cp
        if cz3 >= -1e-4: return None
        aspect = VIEW_WIDTH / HEIGHT;  t = math.tan(math.radians(FOV / 2))
        return ((cx3/(-cz3*aspect*t)+1)/2*VIEW_WIDTH, (1 - cy3/(-cz3*t))/2*HEIGHT)

    def screen_ray(self, vx, vy):
        """Rayon depuis un pixel viewport (vx = mx - PANEL_WIDTH). Retourne la direction normalisée."""
        aspect = VIEW_WIDTH / HEIGHT;  t = math.tan(math.radians(FOV / 2))
        rcx = ((2*vx/VIEW_WIDTH) - 1) * aspect * t
        rcy = (1 - (2*vy/HEIGHT)) * t;  rcz = -1.0
        rcx, rcy, rcz = math3d.normalize((rcx, rcy, rcz))
        pr = math.radians(self.pitch);  cp, sp = math.cos(pr), math.sin(pr)
        rx1 = rcx;  ry1 = rcy*cp - rcz*sp;  rz1 = rcy*sp + rcz*cp
        yr = math.radians(self.yaw);  cy, sy = math.cos(yr), math.sin(yr)
        return math3d.normalize((rx1*cy + rz1*sy, ry1, -rx1*sy + rz1*cy))

    # ── Entrées ───────────────────────────────────────────────────────────────
    def apply_movement(self, keys, dt):
        speed = MOVE_SPEED * dt
        fwd, rgt = self.forward_xz(), self.right_xz()
        if keys[K_z]: self.pos[0] -= fwd[0]*speed; self.pos[1] += fwd[1]*speed; self.pos[2] -= fwd[2]*speed
        if keys[K_s]: self.pos[0] += fwd[0]*speed; self.pos[1] -= fwd[1]*speed; self.pos[2] += fwd[2]*speed
        if keys[K_q]: self.pos[0] -= rgt[0]*speed; self.pos[2] -= rgt[2]*speed
        if keys[K_d]: self.pos[0] += rgt[0]*speed; self.pos[2] += rgt[2]*speed

    def apply_mouse_look(self, dx, dy):
        self.yaw   = (self.yaw   - dx * MOUSE_SENSITIVITY) % 360.0
        self.pitch = max(-89.0, min(89.0, self.pitch - dy * MOUSE_SENSITIVITY))
