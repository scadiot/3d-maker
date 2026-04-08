"""Stateless OpenGL rendering functions (grid)."""

from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glColor3f, glLineWidth,
    GL_LINES,
)


# ── Grid ──────────────────────────────────────────────────────────────────────
def draw_grid(half_size=30, step=1, plane='Y', offset=0.0):
    o = offset
    glLineWidth(1.0)
    glBegin(GL_LINES)
    glColor3f(0.30, 0.30, 0.35)
    for i in range(-half_size, half_size + 1, step):
        if i == 0:
            continue
        if plane == 'Y':
            glVertex3f(-half_size, o, i);  glVertex3f(half_size, o, i)
            glVertex3f(i, o, -half_size);  glVertex3f(i, o, half_size)
        elif plane == 'X':
            glVertex3f(o, -half_size, i);  glVertex3f(o, half_size, i)
            glVertex3f(o, i, -half_size);  glVertex3f(o, i, half_size)
        elif plane == 'Z':
            glVertex3f(-half_size, i, o);  glVertex3f(half_size, i, o)
            glVertex3f(i, -half_size, o);  glVertex3f(i, half_size, o)
    glEnd()

    glLineWidth(2.0)
    glBegin(GL_LINES)
    if plane == 'Y':
        glColor3f(0.8, 0.2, 0.2); glVertex3f(-half_size, o, 0); glVertex3f(half_size, o, 0)
        glColor3f(0.2, 0.4, 0.9); glVertex3f(0, o, -half_size); glVertex3f(0, o, half_size)
    elif plane == 'X':
        glColor3f(0.2, 0.7, 0.2); glVertex3f(o, -half_size, 0); glVertex3f(o, half_size, 0)
        glColor3f(0.2, 0.4, 0.9); glVertex3f(o, 0, -half_size); glVertex3f(o, 0, half_size)
    elif plane == 'Z':
        glColor3f(0.8, 0.2, 0.2); glVertex3f(-half_size, 0, o); glVertex3f(half_size, 0, o)
        glColor3f(0.2, 0.7, 0.2); glVertex3f(0, -half_size, o); glVertex3f(0, half_size, o)
    glEnd()
    glLineWidth(1.0)
