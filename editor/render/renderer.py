"""Stateless OpenGL rendering functions (grid)."""

from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
    GL_LINES,
)


# ── Grid ──────────────────────────────────────────────────────────────────────
def draw_grid(half_size=30, step=1):
    glLineWidth(1.0)
    glBegin(GL_LINES)
    for i in range(-half_size, half_size+1, step):
        if i == 0: continue
        glColor3f(0.30, 0.30, 0.35)
        glVertex3f(-half_size, 0, i); glVertex3f(half_size, 0, i)
        glVertex3f(i, 0, -half_size); glVertex3f(i, 0, half_size)
    glEnd()
    glLineWidth(2.0)
    glBegin(GL_LINES)
    glColor3f(0.8, 0.2, 0.2); glVertex3f(-half_size, 0, 0); glVertex3f(half_size, 0, 0)
    glColor3f(0.2, 0.4, 0.9); glVertex3f(0, 0, -half_size); glVertex3f(0, 0, half_size)
    glEnd();  glLineWidth(1.0)
