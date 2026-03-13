"""
Visionneuse 3D - Grille horizontale
Navigation : ZQSD pour se déplacer, souris pour orienter la caméra, Échap pour quitter
"""

import math
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_ESCAPE, K_z, K_q, K_s, K_d
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_TEST,
    GL_LINES, GL_MODELVIEW, GL_PROJECTION,
    glBegin, glClear, glClearColor, glColor3f, glEnable,
    glEnd, glLoadIdentity, glMatrixMode, glRotatef, glTranslatef, glVertex3f,
    glLineWidth,
)
from OpenGL.GLU import gluPerspective

# ── Fenêtre ────────────────────────────────────────────────────────────────────
WIDTH, HEIGHT = 1280, 720
FOV = 60.0
NEAR, FAR = 0.05, 2000.0

# ── Caméra ─────────────────────────────────────────────────────────────────────
cam_pos   = [0.0, 3.0, 8.0]
cam_yaw   = 0.0     # rotation horizontale (degrés)
cam_pitch = -20.0   # rotation verticale  (degrés)

MOVE_SPEED        = 8.0   # unités/seconde
MOUSE_SENSITIVITY = 0.15  # degrés/pixel


# ── Fonctions caméra ───────────────────────────────────────────────────────────

def forward_xz(yaw: float, pitch: float = 0.0) -> tuple:
    """Vecteur avant dans la direction du regard."""
    yr = math.radians(yaw)
    pr = math.radians(pitch)
    return (
        math.cos(pr) * math.sin(yr),
        math.sin(pr),
        math.cos(pr) * math.cos(yr),
    )


def right_xz(yaw: float) -> tuple:
    """Vecteur droite dans le plan XZ."""
    r = math.radians(yaw)
    return math.cos(r), 0.0, -math.sin(r)


# ── Rendu ──────────────────────────────────────────────────────────────────────

def draw_grid(half_size: int = 30, step: int = 1) -> None:
    """Dessine une grille sur le plan Y=0."""
    glLineWidth(1.0)
    glBegin(GL_LINES)
    for i in range(-half_size, half_size + 1, step):
        if i == 0:
            continue  # axe X et Z dessinés séparément
        glColor3f(0.30, 0.30, 0.35)
        # lignes parallèles à X
        glVertex3f(-half_size, 0, i)
        glVertex3f( half_size, 0, i)
        # lignes parallèles à Z
        glVertex3f(i, 0, -half_size)
        glVertex3f(i, 0,  half_size)
    glEnd()

    # Axe X (rouge) et Z (bleu)
    glLineWidth(2.0)
    glBegin(GL_LINES)
    glColor3f(0.8, 0.2, 0.2)
    glVertex3f(-half_size, 0, 0)
    glVertex3f( half_size, 0, 0)

    glColor3f(0.2, 0.4, 0.9)
    glVertex3f(0, 0, -half_size)
    glVertex3f(0, 0,  half_size)
    glEnd()
    glLineWidth(1.0)


# ── Boucle principale ──────────────────────────────────────────────────────────

def main() -> None:
    global cam_pos, cam_yaw, cam_pitch

    pygame.init()
    pygame.display.set_mode((WIDTH, HEIGHT), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("3D Viewer — ZQSD + souris")

    glEnable(GL_DEPTH_TEST)
    glClearColor(0.08, 0.08, 0.12, 1.0)

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(FOV, WIDTH / HEIGHT, NEAR, FAR)
    glMatrixMode(GL_MODELVIEW)

    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)

    clock = pygame.time.Clock()
    running = True

    while running:
        dt = clock.tick(60) / 1000.0  # secondes

        # ── Événements ────────────────────────────────────────────────────────
        for event in pygame.event.get():
            if event.type == QUIT:
                running = False
            if event.type == KEYDOWN and event.key == K_ESCAPE:
                running = False

        # ── Souris → orientation (bouton molette maintenu) ─────────────────────
        dx, dy = pygame.mouse.get_rel()
        if pygame.mouse.get_pressed()[1]:  # bouton molette (bouton 2)
            cam_yaw   = (cam_yaw   - dx * MOUSE_SENSITIVITY) % 360.0
            cam_pitch = max(-89.0, min(89.0, cam_pitch - dy * MOUSE_SENSITIVITY))

        # ── Clavier → déplacement ─────────────────────────────────────────────
        keys  = pygame.key.get_pressed()
        speed = MOVE_SPEED * dt

        fwd = forward_xz(cam_yaw, cam_pitch)
        rgt = right_xz(cam_yaw)

        if keys[K_z]:  # avant
            cam_pos[0] -= fwd[0] * speed
            cam_pos[1] += fwd[1] * speed
            cam_pos[2] -= fwd[2] * speed
        if keys[K_s]:  # arrière
            cam_pos[0] += fwd[0] * speed
            cam_pos[1] -= fwd[1] * speed
            cam_pos[2] += fwd[2] * speed
        if keys[K_q]:  # gauche
            cam_pos[0] -= rgt[0] * speed
            cam_pos[2] -= rgt[2] * speed
        if keys[K_d]:  # droite
            cam_pos[0] += rgt[0] * speed
            cam_pos[2] += rgt[2] * speed

        # ── Rendu ─────────────────────────────────────────────────────────────
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glLoadIdentity()

        # Applique la caméra : rotation puis translation
        glRotatef(-cam_pitch, 1, 0, 0)
        glRotatef(-cam_yaw,   0, 1, 0)
        glTranslatef(-cam_pos[0], -cam_pos[1], -cam_pos[2])

        draw_grid(30, 1)

        pygame.display.flip()

    pygame.quit()


if __name__ == "__main__":
    main()
