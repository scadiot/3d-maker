"""
Visionneuse 3D
Navigation : ZQSD déplacer, molette orienter, Espace alterner translation/rotation, Échap quitter
"""

import math
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_ESCAPE, K_z, K_q, K_s, K_d, K_SPACE
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
quads = []

# ── Sélection / gizmo ──────────────────────────────────────────────────────────
selected_quad_idx  = -1
gizmo_mode         = 'translate'   # 'translate' | 'rotate'
dragging_axis      = None
drag_start_verts   = None
drag_axis_t0       = 0.0           # translation : paramètre axe au départ
drag_angle0        = 0.0           # rotation : angle au départ
drag_plane_u       = None          # rotation : base de plan
drag_plane_v       = None
drag_center        = None          # rotation : centre au départ

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
    tx, ty, tz = wx-cam_pos[0], wy-cam_pos[1], wz-cam_pos[2]
    yr = math.radians(cam_yaw);  cy, sy = math.cos(yr), math.sin(yr)
    cx2 = tx*cy - tz*sy;  cy2 = ty;  cz2 = tx*sy + tz*cy
    pr = math.radians(cam_pitch);  cp, sp = math.cos(pr), math.sin(pr)
    cx3 = cx2;  cy3 = cy2*cp + cz2*sp;  cz3 = -cy2*sp + cz2*cp
    if cz3 >= -1e-4: return None
    aspect = VIEW_WIDTH / HEIGHT;  t = math.tan(math.radians(FOV/2))
    ndcx = cx3/(-cz3*aspect*t);  ndcy = cy3/(-cz3*t)
    return ((ndcx+1)/2*VIEW_WIDTH, (1-ndcy)/2*HEIGHT)

def screen_ray(px, py):
    aspect = VIEW_WIDTH/HEIGHT;  t = math.tan(math.radians(FOV/2))
    rcx = ((2*px/VIEW_WIDTH)-1)*aspect*t
    rcy = (1-(2*py/HEIGHT))*t
    rcz = -1.0
    rcx, rcy, rcz = normalize((rcx, rcy, rcz))
    pr = math.radians(cam_pitch);  cp, sp = math.cos(pr), math.sin(pr)
    rx1 = rcx;  ry1 = rcy*cp - rcz*sp;  rz1 = rcy*sp + rcz*cp
    yr = math.radians(cam_yaw);  cy, sy = math.cos(yr), math.sin(yr)
    return normalize((rx1*cy+rz1*sy, ry1, -rx1*sy+rz1*cy))

# ── Intersection ───────────────────────────────────────────────────────────────
def ray_triangle(orig, dir, v0, v1, v2):
    EPS = 1e-7
    e1, e2 = vsub(v1,v0), vsub(v2,v0)
    h = cross(dir, e2);  a = dot(e1, h)
    if -EPS < a < EPS: return None
    f = 1/a;  s = vsub(orig, v0);  u = f*dot(s, h)
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

def ray_plane_intersect(ray_o, ray_d, plane_pt, plane_n):
    denom = dot(ray_d, plane_n)
    if abs(denom) < 1e-10: return None
    t = dot(vsub(plane_pt, ray_o), plane_n) / denom
    return vadd(ray_o, vscale(ray_d, t)) if t > 0 else None

def ray_line_closest_s(ray_o, ray_d, line_o, line_d):
    w = vsub(ray_o, line_o)
    a, b, c = dot(ray_d,ray_d), dot(ray_d,line_d), dot(line_d,line_d)
    d, e = dot(ray_d,w), dot(line_d,w)
    denom = a*c - b*b
    return (a*e - b*d)/denom if abs(denom) > 1e-10 else 0.0

def seg_dist_2d(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay;  len2 = dx*dx+dy*dy
    if len2 < 1e-10: return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx+(py-ay)*dy)/len2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

# ── Géométrie rotation ─────────────────────────────────────────────────────────
def angle_on_plane(point, center, u, v):
    local = vsub(point, center)
    return math.atan2(dot(local, v), dot(local, u))

def rotate_point(point, center, axis, angle):
    p  = vsub(point, center)
    ca, sa = math.cos(angle), math.sin(angle)
    return vadd(center, vadd(vadd(vscale(p, ca),
                                  vscale(cross(axis, p), sa)),
                             vscale(axis, dot(axis, p)*(1-ca))))

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

# -- Gizmo translation --
def draw_arrow_3d(start, tip, color, selected=False):
    r, g, b = (1.0, 0.9, 0.1) if selected else color
    length = vlength(vsub(tip, start))
    if length < 1e-10: return
    axis = normalize(vsub(tip, start))
    cone_base = vadd(start, vscale(axis, length*0.78))
    cone_r = length*0.08;  u, v = perp_basis(axis);  N = 10
    glColor3f(r, g, b)
    glLineWidth(2.5 if selected else 2.0)
    glBegin(GL_LINES); glVertex3f(*start); glVertex3f(*cone_base); glEnd()
    glLineWidth(1.0)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(*tip)
    for i in range(N+1):
        a = 2*math.pi*i/N
        p = vadd(cone_base, vadd(vscale(u, cone_r*math.cos(a)), vscale(v, cone_r*math.sin(a))))
        glVertex3f(*p)
    glEnd()

def draw_translate_gizmo(center, active_axis=None):
    scale = gizmo_scale(center)
    glDisable(GL_DEPTH_TEST)
    for name, (axis_dir, color) in GIZMO_AXES.items():
        draw_arrow_3d(center, vadd(center, vscale(axis_dir, scale)), color, name==active_axis)
    glEnable(GL_DEPTH_TEST)

def pick_translate_axis(mx, my):
    if selected_quad_idx < 0: return None
    center = quad_center(quads[selected_quad_idx])
    scale  = gizmo_scale(center);  vx, vy = mx-PANEL_WIDTH, my
    best, best_d = None, 10.0
    for name, (axis_dir, _) in GIZMO_AXES.items():
        p0 = world_to_screen(*center)
        p1 = world_to_screen(*vadd(center, vscale(axis_dir, scale)))
        if p0 and p1:
            d = seg_dist_2d(vx, vy, p0[0], p0[1], p1[0], p1[1])
            if d < best_d: best_d, best = d, name
    return best

# -- Gizmo rotation --
RING_SEGMENTS = 48

def draw_rotate_gizmo(center, active_axis=None):
    scale = gizmo_scale(center)
    glDisable(GL_DEPTH_TEST)
    for name, (axis_dir, color) in GIZMO_AXES.items():
        r, g, b = (1.0, 0.9, 0.1) if name == active_axis else color
        glColor3f(r, g, b)
        glLineWidth(2.5 if name == active_axis else 2.0)
        u, v = perp_basis(axis_dir)
        glBegin(GL_LINE_LOOP)
        for i in range(RING_SEGMENTS):
            a = 2*math.pi*i/RING_SEGMENTS
            p = vadd(center, vadd(vscale(u, scale*math.cos(a)), vscale(v, scale*math.sin(a))))
            glVertex3f(*p)
        glEnd()
    glLineWidth(1.0)
    glEnable(GL_DEPTH_TEST)

def pick_rotate_axis(mx, my):
    if selected_quad_idx < 0: return None
    center = quad_center(quads[selected_quad_idx])
    scale  = gizmo_scale(center);  vx, vy = mx-PANEL_WIDTH, my
    best, best_d = None, 10.0
    for name, (axis_dir, _) in GIZMO_AXES.items():
        u, v = perp_basis(axis_dir)
        prev = None
        for i in range(RING_SEGMENTS+1):
            a = 2*math.pi*i/RING_SEGMENTS
            p = vadd(center, vadd(vscale(u, scale*math.cos(a)), vscale(v, scale*math.sin(a))))
            sp = world_to_screen(*p)
            if sp and prev:
                d = seg_dist_2d(vx, vy, prev[0], prev[1], sp[0], sp[1])
                if d < best_d: best_d, best = d, name
            prev = sp if sp else None
    return best

# ── Quads ──────────────────────────────────────────────────────────────────────
def add_vertical_quad():
    yr = math.radians(cam_yaw)
    cx = round(cam_pos[0] - math.sin(yr) * 5)
    cz = round(cam_pos[2] - math.cos(yr) * 5)
    quads.append([
        (cx-1, 0.0, cz-1), (cx+1, 0.0, cz-1),
        (cx+1, 0.0, cz+1), (cx-1, 0.0, cz+1),
    ])

def draw_quads():
    for i, quad in enumerate(quads):
        sel = (i == selected_quad_idx)
        glColor3f(0.85, 0.55, 0.20)
        glBegin(GL_QUADS)
        for vx, vy, vz in quad: glVertex3f(vx, vy, vz)
        glEnd()
        glLineWidth(2.5 if sel else 1.5)
        glColor3f(1.0, 0.15, 0.15) if sel else glColor3f(1.0, 0.75, 0.35)
        glBegin(GL_LINE_LOOP)
        for vx, vy, vz in quad: glVertex3f(vx, vy, vz)
        glEnd()
    glLineWidth(1.0)

# ── Drag translation ───────────────────────────────────────────────────────────
def start_translate_drag(axis, mx, my):
    global dragging_axis, drag_start_verts, drag_axis_t0
    dragging_axis    = axis
    drag_start_verts = list(quads[selected_quad_idx])
    center   = quad_center(drag_start_verts)
    drag_axis_t0 = ray_line_closest_s(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my),
                                      center, GIZMO_AXES[axis][0])

def update_translate_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    center   = quad_center(drag_start_verts)
    axis_dir = GIZMO_AXES[dragging_axis][0]
    t = ray_line_closest_s(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my), center, axis_dir)
    move = vscale(axis_dir, round(t - drag_axis_t0))
    quads[selected_quad_idx] = [vadd(v, move) for v in drag_start_verts]

# ── Drag rotation ──────────────────────────────────────────────────────────────
def start_rotate_drag(axis, mx, my):
    global dragging_axis, drag_start_verts, drag_angle0, drag_plane_u, drag_plane_v, drag_center
    dragging_axis    = axis
    drag_start_verts = list(quads[selected_quad_idx])
    drag_center      = quad_center(drag_start_verts)
    axis_dir         = GIZMO_AXES[axis][0]
    drag_plane_u, drag_plane_v = perp_basis(axis_dir)
    hit = ray_plane_intersect(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my),
                              drag_center, axis_dir)
    drag_angle0 = angle_on_plane(hit, drag_center, drag_plane_u, drag_plane_v) if hit else 0.0

def update_rotate_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    axis_dir = GIZMO_AXES[dragging_axis][0]
    hit = ray_plane_intersect(tuple(cam_pos), screen_ray(mx-PANEL_WIDTH, my),
                              drag_center, axis_dir)
    if hit is None: return
    angle = angle_on_plane(hit, drag_center, drag_plane_u, drag_plane_v)
    step  = math.radians(45)
    delta = round((angle - drag_angle0) / step) * step
    quads[selected_quad_idx] = [rotate_point(v, drag_center, axis_dir, delta)
                                 for v in drag_start_verts]

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

def draw_panel(btn_hovered, btn_tex, btn_tex_w, btn_tex_h, mode_tex, mode_tex_w, mode_tex_h):
    draw_rect(0, 0, PANEL_WIDTH, HEIGHT, 0.10, 0.10, 0.13)
    draw_rect(PANEL_WIDTH-1, 0, 1, HEIGHT, 0.22, 0.22, 0.28)
    b = BTN
    if btn_hovered:
        draw_rect(b["x"], b["y"], b["w"], b["h"], 0.35, 0.55, 0.85)
    else:
        draw_rect(b["x"], b["y"], b["w"], b["h"], 0.22, 0.40, 0.70)
    draw_texture(btn_tex, b["x"]+(b["w"]-btn_tex_w)//2, b["y"]+(b["h"]-btn_tex_h)//2,
                 btn_tex_w, btn_tex_h)
    # Indicateur de mode gizmo (affiché si un objet est sélectionné)
    if selected_quad_idx >= 0:
        draw_texture(mode_tex, b["x"], b["y"]+b["h"]+10, mode_tex_w, mode_tex_h)

# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    global cam_pos, cam_yaw, cam_pitch
    global selected_quad_idx, gizmo_mode
    global dragging_axis, drag_start_verts, drag_axis_t0
    global drag_angle0, drag_plane_u, drag_plane_v, drag_center

    pygame.init()
    pygame.display.set_mode((TOTAL_WIDTH, HEIGHT), DOUBLEBUF | OPENGL)
    pygame.display.set_caption("3D Viewer")
    glEnable(GL_DEPTH_TEST)
    glClearColor(0.08, 0.08, 0.12, 1.0)

    font     = pygame.font.SysFont("segoeui", 15)
    font_sm  = pygame.font.SysFont("segoeui", 13)
    btn_tex, btn_tex_w, btn_tex_h = make_text_texture(font, "add quad")

    def make_mode_tex():
        label = "[ Espace ] Gizmo : Translation" if gizmo_mode == 'translate' else "[ Espace ] Gizmo : Rotation"
        col   = (120, 200, 120) if gizmo_mode == 'translate' else (200, 140, 80)
        return make_text_texture(font_sm, label, col)

    mode_tex, mode_tex_w, mode_tex_h = make_mode_tex()

    clock   = pygame.time.Clock()
    running = True

    while running:
        dt = clock.tick(60) / 1000.0
        mx, my = pygame.mouse.get_pos()
        in_3d  = mx >= PANEL_WIDTH
        btn_hovered = (BTN["x"] <= mx <= BTN["x"]+BTN["w"] and BTN["y"] <= my <= BTN["y"]+BTN["h"])

        for event in pygame.event.get():
            if event.type == QUIT: running = False
            if event.type == KEYDOWN:
                if event.key == K_ESCAPE: running = False
                if event.key == K_SPACE and selected_quad_idx >= 0:
                    gizmo_mode = 'rotate' if gizmo_mode == 'translate' else 'translate'
                    mode_tex, mode_tex_w, mode_tex_h = make_mode_tex()
                    dragging_axis = None

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if btn_hovered:
                    add_vertical_quad()
                elif in_3d:
                    if gizmo_mode == 'translate':
                        axis = pick_translate_axis(mx, my)
                        if axis:
                            start_translate_drag(axis, mx, my)
                        else:
                            selected_quad_idx = _pick_quad(mx, my)
                    else:
                        axis = pick_rotate_axis(mx, my)
                        if axis:
                            start_rotate_drag(axis, mx, my)
                        else:
                            selected_quad_idx = _pick_quad(mx, my)
                            gizmo_mode = 'translate'
                            mode_tex, mode_tex_w, mode_tex_h = make_mode_tex()

            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                dragging_axis = None;  drag_start_verts = None

        if dragging_axis and pygame.mouse.get_pressed()[0]:
            if gizmo_mode == 'translate':
                update_translate_drag(mx, my)
            else:
                update_rotate_drag(mx, my)

        dx, dy = pygame.mouse.get_rel()
        if pygame.mouse.get_pressed()[1] and in_3d:
            cam_yaw   = (cam_yaw   - dx * MOUSE_SENSITIVITY) % 360.0
            cam_pitch = max(-89.0, min(89.0, cam_pitch - dy * MOUSE_SENSITIVITY))

        keys  = pygame.key.get_pressed();  speed = MOVE_SPEED * dt
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
            center = quad_center(quads[selected_quad_idx])
            if gizmo_mode == 'translate':
                draw_translate_gizmo(center, dragging_axis)
            else:
                draw_rotate_gizmo(center, dragging_axis)

        # ── Rendu 2D ──────────────────────────────────────────────────────────
        begin_2d()
        draw_panel(btn_hovered, btn_tex, btn_tex_w, btn_tex_h, mode_tex, mode_tex_w, mode_tex_h)
        end_2d()

        pygame.display.flip()

    glDeleteTextures(1, [btn_tex])
    glDeleteTextures(1, [mode_tex])
    pygame.quit()


def _pick_quad(mx, my):
    ray_o = tuple(cam_pos);  ray_d = screen_ray(mx-PANEL_WIDTH, my)
    best_t, best_i = float('inf'), -1
    for i, q in enumerate(quads):
        t = ray_quad_intersect(ray_o, ray_d, q)
        if t is not None and t < best_t: best_t, best_i = t, i
    return best_i


if __name__ == "__main__":
    main()
