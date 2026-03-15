"""Maths vectorielles 3D et intersections de rayons (fonctions pures)."""

import math

# ── Vec3 ─────────────────────────────────────────────────────────────────────
def vadd(a, b):   return (a[0]+b[0], a[1]+b[1], a[2]+b[2])
def vsub(a, b):   return (a[0]-b[0], a[1]-b[1], a[2]-b[2])
def vscale(a, s): return (a[0]*s, a[1]*s, a[2]*s)
def dot(a, b):    return a[0]*b[0]+a[1]*b[1]+a[2]*b[2]
def cross(a, b):  return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])
def vlength(a):   return math.sqrt(dot(a, a))
def normalize(a):
    l = vlength(a)
    return (a[0]/l, a[1]/l, a[2]/l) if l > 1e-10 else (0.0, 0.0, 0.0)

# ── Intersection ──────────────────────────────────────────────────────────────
def ray_triangle(orig, dir, v0, v1, v2):
    EPS = 1e-7
    e1, e2 = vsub(v1, v0), vsub(v2, v0)
    h = cross(dir, e2);  a = dot(e1, h)
    if -EPS < a < EPS: return None
    f = 1/a;  s = vsub(orig, v0);  u = f*dot(s, h)
    if u < 0 or u > 1: return None
    q = cross(s, e1);  v = f*dot(dir, q)
    if v < 0 or u+v > 1: return None
    t = f*dot(e2, q);  return t if t > EPS else None

def ray_poly_intersect(orig, dir, poly):
    v = [tuple(x) for x in poly]
    if len(v) < 3: return None
    normal = cross(vsub(v[1], v[0]), vsub(v[2], v[0]))
    if dot(dir, normal) <= 0: return None  # face arrière ou perpendiculaire
    hits = [t for i in range(1, len(v) - 1)
            for t in [ray_triangle(orig, dir, v[0], v[i], v[i+1])] if t is not None]
    return min(hits) if hits else None

def ray_plane_intersect(ray_o, ray_d, plane_pt, plane_n):
    denom = dot(ray_d, plane_n)
    if abs(denom) < 1e-10: return None
    t = dot(vsub(plane_pt, ray_o), plane_n) / denom
    return vadd(ray_o, vscale(ray_d, t)) if t > 0 else None

def ray_line_closest_s(ray_o, ray_d, line_o, line_d):
    w = vsub(ray_o, line_o)
    a, b, c = dot(ray_d, ray_d), dot(ray_d, line_d), dot(line_d, line_d)
    d, e = dot(ray_d, w), dot(line_d, w)
    denom = a*c - b*b
    return (a*e - b*d)/denom if abs(denom) > 1e-10 else 0.0

def closest_point_on_seg(p, a, b):
    ab = vsub(b, a)
    len2 = dot(ab, ab)
    if len2 < 1e-10:
        return a
    t = max(0.0, min(1.0, dot(vsub(p, a), ab) / len2))
    return vadd(a, vscale(ab, t))

def seg_dist_2d(px, py, ax, ay, bx, by):
    dx, dy = bx-ax, by-ay;  len2 = dx*dx + dy*dy
    if len2 < 1e-10: return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, ((px-ax)*dx + (py-ay)*dy) / len2))
    return math.hypot(px-(ax+t*dx), py-(ay+t*dy))

# ── Géométrie ─────────────────────────────────────────────────────────────────
def angle_on_plane(point, center, u, v):
    local = vsub(point, center)
    return math.atan2(dot(local, v), dot(local, u))

def rotate_point(point, center, axis, angle):
    p = vsub(point, center);  ca, sa = math.cos(angle), math.sin(angle)
    return vadd(center, vadd(vadd(vscale(p, ca), vscale(cross(axis, p), sa)),
                             vscale(axis, dot(axis, p)*(1-ca))))

def poly_center(poly):
    n = len(poly)
    return (sum(v[0] for v in poly)/n, sum(v[1] for v in poly)/n, sum(v[2] for v in poly)/n)

def quad_decompose(quad):
    """Retourne (center, width_axis, height_axis, half_width, half_height)."""
    v0, v1, _, v3 = [tuple(v) for v in quad]
    center = poly_center(quad)
    wa = normalize(vsub(v1, v0));  ha = normalize(vsub(v3, v0))
    hw = vlength(vsub(v1, v0))/2;  hh = vlength(vsub(v3, v0))/2
    return center, wa, ha, hw, hh

def quad_compose(center, wa, ha, hw, hh):
    return [
        vsub(vsub(center, vscale(wa, hw)), vscale(ha, hh)),
        vsub(vadd(center, vscale(wa, hw)), vscale(ha, hh)),
        vadd(vadd(center, vscale(wa, hw)), vscale(ha, hh)),
        vadd(vsub(center, vscale(wa, hw)), vscale(ha, hh)),
    ]

def diagonals_intersect(a, b, c, d):
    """Retourne True si les diagonales a-c et b-d du quad se croisent (quad non-papillon)."""
    d1 = vsub(c, a)
    d2 = vsub(d, b)
    r  = vsub(a, b)
    aa = dot(d1, d1)
    cc = dot(d2, d2)
    if aa < 1e-10 or cc < 1e-10:
        return False
    bb = dot(d1, d2)
    dd = dot(d1, r)
    ee = dot(d2, r)
    denom = aa * cc - bb * bb
    if abs(denom) < 1e-10:
        return False  # diagonales parallèles → papillon
    t = (bb * ee - cc * dd) / denom
    s = (aa * ee - bb * dd) / denom
    if not (0.0 < t < 1.0 and 0.0 < s < 1.0):
        return False
    pt1 = vadd(a, vscale(d1, t))
    pt2 = vadd(b, vscale(d2, s))
    len_ref = max(math.sqrt(aa), math.sqrt(cc))
    return vlength(vsub(pt1, pt2)) < 0.05 * len_ref

def perp_basis(axis):
    ref = (1, 0, 0) if abs(axis[0]) < 0.9 else (0, 1, 0)
    u = normalize(cross(axis, ref));  return u, normalize(cross(axis, u))
