"""
Visionneuse 3D
Navigation : ZQSD déplacer, molette orienter, Espace alterner gizmos, Échap quitter
"""

import copy
import math
import pygame
from pygame.locals import DOUBLEBUF, OPENGL, QUIT, KEYDOWN, K_ESCAPE, K_z, K_q, K_s, K_d, K_SPACE, K_c, K_DELETE, K_t
from OpenGL.GL import *
from OpenGL.GLU import gluPerspective

# ── Dimensions ─────────────────────────────────────────────────────────────────
PANEL_WIDTH = 250
VIEW_WIDTH  = 1280
HEIGHT      = 720
TOTAL_WIDTH = PANEL_WIDTH + VIEW_WIDTH
FOV         = 60.0
NEAR, FAR      = 0.05, 2000.0
TEXTURE_PATH   = r"C:\Dev\Paris\assets\textures\result.png"
PREVIEW_MAX_SZ = 512

# ── Caméra ─────────────────────────────────────────────────────────────────────
cam_pos   = [0.0, 3.0, 8.0]
cam_yaw   = 0.0
cam_pitch = -20.0
MOVE_SPEED        = 8.0
MOUSE_SENSITIVITY = 0.15

# ── Monde ──────────────────────────────────────────────────────────────────────
quads           = []
quad_texture    = 0
tex_preview_win = None
tex_preview_sz  = 0
tex_click_pos   = None   # (u, v) normalisé 0-1 du dernier clic dans l'aperçu

# ── Sélection / gizmo ──────────────────────────────────────────────────────────
selected_quad_idx = -1
gizmo_mode        = 'translate'   # 'translate' | 'rotate' | 'scale'
GIZMO_MODES       = ['translate', 'rotate', 'scale']

# État drag partagé
dragging_axis    = None   # axe ('x','y','z') ou handle ('width','height','uniform')
drag_start_verts = None
drag_axis_t0     = 0.0

# État drag rotation
drag_angle0   = 0.0
drag_plane_u  = None
drag_plane_v  = None
drag_center   = None

# État drag scale
drag_hw0 = 0.0
drag_hh0 = 0.0
drag_wa  = None
drag_ha  = None

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

# ── Caméra ─────────────────────────────────────────────────────────────────────
def forward_xz(yaw, pitch=0.0):
    yr, pr = math.radians(yaw), math.radians(pitch)
    return (math.cos(pr)*math.sin(yr), math.sin(pr), math.cos(pr)*math.cos(yr))

def right_xz(yaw):
    r = math.radians(yaw)
    return (math.cos(r), 0.0, -math.sin(r))

def world_to_screen(wx, wy, wz):
    tx, ty, tz = wx-cam_pos[0], wy-cam_pos[1], wz-cam_pos[2]
    yr = math.radians(cam_yaw);  cy, sy = math.cos(yr), math.sin(yr)
    cx2 = tx*cy-tz*sy;  cy2 = ty;  cz2 = tx*sy+tz*cy
    pr = math.radians(cam_pitch);  cp, sp = math.cos(pr), math.sin(pr)
    cx3 = cx2;  cy3 = cy2*cp+cz2*sp;  cz3 = -cy2*sp+cz2*cp
    if cz3 >= -1e-4: return None
    aspect = VIEW_WIDTH/HEIGHT;  t = math.tan(math.radians(FOV/2))
    return ((cx3/(-cz3*aspect*t)+1)/2*VIEW_WIDTH, (1-cy3/(-cz3*t))/2*HEIGHT)

def screen_ray(px, py):
    aspect = VIEW_WIDTH/HEIGHT;  t = math.tan(math.radians(FOV/2))
    rcx = ((2*px/VIEW_WIDTH)-1)*aspect*t
    rcy = (1-(2*py/HEIGHT))*t;  rcz = -1.0
    rcx, rcy, rcz = normalize((rcx, rcy, rcz))
    pr = math.radians(cam_pitch);  cp, sp = math.cos(pr), math.sin(pr)
    rx1 = rcx;  ry1 = rcy*cp-rcz*sp;  rz1 = rcy*sp+rcz*cp
    yr = math.radians(cam_yaw);  cy, sy = math.cos(yr), math.sin(yr)
    return normalize((rx1*cy+rz1*sy, ry1, -rx1*sy+rz1*cy))

# ── Intersection ───────────────────────────────────────────────────────────────
def ray_triangle(orig, dir, v0, v1, v2):
    EPS = 1e-7
    e1, e2 = vsub(v1,v0), vsub(v2,v0)
    h = cross(dir,e2);  a = dot(e1,h)
    if -EPS < a < EPS: return None
    f=1/a;  s=vsub(orig,v0);  u=f*dot(s,h)
    if u<0 or u>1: return None
    q=cross(s,e1);  v=f*dot(dir,q)
    if v<0 or u+v>1: return None
    t=f*dot(e2,q);  return t if t>EPS else None

def ray_quad_intersect(orig, dir, quad):
    v=[tuple(x) for x in quad]
    hits=[t for t in (ray_triangle(orig,dir,v[0],v[1],v[2]),
                      ray_triangle(orig,dir,v[0],v[2],v[3])) if t is not None]
    return min(hits) if hits else None

def ray_plane_intersect(ray_o, ray_d, plane_pt, plane_n):
    denom = dot(ray_d, plane_n)
    if abs(denom) < 1e-10: return None
    t = dot(vsub(plane_pt, ray_o), plane_n)/denom
    return vadd(ray_o, vscale(ray_d, t)) if t > 0 else None

def ray_line_closest_s(ray_o, ray_d, line_o, line_d):
    w=vsub(ray_o,line_o);  a,b,c=dot(ray_d,ray_d),dot(ray_d,line_d),dot(line_d,line_d)
    d,e=dot(ray_d,w),dot(line_d,w);  denom=a*c-b*b
    return (a*e-b*d)/denom if abs(denom)>1e-10 else 0.0

def seg_dist_2d(px,py,ax,ay,bx,by):
    dx,dy=bx-ax,by-ay;  len2=dx*dx+dy*dy
    if len2<1e-10: return math.hypot(px-ax,py-ay)
    t=max(0.0,min(1.0,((px-ax)*dx+(py-ay)*dy)/len2))
    return math.hypot(px-(ax+t*dx),py-(ay+t*dy))

# ── Géométrie ──────────────────────────────────────────────────────────────────
def angle_on_plane(point, center, u, v):
    local = vsub(point, center)
    return math.atan2(dot(local, v), dot(local, u))

def rotate_point(point, center, axis, angle):
    p=vsub(point,center);  ca,sa=math.cos(angle),math.sin(angle)
    return vadd(center, vadd(vadd(vscale(p,ca), vscale(cross(axis,p),sa)),
                             vscale(axis, dot(axis,p)*(1-ca))))

def quad_center(quad):
    return (sum(v[0] for v in quad)/4, sum(v[1] for v in quad)/4, sum(v[2] for v in quad)/4)

def quad_decompose(quad):
    """Retourne (center, width_axis, height_axis, half_width, half_height)."""
    v0,v1,_,v3=[tuple(v) for v in quad]
    center=quad_center(quad)
    wa=normalize(vsub(v1,v0));  ha=normalize(vsub(v3,v0))
    hw=vlength(vsub(v1,v0))/2;  hh=vlength(vsub(v3,v0))/2
    return center, wa, ha, hw, hh

def quad_compose(center, wa, ha, hw, hh):
    return [
        vsub(vsub(center,vscale(wa,hw)),vscale(ha,hh)),
        vsub(vadd(center,vscale(wa,hw)),vscale(ha,hh)),
        vadd(vadd(center,vscale(wa,hw)),vscale(ha,hh)),
        vadd(vsub(center,vscale(wa,hw)),vscale(ha,hh)),
    ]

# ── Gizmo helpers ──────────────────────────────────────────────────────────────
GIZMO_AXES = {
    'x': ((1,0,0), (1.0, 0.25, 0.25)),
    'y': ((0,1,0), (0.25, 1.0, 0.25)),
    'z': ((0,0,1), (0.25, 0.5,  1.0)),
}
SCALE_COLORS = {
    'width':   (1.0,  0.55, 0.0),
    'height':  (0.0,  0.80, 0.80),
    'uniform': (0.90, 0.90, 0.90),
}

def gizmo_scale(center):
    return max(0.5, vlength(vsub(tuple(cam_pos), center))*0.2)

def perp_basis(axis):
    ref=(1,0,0) if abs(axis[0])<0.9 else (0,1,0)
    u=normalize(cross(axis,ref));  return u, normalize(cross(axis,u))

def scale_handle_positions(quad):
    center, wa, ha, hw, hh = quad_decompose(quad)
    off  = gizmo_scale(center)*0.3
    diag = normalize(vadd(wa, ha))
    return {
        'width':   vadd(center, vscale(wa, hw+off)),
        'height':  vadd(center, vscale(ha, hh+off)),
        'uniform': vadd(center, vscale(diag, math.hypot(hw, hh)+off*1.2)),
    }

# ── Rendu gizmos ───────────────────────────────────────────────────────────────
def draw_arrow_3d(start, tip, color, selected=False):
    r,g,b=(1.0,0.9,0.1) if selected else color
    length=vlength(vsub(tip,start));
    if length<1e-10: return
    axis=normalize(vsub(tip,start))
    cone_base=vadd(start,vscale(axis,length*0.78))
    cone_r=length*0.08;  u,v=perp_basis(axis);  N=10
    glColor3f(r,g,b)
    glLineWidth(2.5 if selected else 2.0)
    glBegin(GL_LINES); glVertex3f(*start); glVertex3f(*cone_base); glEnd()
    glLineWidth(1.0)
    glBegin(GL_TRIANGLE_FAN); glVertex3f(*tip)
    for i in range(N+1):
        a=2*math.pi*i/N
        p=vadd(cone_base,vadd(vscale(u,cone_r*math.cos(a)),vscale(v,cone_r*math.sin(a))))
        glVertex3f(*p)
    glEnd()

def draw_box_3d(pos, size, r, g, b):
    x,y,z=pos;  s=size/2
    glColor3f(r,g,b)
    glBegin(GL_QUADS)
    for face in [
        [(x-s,y-s,z+s),(x+s,y-s,z+s),(x+s,y+s,z+s),(x-s,y+s,z+s)],
        [(x+s,y-s,z-s),(x-s,y-s,z-s),(x-s,y+s,z-s),(x+s,y+s,z-s)],
        [(x-s,y-s,z-s),(x-s,y-s,z+s),(x-s,y+s,z+s),(x-s,y+s,z-s)],
        [(x+s,y-s,z+s),(x+s,y-s,z-s),(x+s,y+s,z-s),(x+s,y+s,z+s)],
        [(x-s,y+s,z+s),(x+s,y+s,z+s),(x+s,y+s,z-s),(x-s,y+s,z-s)],
        [(x-s,y-s,z-s),(x+s,y-s,z-s),(x+s,y-s,z+s),(x-s,y-s,z+s)],
    ]:
        for v in face: glVertex3f(*v)
    glEnd()

def draw_translate_gizmo(center, active=None):
    scale=gizmo_scale(center)
    glDisable(GL_DEPTH_TEST)
    for name,(axis_dir,color) in GIZMO_AXES.items():
        draw_arrow_3d(center, vadd(center,vscale(axis_dir,scale)), color, name==active)
    glEnable(GL_DEPTH_TEST)

def draw_rotate_gizmo(center, active=None):
    scale=gizmo_scale(center);  N=48
    glDisable(GL_DEPTH_TEST)
    for name,(axis_dir,color) in GIZMO_AXES.items():
        r,g,b=(1.0,0.9,0.1) if name==active else color
        glColor3f(r,g,b);  glLineWidth(2.5 if name==active else 2.0)
        u,v=perp_basis(axis_dir)
        glBegin(GL_LINE_LOOP)
        for i in range(N):
            a=2*math.pi*i/N
            p=vadd(center,vadd(vscale(u,scale*math.cos(a)),vscale(v,scale*math.sin(a))))
            glVertex3f(*p)
        glEnd()
    glLineWidth(1.0);  glEnable(GL_DEPTH_TEST)

def draw_scale_gizmo(quad, active=None):
    center=quad_center(quad);  bs=gizmo_scale(center)*0.1
    handles=scale_handle_positions(quad)
    glDisable(GL_DEPTH_TEST)
    glLineWidth(2.0)
    for name,pos in handles.items():
        r,g,b=(1.0,0.9,0.1) if name==active else SCALE_COLORS[name]
        glColor3f(r,g,b)
        glBegin(GL_LINES); glVertex3f(*center); glVertex3f(*pos); glEnd()
        draw_box_3d(pos, bs*(1.4 if name==active else 1.0), r,g,b)
    glLineWidth(1.0);  glEnable(GL_DEPTH_TEST)

# ── Picking gizmos ─────────────────────────────────────────────────────────────
def pick_translate_axis(mx, my):
    if selected_quad_idx<0: return None
    center=quad_center(quads[selected_quad_idx]);  scale=gizmo_scale(center)
    vx,vy=mx-PANEL_WIDTH,my;  best,best_d=None,10.0
    for name,(axis_dir,_) in GIZMO_AXES.items():
        p0=world_to_screen(*center);  p1=world_to_screen(*vadd(center,vscale(axis_dir,scale)))
        if p0 and p1:
            d=seg_dist_2d(vx,vy,p0[0],p0[1],p1[0],p1[1])
            if d<best_d: best_d,best=d,name
    return best

def pick_rotate_axis(mx, my):
    if selected_quad_idx<0: return None
    center=quad_center(quads[selected_quad_idx]);  scale=gizmo_scale(center)
    vx,vy=mx-PANEL_WIDTH,my;  N=48;  best,best_d=None,10.0
    for name,(axis_dir,_) in GIZMO_AXES.items():
        u,v=perp_basis(axis_dir);  prev=None
        for i in range(N+1):
            a=2*math.pi*i/N
            p=vadd(center,vadd(vscale(u,scale*math.cos(a)),vscale(v,scale*math.sin(a))))
            sp=world_to_screen(*p)
            if sp and prev:
                d=seg_dist_2d(vx,vy,prev[0],prev[1],sp[0],sp[1])
                if d<best_d: best_d,best=d,name
            prev=sp if sp else None
    return best

def pick_scale_handle(mx, my):
    if selected_quad_idx<0: return None
    handles=scale_handle_positions(quads[selected_quad_idx])
    vx,vy=mx-PANEL_WIDTH,my;  best,best_d=None,15.0
    for name,pos in handles.items():
        sp=world_to_screen(*pos)
        if sp:
            d=math.hypot(vx-sp[0],vy-sp[1])
            if d<best_d: best_d,best=d,name
    return best

# ── Quads ──────────────────────────────────────────────────────────────────────
def add_quad():
    yr=math.radians(cam_yaw)
    cx=round(cam_pos[0]-math.sin(yr)*5)
    cz=round(cam_pos[2]-math.cos(yr)*5)
    quads.append([
        (cx-1,0.0,cz-1),(cx+1,0.0,cz-1),
        (cx+1,0.0,cz+1),(cx-1,0.0,cz+1),
    ])

def draw_quads():
    QUAD_UVS=[(0,0),(1,0),(1,1),(0,1)]
    for i,quad in enumerate(quads):
        sel=(i==selected_quad_idx)
        glEnable(GL_TEXTURE_2D);  glBindTexture(GL_TEXTURE_2D,quad_texture)
        glColor3f(1.0,1.0,1.0)
        glBegin(GL_QUADS)
        for (vx,vy,vz),(u,v) in zip(quad,QUAD_UVS):
            glTexCoord2f(u,v);  glVertex3f(vx,vy,vz)
        glEnd()
        glDisable(GL_TEXTURE_2D)
        glLineWidth(2.5 if sel else 1.5)
        glColor3f(1.0,0.15,0.15) if sel else glColor3f(1.0,0.75,0.35)
        glBegin(GL_LINE_LOOP)
        for vx,vy,vz in quad: glVertex3f(vx,vy,vz)
        glEnd()
    glLineWidth(1.0)

# ── Drag translation ───────────────────────────────────────────────────────────
def start_translate_drag(axis, mx, my):
    global dragging_axis, drag_start_verts, drag_axis_t0
    dragging_axis=axis;  drag_start_verts=list(quads[selected_quad_idx])
    center=quad_center(drag_start_verts)
    drag_axis_t0=ray_line_closest_s(tuple(cam_pos),screen_ray(mx-PANEL_WIDTH,my),
                                    center,GIZMO_AXES[axis][0])

def update_translate_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    center=quad_center(drag_start_verts);  axis_dir=GIZMO_AXES[dragging_axis][0]
    t=ray_line_closest_s(tuple(cam_pos),screen_ray(mx-PANEL_WIDTH,my),center,axis_dir)
    move=vscale(axis_dir,round((t-drag_axis_t0)*2)/2)
    quads[selected_quad_idx]=[vadd(v,move) for v in drag_start_verts]

# ── Drag rotation ──────────────────────────────────────────────────────────────
def start_rotate_drag(axis, mx, my):
    global dragging_axis, drag_start_verts, drag_angle0, drag_plane_u, drag_plane_v, drag_center
    dragging_axis=axis;  drag_start_verts=list(quads[selected_quad_idx])
    drag_center=quad_center(drag_start_verts);  axis_dir=GIZMO_AXES[axis][0]
    drag_plane_u,drag_plane_v=perp_basis(axis_dir)
    hit=ray_plane_intersect(tuple(cam_pos),screen_ray(mx-PANEL_WIDTH,my),drag_center,axis_dir)
    drag_angle0=angle_on_plane(hit,drag_center,drag_plane_u,drag_plane_v) if hit else 0.0

def update_rotate_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    axis_dir=GIZMO_AXES[dragging_axis][0]
    hit=ray_plane_intersect(tuple(cam_pos),screen_ray(mx-PANEL_WIDTH,my),drag_center,axis_dir)
    if hit is None: return
    angle=angle_on_plane(hit,drag_center,drag_plane_u,drag_plane_v)
    step=math.radians(45);  delta=round((angle-drag_angle0)/step)*step
    quads[selected_quad_idx]=[rotate_point(v,drag_center,axis_dir,delta) for v in drag_start_verts]

# ── Drag scale ─────────────────────────────────────────────────────────────────
def start_scale_drag(handle, mx, my):
    global dragging_axis, drag_start_verts, drag_axis_t0
    global drag_hw0, drag_hh0, drag_wa, drag_ha, drag_center
    dragging_axis=handle;  drag_start_verts=list(quads[selected_quad_idx])
    drag_center,drag_wa,drag_ha,drag_hw0,drag_hh0=quad_decompose(drag_start_verts)
    ray_o=tuple(cam_pos);  ray_d=screen_ray(mx-PANEL_WIDTH,my)
    if handle=='width':
        drag_axis_t0=ray_line_closest_s(ray_o,ray_d,drag_center,drag_wa)
    elif handle=='height':
        drag_axis_t0=ray_line_closest_s(ray_o,ray_d,drag_center,drag_ha)
    else:
        drag_axis_t0=ray_line_closest_s(ray_o,ray_d,drag_center,normalize(vadd(drag_wa,drag_ha)))

def update_scale_drag(mx, my):
    if dragging_axis is None or drag_start_verts is None: return
    ray_o=tuple(cam_pos);  ray_d=screen_ray(mx-PANEL_WIDTH,my)
    snap=lambda x: max(0.5, round(x*2)/2)
    if dragging_axis=='width':
        t=ray_line_closest_s(ray_o,ray_d,drag_center,drag_wa)
        new_hw=snap(drag_hw0+(t-drag_axis_t0));  new_hh=drag_hh0
    elif dragging_axis=='height':
        t=ray_line_closest_s(ray_o,ray_d,drag_center,drag_ha)
        new_hw=drag_hw0;  new_hh=snap(drag_hh0+(t-drag_axis_t0))
    else:
        diag=normalize(vadd(drag_wa,drag_ha))
        t=ray_line_closest_s(ray_o,ray_d,drag_center,diag)
        delta=t-drag_axis_t0;  new_hw=snap(drag_hw0+delta);  new_hh=snap(drag_hh0+delta)
    quads[selected_quad_idx]=quad_compose(drag_center,drag_wa,drag_ha,new_hw,new_hh)

# ── Grille ─────────────────────────────────────────────────────────────────────
def draw_grid(half_size=30, step=1):
    glLineWidth(1.0)
    glBegin(GL_LINES)
    for i in range(-half_size,half_size+1,step):
        if i==0: continue
        glColor3f(0.30,0.30,0.35)
        glVertex3f(-half_size,0,i); glVertex3f(half_size,0,i)
        glVertex3f(i,0,-half_size); glVertex3f(i,0,half_size)
    glEnd()
    glLineWidth(2.0)
    glBegin(GL_LINES)
    glColor3f(0.8,0.2,0.2); glVertex3f(-half_size,0,0); glVertex3f(half_size,0,0)
    glColor3f(0.2,0.4,0.9); glVertex3f(0,0,-half_size); glVertex3f(0,0,half_size)
    glEnd();  glLineWidth(1.0)

# ── UI 2D ──────────────────────────────────────────────────────────────────────
def load_texture(path):
    surf=pygame.image.load(path).convert_alpha();  w,h=surf.get_size()
    data=pygame.image.tobytes(surf,"RGBA",True)
    tex=glGenTextures(1);  glBindTexture(GL_TEXTURE_2D,tex)
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,data)
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
    glBindTexture(GL_TEXTURE_2D,0);  return tex

def make_text_texture(font, text, color=(255,255,255)):
    surf=font.render(text,True,color);  w,h=surf.get_size()
    data=pygame.image.tobytes(surf,"RGBA",True)
    tex=glGenTextures(1);  glBindTexture(GL_TEXTURE_2D,tex)
    glTexImage2D(GL_TEXTURE_2D,0,GL_RGBA,w,h,0,GL_RGBA,GL_UNSIGNED_BYTE,data)
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
    glBindTexture(GL_TEXTURE_2D,0);  return tex,w,h

def begin_2d():
    glViewport(0,0,TOTAL_WIDTH,HEIGHT)
    glMatrixMode(GL_PROJECTION);  glPushMatrix();  glLoadIdentity()
    glOrtho(0,TOTAL_WIDTH,HEIGHT,0,-1,1)
    glMatrixMode(GL_MODELVIEW);  glPushMatrix();  glLoadIdentity()
    glDisable(GL_DEPTH_TEST)

def end_2d():
    glMatrixMode(GL_PROJECTION);  glPopMatrix()
    glMatrixMode(GL_MODELVIEW);   glPopMatrix()
    glEnable(GL_DEPTH_TEST)

def draw_rect(x,y,w,h,r,g,b):
    glColor3f(r,g,b)
    glBegin(GL_QUADS)
    glVertex2f(x,y); glVertex2f(x+w,y); glVertex2f(x+w,y+h); glVertex2f(x,y+h)
    glEnd()

def draw_texture(tex_id,x,y,w,h):
    glEnable(GL_TEXTURE_2D);  glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA,GL_ONE_MINUS_SRC_ALPHA)
    glBindTexture(GL_TEXTURE_2D,tex_id);  glColor3f(1,1,1)
    glBegin(GL_QUADS)
    glTexCoord2f(0,1); glVertex2f(x,y);    glTexCoord2f(1,1); glVertex2f(x+w,y)
    glTexCoord2f(1,0); glVertex2f(x+w,y+h);glTexCoord2f(0,0); glVertex2f(x,y+h)
    glEnd()
    glDisable(GL_TEXTURE_2D);  glDisable(GL_BLEND)

BTN = {"x":15,"y":15,"w":220,"h":36}
MODE_INFO = {
    'translate': ("Gizmo : Translation",  (120,200,120)),
    'rotate':    ("Gizmo : Rotation",     (200,140, 80)),
    'scale':     ("Gizmo : Taille",       (180,100,220)),
}

def draw_panel(btn_hovered,btn_tex,btn_tex_w,btn_tex_h,mode_tex,mode_tex_w,mode_tex_h):
    draw_rect(0,0,PANEL_WIDTH,HEIGHT,0.10,0.10,0.13)
    draw_rect(PANEL_WIDTH-1,0,1,HEIGHT,0.22,0.22,0.28)
    b=BTN
    draw_rect(b["x"],b["y"],b["w"],b["h"],*(0.35,0.55,0.85) if btn_hovered else (0.22,0.40,0.70))
    draw_texture(btn_tex,b["x"]+(b["w"]-btn_tex_w)//2,b["y"]+(b["h"]-btn_tex_h)//2,btn_tex_w,btn_tex_h)
    if selected_quad_idx>=0:
        draw_texture(mode_tex,b["x"],b["y"]+b["h"]+10,mode_tex_w,mode_tex_h)

# ── Fenêtre aperçu texture ─────────────────────────────────────────────────────
def open_tex_preview():
    global tex_preview_win, tex_preview_sz
    if tex_preview_win:
        return
    img = pygame.image.load(TEXTURE_PATH)
    tex_preview_sz = min(img.get_width(), PREVIEW_MAX_SZ)
    if img.get_width() != tex_preview_sz:
        img = pygame.transform.smoothscale(img, (tex_preview_sz, tex_preview_sz))
    tex_preview_win = pygame.Window("Aperçu texture", size=(tex_preview_sz, tex_preview_sz))
    tex_preview_win.get_surface().blit(img, (0, 0))
    tex_preview_win.flip()

def close_tex_preview():
    global tex_preview_win
    if tex_preview_win:
        tex_preview_win.destroy()
        tex_preview_win = None

# ── Main ───────────────────────────────────────────────────────────────────────
def _pick_quad(mx,my):
    ray_o=tuple(cam_pos);  ray_d=screen_ray(mx-PANEL_WIDTH,my)
    best_t,best_i=float('inf'),-1
    for i,q in enumerate(quads):
        t=ray_quad_intersect(ray_o,ray_d,q)
        if t is not None and t<best_t: best_t,best_i=t,i
    return best_i

def main():
    global cam_pos,cam_yaw,cam_pitch
    global selected_quad_idx,gizmo_mode
    global quad_texture,tex_preview_win,tex_preview_sz,tex_click_pos
    global dragging_axis,drag_start_verts,drag_axis_t0
    global drag_angle0,drag_plane_u,drag_plane_v,drag_center
    global drag_hw0,drag_hh0,drag_wa,drag_ha

    pygame.init()
    pygame.display.set_mode((TOTAL_WIDTH,HEIGHT),DOUBLEBUF|OPENGL)
    pygame.display.set_caption("3D Viewer")
    glEnable(GL_DEPTH_TEST);  glClearColor(0.08,0.08,0.12,1.0)
    quad_texture=load_texture(TEXTURE_PATH)

    font    = pygame.font.SysFont("segoeui",15)
    font_sm = pygame.font.SysFont("segoeui",13)
    btn_tex,btn_tex_w,btn_tex_h = make_text_texture(font,"add quad")

    def make_mode_tex():
        label,col = MODE_INFO[gizmo_mode]
        return make_text_texture(font_sm,f"[ Espace ]  {label}",col)

    mode_tex,mode_tex_w,mode_tex_h = make_mode_tex()
    clock=pygame.time.Clock();  running=True

    while running:
        dt=clock.tick(60)/1000.0
        mx,my=pygame.mouse.get_pos()
        in_3d=mx>=PANEL_WIDTH
        btn_hovered=(BTN["x"]<=mx<=BTN["x"]+BTN["w"] and BTN["y"]<=my<=BTN["y"]+BTN["h"])

        for event in pygame.event.get():
            if event.type==QUIT: running=False
            if event.type==KEYDOWN:
                if event.key==K_ESCAPE: running=False
                if event.key==K_t and selected_quad_idx>=0:
                    if tex_preview_win: close_tex_preview()
                    else:               open_tex_preview()
                if event.key==K_DELETE and selected_quad_idx>=0:
                    quads.pop(selected_quad_idx)
                    selected_quad_idx=-1
                    dragging_axis=None
                if event.key==K_c and selected_quad_idx>=0:
                    quads.append(copy.deepcopy(quads[selected_quad_idx]))
                    selected_quad_idx=len(quads)-1
                if event.key==K_SPACE and selected_quad_idx>=0:
                    gizmo_mode=GIZMO_MODES[(GIZMO_MODES.index(gizmo_mode)+1)%3]
                    mode_tex,mode_tex_w,mode_tex_h=make_mode_tex()
                    dragging_axis=None

            if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                if btn_hovered:
                    add_quad()
                elif in_3d:
                    if gizmo_mode=='translate':
                        axis=pick_translate_axis(mx,my)
                        if axis: start_translate_drag(axis,mx,my)
                        else:    selected_quad_idx=_pick_quad(mx,my)
                    elif gizmo_mode=='rotate':
                        axis=pick_rotate_axis(mx,my)
                        if axis: start_rotate_drag(axis,mx,my)
                        else:
                            selected_quad_idx=_pick_quad(mx,my)
                            gizmo_mode='translate';  mode_tex,mode_tex_w,mode_tex_h=make_mode_tex()
                    else:  # scale
                        handle=pick_scale_handle(mx,my)
                        if handle: start_scale_drag(handle,mx,my)
                        else:
                            selected_quad_idx=_pick_quad(mx,my)
                            gizmo_mode='translate';  mode_tex,mode_tex_w,mode_tex_h=make_mode_tex()

            if event.type==pygame.MOUSEBUTTONUP and event.button==1:
                dragging_axis=None;  drag_start_verts=None

            if event.type==pygame.MOUSEBUTTONDOWN and event.button==1:
                if tex_preview_win and getattr(event,'window',None)==tex_preview_win:
                    tex_click_pos=(event.pos[0]/tex_preview_sz, event.pos[1]/tex_preview_sz)
                    print(f"Clic texture : pixel={event.pos}  uv=({tex_click_pos[0]:.3f}, {tex_click_pos[1]:.3f})")
                    close_tex_preview()

            if event.type==pygame.WINDOWCLOSE:
                if tex_preview_win and event.window==tex_preview_win:
                    close_tex_preview()
                else:
                    running=False

        if dragging_axis and pygame.mouse.get_pressed()[0]:
            if   gizmo_mode=='translate': update_translate_drag(mx,my)
            elif gizmo_mode=='rotate':    update_rotate_drag(mx,my)
            else:                         update_scale_drag(mx,my)

        dx,dy=pygame.mouse.get_rel()
        if pygame.mouse.get_pressed()[1] and in_3d:
            cam_yaw  =(cam_yaw  -dx*MOUSE_SENSITIVITY)%360.0
            cam_pitch=max(-89.0,min(89.0,cam_pitch-dy*MOUSE_SENSITIVITY))

        keys=pygame.key.get_pressed();  speed=MOVE_SPEED*dt
        fwd,rgt=forward_xz(cam_yaw,cam_pitch),right_xz(cam_yaw)
        if keys[K_z]: cam_pos[0]-=fwd[0]*speed; cam_pos[1]+=fwd[1]*speed; cam_pos[2]-=fwd[2]*speed
        if keys[K_s]: cam_pos[0]+=fwd[0]*speed; cam_pos[1]-=fwd[1]*speed; cam_pos[2]+=fwd[2]*speed
        if keys[K_q]: cam_pos[0]-=rgt[0]*speed; cam_pos[2]-=rgt[2]*speed
        if keys[K_d]: cam_pos[0]+=rgt[0]*speed; cam_pos[2]+=rgt[2]*speed

        # ── Rendu 3D ──────────────────────────────────────────────────────────
        glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT)
        glViewport(PANEL_WIDTH,0,VIEW_WIDTH,HEIGHT)
        glMatrixMode(GL_PROJECTION);  glLoadIdentity()
        gluPerspective(FOV,VIEW_WIDTH/HEIGHT,NEAR,FAR)
        glMatrixMode(GL_MODELVIEW);   glLoadIdentity()
        glRotatef(-cam_pitch,1,0,0);  glRotatef(-cam_yaw,0,1,0)
        glTranslatef(-cam_pos[0],-cam_pos[1],-cam_pos[2])

        draw_grid(30,1);  draw_quads()
        if selected_quad_idx>=0:
            q=quads[selected_quad_idx];  c=quad_center(q)
            if   gizmo_mode=='translate': draw_translate_gizmo(c,dragging_axis)
            elif gizmo_mode=='rotate':    draw_rotate_gizmo(c,dragging_axis)
            else:                         draw_scale_gizmo(q,dragging_axis)

        # ── Rendu 2D ──────────────────────────────────────────────────────────
        begin_2d()
        draw_panel(btn_hovered,btn_tex,btn_tex_w,btn_tex_h,mode_tex,mode_tex_w,mode_tex_h)
        end_2d()
        pygame.display.flip()

    close_tex_preview()
    glDeleteTextures(1,[btn_tex]);  glDeleteTextures(1,[mode_tex]);  glDeleteTextures(1,[quad_texture])
    pygame.quit()


if __name__=="__main__":
    main()
