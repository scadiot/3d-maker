"""
Visionneuse 3D
Navigation : ZQSD pour se déplacer, molette maintenue pour orienter, Échap pour quitter
"""

import math
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_ESCAPE, K_z, K_q, K_s, K_d
from OpenGL.GL import *
from OpenGL.GLU import gluPerspective

# ── Dimensions ─────────────────────────────────────────────────────────────────
PANEL_WIDTH = 250
VIEW_WIDTH  = 1280
HEIGHT      = 720
TOTAL_WIDTH = PANEL_WIDTH + VIEW_WIDTH
FOV         = 60.0
NEAR, FAR   = 0.05, 2000.0

# ── Caméra ─────────────────────────────────────────────────────────────────────
cam_pos   = [0.0, 3.0, 8.0]
cam_yaw   = 0.0
cam_pitch = -20.0
MOVE_SPEED        = 8.0
MOUSE_SENSITIVITY = 0.15

# ── Monde ──────────────────────────────────────────────────────────────────────
quads = []  # liste de quads : chaque élément = liste de 4 tuples (x,y,z)

# ── Sélection / gizmo ──────────────────────────────────────────────────────────
selected_quad_idx = -1
dragging_axis     = None   # 'x', 'y', 'z' ou None
drag_start_verts  = None
drag_axis_t0      = 0.0

# ── Vec3 ───────────────────────────────────────────────────────────────────────
def vadd(a, b):   return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def vsub(a, b):   return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def vscale(a, s): return (a[0]*s, a[1]*s, a[2]*s)
def dot(a, b):    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def cross(a, b):  return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def vlength(a):   return math.sqrt(dot(a, a))
def normalize(a):
    l = vlength(a)
    return (a[0]/l, a[1]/l, a[2]/l) if l > 1e-10 else (0.0, 0.0, 0.0)

# ── Caméra helpers ─────────────────────────────────────────────────────────────
def forward_xz(yaw, pitch=0.0):
    yr, pr = math.radians(yaw), math.radians(pitch)
    return (math.cos(pr)*math.sin(yr), math.sin(pr), math.cos(pr)*math.cos(yr))

def right_xz(yaw):
    r = math.radians(yaw)
    return (math.cos(r), 0.0, -math.sin(r))

def world_to_screen(wx, wy, wz):
    """Point monde → coordonnées écran (px,py) relatives au viewport 3D, ou None si derrière."""
    tx, ty, tz = wx-cam_pos[0], wy-cam_pos[1], wz-cam_pos[2]
    yr = math.radians(cam_yaw)
    cy, sy = math.cos(yr), math.sin(yr)
    cx2 = tx*cy - tz*sy;  cy2 = ty;  cz2 = tx*sy + tz*cy
    pr = math.radians(cam_pitch)
    cp, sp = math.cos(pr), math.sin(pr)
    cx3 = cx2;  cy3 = cy2*cp + cz2*sp;  cz3 = -cy2*sp + cz2*cp
    if cz3 >= -1e-4:
        return None
    aspect = VIEW_WIDTH / HEIGHT
    t = math.tan(math.radians(FOV / 2))
    ndcx = cx3 / (-cz3 * aspect * t)
    ndcy = cy3 / (-cz3 * t)
    return ((ndcx+1)/2*VIEW_WIDTH, (1-ndcy)/2*HEIGHT)

def screen_ray(px, py):
    """Pixel (relatif viewport 3D) → direction rayon monde."""
    aspect = VIEW_WIDTH / HEIGHT
    t = math.tan(math.radians(FOV / 2))
    rcx = ((2*px/VIEW_WIDTH)-1) * aspect * t
    rcy = (1-(2*py/HEIGHT)) * t
    rcz = -1.0
    rcx, rcy, rcz = normalize((rcx, rcy, rcz))
    pr = math.radians(cam_pitch)
    cp, sp = math.cos(pr), math.sin(pr)
    rx1 = rcx;  ry1 = rcy*cp - rcz*sp;  rz1 = rcy*sp + rcz*cp
    yr = math.radians(cam_yaw)
    cy, sy = math.cos(yr), math.sin(yr)
    return normalize((rx1*cy+rz1*sy, ry1, -rx1*sy+rz1*cy))

# ── Intersection ───────────────────────────────────────────────────────────────
def ray_triangle(orig, dir, v0, v1, v2):
    EPS = 1e-7
    e1, e2 = vsub(v1,v0), vsub(v2,v0)
    h = cross(dir, e2);  a = dot(e1, h)
    if -EPS < a < EPS: return None
    f = 1.0/a;  s = vsub(orig, v0);  u = f*dot(s, h)
    if u < 0 or u > 1: return None
    q = cross(s, e1);  v = f*dot(dir, q)
    if v < 0 or u+v > 1: return None
    t = f*dot(e2, q)
    return t if t > EPS else None

def ray_quad_intersect(orig, dir, quad):
    v = [tuple(x) for x in quad]
    hits = [t for t in (ray_triangle(orig,dir,v[0],v[1],v[2]),
                        ray_triangle(orig,dir,v[0],v[2],v[3])) if t is not None]
    return min(hits) if hits else None

def ray_line_closest_s(ray_o, ray_d, line_o, line_d):
    """Retourne s : line_o + s*line_d est le point de la droite le plus proche du rayon."""
    w = vsub(ray_o, line_o)
    a, b, c = dot(ray_d,ray_d), dot(ray_d,line_d), dot(line_d,line_d)
    d, e = dot(ray_d,w), dot(line_d,w)
    denom = a*c - b*b
    return (a*e - b*d)/denom if abs(denom) > 1e-10 else 0.0

def seg_dist_2d(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay
    len2 = dx*dx+dy*dy
    if len2 < 1e-10: return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/len2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

# ── Gizmo ──────────────────────────────────────────────────────────────────────
GIZMO_AXES = {
    'x': ((1,0,0), (1.0, 0.25, 0.25)),
    'y': ((0,1,0), (0.25, 1.0, 0.25)),
    'z': ((0,0,1), (0.25, 0.5,  1.0)),
}

def quad_center(quad):
    return (sum(v[0] for v in quad)/4, sum(v[1] for v in quad)/4, sum(v[2] for v in quad)/4)

def gizmo_scale(center):
    return max(0.5, vlength(vsub(tuple(cam_pos), center)) * 0.2)

def perp_basis(axis):
    ref = (1,0,0) if abs(axis[0]) < 0.9 else (0,1,0)
    u = normalize(cross(axis, ref))
    return u, normalize(cross(axis, u))

def draw_arrow_3d(start, tip, color, selected=False):
    r, g, b = (1.0, 0.9, 0.1) if selected else color
    length = vlength(vsub(tip, start))
    if length < 1e-10: return
    axis = normalize(vsub(tip, start))
    cone_base = vadd(start, vscale(axis, length*0.78))
    cone_r = length * 0.08
    u, v = perp_basis(axis)
    N = 10
    glColor3f(r, g, b)
    glLineWidth(2.5 if selected else 2.0)
    glBegin(GL_LINES)
    glVertex3f(*start); glVertex3f(*cone_base)
    glEnd()
    glLineWidth(1.0)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(*tip)
    for i in range(N+1):
        a = 2*math.pi*i/N
        p = vadd(cone_base, vadd(vscale(u, cone_r*math.cos(a)), vscale(v, cone_r*math.sin(a))))
        glVertex3f(*p)
    glEnd()

def draw_gizmo(center, active_axis=None):
    scale = gizmo_scale(center)
    glDisable(GL_DEPTH_TEST)
    for name, (axis_dir, color) in GIZMO_AXES.items():
        draw_arrow_3d(center, vadd(center, vscale(axis_dir, scale)), color, name==active_axis)
    glEnable(GL_DEPTH_TEST)

def pick_gizmo_axis(mx, my):
    if selected_quad_idx < 0: return None
    center = quad_center(quads[selected_quad_idx])
    scale  = gizmo_scale(center)
    vx, vy = mx - PANEL_WIDTH, my
    best, best_d = None, 10.0
    for name, (axis_dir, _) in GIZMO_AXES.items():
        p0 = world_to_screen(*center)
        p1 = world_to_screen(*vadd(center, vscale(axis_dir, scale)))
        if p0 and p1:
            d = seg_dist_2d(vx, vy, p0[0], p0[1], p1[0], p1[1])
            if d < best_d: best_d, best = d, name
    return best

# ── Quads ──────────────────────────────────────────────────────────────────────
def add_vertical_quad():
    yr = math.radians(cam_yaw)
    fx, fz =  math.sin(yr),  math.cos(yr)
    rx, rz =  math.cos(yr), -math.sin(yr)
    cx, cz = cam_pos[0]+fx*5, cam_pos[2]+fz*5
    quads.append([
        (cx-rx, 0.0, cz-rz), (cx+rx, 0.0, cz+rz),
        (cx+rx, 2.0, cz+rz), (cx-rx, 2.0, cz-rz),
    ])

def draw_quads():
    for i, quad in enumerate(quads):
        sel = (i == selected_quad_idx)
        glColor3f(0.85, 0.55, 0.20)
        glBegin(GL_QUADS)
        for vx, vy, vz in quad: glVertex3f(vx, vy, vz)
        glEnd()
        glLineWidth(2.5 if sel else 1.5)
        if sel:
            glColor3f(1.0, 0.15, 0.15)
        else:
            glColor3f(1.0, 0.75, 0.35)
        glBegin(GL_LINE_LOOP)
        for vx, vy, vz in quad: glVertex3f(vx, vy, vz)
        glEnd()
    glLineWidth(1.0)

# ── Drag ───────────────────────────────────────────────────────────────────────
def start_drag(axis, mx, my):
    global dragging_axis, drag_start_verts, drag_axis_t0
    dragging_axis    = axis
    drag_start_verts = list(quads[selected_quad_idx])
    center   = quad_center(drag_start_verts)
    axis_dir = GIZMO_AXES[axis][0]
    drag_axis_t0 = ray_line_closest_s(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my), center, axis_dir)

def update_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    center   = quad_center(drag_start_verts)
    axis_dir = GIZMO_AXES[dragging_axis][0]
    t = ray_line_closest_s(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my), center, axis_dir)
    move = vscale(axis_dir, t - drag_axis_t0)
    quads[selected_quad_idx] = [vadd(v, move) for v in drag_start_verts]

# ── Grille ─────────────────────────────────────────────────────────────────────
def draw_grid(half_size=30, step=1):
    glLineWidth(1.0)
    glBegin(GL_LINES)
    for i in range(-half_size, half_size+1, step):
        if i == 0: continue
        glColor3f(0.30, 0.30, 0.35)
        glVertex3f(-half_size,0,i); glVertex3f(half_size,0,i)
        glVertex3f(i,0,-half_size); glVertex3f(i,0,half_size)
    glEnd()
    glLineWidth(2.0)
    glBegin(GL_LINES)
    glColor3f(0.8,0.2,0.2); glVertex3f(-half_size,0,0); glVertex3f(half_size,0,0)
    glColor3f(0.2,0.4,0.9); glVertex3f(0,0,-half_size); glVertex3f(0,0,half_size)
    glEnd()
    glLineWidth(1.0)

# ── UI 2D ──────────────────────────────────────────────────────────────────────
def make_text_texture(font, text, color=(255,255,255)):
    surf = font.render(text, True, color)
    w, h = surf.get_size()
    data = pygame.image.tobytes(surf, "RGBA", True)
    tex  = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tex)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glBindTexture(GL_TEXTURE_2D, 0)
    return tex, w, h

def begin_2d():
    glViewport(0, 0, TOTAL_WIDTH, HEIGHT)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, TOTAL_WIDTH, HEIGHT, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glDisable(GL_DEPTH_TEST)

def end_2d():
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW);  glPopMatrix()
    glEnable(GL_DEPTH_TEST)

def draw_rect(x, y, w, h, r, g, b):
    glColor3f(r, g, b)
    glBegin(GL_QUADS)
    glVertex2f(x,y); glVertex2f(x+w,y); glVertex2f(x+w,y+h); glVertex2f(x,y+h)
    glEnd()

def draw_texture(tex_id, x, y, w, h):
    glEnable(GL_TEXTURE_2D); glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glBindTexture(GL_TEXTURE_2D, tex_id); glColor3f(1,1,1)
    glBegin(GL_QUADS)
    glTexCoord2f(0,1); glVertex2f(x,   y)
    glTexCoord2f(1,1); glVertex2f(x+w, y)
    glTexCoord2f(1,0); glVertex2f(x+w, y+h)
    glTexCoord2f(0,0); glVertex2f(x,   y+h)
    glEnd()
    glDisable(GL_TEXTURE_2D); glDisable(GL_BLEND)

BTN = {"x": 15, "y": 15, "w": 220, "h": 36}

def draw_panel(btn_hovered, btn_tex, btn_tex_w, btn_tex_h):
    draw_rect(0, 0, PANEL_WIDTH, HEIGHT, 0.10, 0.10, 0.13)
    draw_rect(PANEL_WIDTH-1, 0, 1, HEIGHT, 0.22, 0.22, 0.28)
    b = BTN
    if btn_hovered:
        draw_rect(b["x"], b["y"], b["w"], b["h"], 0.35, 0.55, 0.85)
    else:
        draw_rect(b["x"], b["y"], b["w"], b["h"], 0.22, 0.40, 0.70)
    draw_texture(btn_tex, b["x"]+(b["w"]-btn_tex_w)//2, b["y"]+(b["h"]-btn_tex_h)//2, btn_tex_w, btn_tex_h)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    global cam_pos, cam_yaw, cam_pitch
    global selected_quad_idx, dragging_axis, drag_start_verts, drag_axis_t0

    pygame.init()
    pygame.display.set_mode((TOTAL_WIDTH, HEIGHT), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("3D Viewer")
    glEnable(GL_DEPTH_TEST)
    glClearColor(0.08, 0.08, 0.12, 1.0)

    font = pygame.font.SysFont("segoeui", 15)
    btn_tex, btn_tex_w, btn_tex_h = make_text_texture(font, "add vertical quad")

    clock   = pygame.time.Clock()
    running = True

    while running:
        dt = clock.tick(60) / 1000.0
        mx, my = pygame.mouse.get_pos()
        in_3d  = mx >= PANEL_WIDTH
        btn_hovered = (BTN["x"] <= mx <= BTN["x"]+BTN["w"] and BTN["y"] <= my <= BTN["y"]+BTN["h"])

        for event in pygame.event.get():
            if event.type == QUIT: running = False
            if event.type == KEYDOWN and event.key == K_ESCAPE: running = False

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if btn_hovered:
                    add_vertical_quad()
                elif in_3d:
                    axis = pick_gizmo_axis(mx, my)
                    if axis:
                        start_drag(axis, mx, my)
                    else:
                        ray_o = tuple(cam_pos)
                        ray_d = screen_ray(mx-PANEL_WIDTH, my)
                        best_t, best_i = float('inf'), -1
                        for i, q in enumerate(quads):
                            t = ray_quad_intersect(ray_o, ray_d, q)
                            if t is not None and t < best_t:
                                best_t, best_i = t, i
                        selected_quad_idx = best_i

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_axis = None
                drag_start_verts = None

        if dragging_axis and pygame.mouse.get_pressed()[0]:
            update_drag(mx, my)

        dx, dy = pygame.mouse.get_rel()
        if pygame.mouse.get_pressed()[1] and in_3d:
            cam_yaw   = (cam_yaw   - dx * MOUSE_SENSITIVITY) % 360.0
            cam_pitch = max(-89.0, min(89.0, cam_pitch - dy * MOUSE_SENSITIVITY))

        keys  = pygame.key.get_pressed()
        speed = MOVE_SPEED * dt
        fwd, rgt = forward_xz(cam_yaw, cam_pitch), right_xz(cam_yaw)
        if keys[K_z]: cam_pos[0]-=fwd[0]*speed; cam_pos[1]+=fwd[1]*speed; cam_pos[2]-=fwd[2]*speed
        if keys[K_s]: cam_pos[0]+=fwd[0]*speed; cam_pos[1]-=fwd[1]*speed; cam_pos[2]+=fwd[2]*speed
        if keys[K_q]: cam_pos[0]-=rgt[0]*speed; cam_pos[2]-=rgt[2]*speed
        if keys[K_d]: cam_pos[0]+=rgt[0]*speed; cam_pos[2]+=rgt[2]*speed

        # ── Rendu 3D ──────────────────────────────────────────────────────────
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glViewport(PANEL_WIDTH, 0, VIEW_WIDTH, HEIGHT)
        glMatrixMode(GL_PROJECTION); glLoadIdentity()
        gluPerspective(FOV, VIEW_WIDTH/HEIGHT, NEAR, FAR)
        glMatrixMode(GL_MODELVIEW); glLoadIdentity()
        glRotatef(-cam_pitch, 1, 0, 0)
        glRotatef(-cam_yaw,   0, 1, 0)
        glTranslatef(-cam_pos[0], -cam_pos[1], -cam_pos[2])

        draw_grid(30, 1)
        draw_quads()
        if selected_quad_idx >= 0:
            draw_gizmo(quad_center(quads[selected_quad_idx]), dragging_axis)

        # ── Rendu 2D ──────────────────────────────────────────────────────────
        begin_2d()
        draw_panel(btn_hovered, btn_tex, btn_tex_w, btn_tex_h)
        end_2d()

        pygame.display.flip()

    glDeleteTextures(1, [btn_tex])
    pygame.quit()


if __name__ == "__main__":
    main()
