"""Fonctions de rendu OpenGL/2D stateless (grille, helpers UI)."""

from OpenGL.GL import (
    glBegin, glEnd, glVertex3f, glVertex2f, glColor3f, glLineWidth,
    glTexCoord2f, glBindTexture, glEnable, glDisable,
    glMatrixMode, glPushMatrix, glPopMatrix, glLoadIdentity, glOrtho,
    glViewport,
    GL_LINES, GL_QUADS, GL_TEXTURE_2D, GL_BLEND, GL_DEPTH_TEST,
    GL_PROJECTION, GL_MODELVIEW, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
)
from OpenGL.GL import glBlendFunc

from editor.constants import TOTAL_WIDTH, HEIGHT


# ── Grille ────────────────────────────────────────────────────────────────────
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


# ── Mode 2D ───────────────────────────────────────────────────────────────────
def begin_2d():
    glViewport(0, 0, TOTAL_WIDTH, HEIGHT)
    glMatrixMode(GL_PROJECTION);  glPushMatrix();  glLoadIdentity()
    glOrtho(0, TOTAL_WIDTH, HEIGHT, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW);  glPushMatrix();  glLoadIdentity()
    glDisable(GL_DEPTH_TEST)

def end_2d():
    glMatrixMode(GL_PROJECTION);  glPopMatrix()
    glMatrixMode(GL_MODELVIEW);   glPopMatrix()
    glEnable(GL_DEPTH_TEST)


# ── Primitives 2D ─────────────────────────────────────────────────────────────
def draw_rect(x, y, w, h, r, g, b):
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    glVertex2f(x, y); glVertex2f(x+w, y); glVertex2f(x+w, y+h); glVertex2f(x, y+h)
    glEnd()

def draw_texture(tex_id, x, y, w, h):
    glEnable(GL_TEXTURE_2D);  glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glBindTexture(GL_TEXTURE_2D, tex_id);  glColor3f(1, 1, 1)
    glBegin(GL_QUADS)
    glTexCoord2f(0, 1); glVertex2f(x, y);    glTexCoord2f(1, 1); glVertex2f(x+w, y)
    glTexCoord2f(1, 0); glVertex2f(x+w, y+h); glTexCoord2f(0, 0); glVertex2f(x, y+h)
    glEnd()
    glDisable(GL_TEXTURE_2D);  glDisable(GL_BLEND)
