#!/usr/bin/env python3
"""Track a feature across extracted frames and derive motion parameters.

Template matching uses FFT-based normalized cross-correlation with sub-pixel peak refinement.
An optional static anchor feature cancels translational camera motion. With --px-per-unit, the
results are in world units (studs or meters); otherwise they are in pixels.

Analyses:
  jump   parabola fit of the airborne segment: apex height, rise and fall times, gravity
         (overall and separately for rise and fall), takeoff speed
  speed  standing-start run: steady speed, time to 90% speed, and linear-ramp versus
         exponential-approach model fits
  none   positions only

Perspective caution: pixel motion is only metric when the motion is roughly parallel to the
image plane at a constant camera distance. Use side-on test clips, or convert third-person
tracks to world units with camera_solve.py ground. --scale-search follows a subject whose
apparent size changes and warns when one --px-per-unit cannot describe the whole clip.

Real footage: frames that repeat the previous position while the subject moves (30 fps content
in a 60 fps file) are dropped from the analyses and reported as content_fps; samples where the
anchor was lost, or the subject was lost (low score plus a jump or a stall), are excluded and
marked; the steady speed is checked half against half so slow drift widens its uncertainty; and
a track with more than 20% unusable samples is marked reliable: false, which ledger.py refuses.

Examples:
  python motion_track.py frames/jump/manifest.json --bbox 912,604,48,96 --px-per-unit 31.5 --unit studs --analyze jump --out tracks/jump.json
  python motion_track.py frames/run/manifest.json --bbox 300,500,40,80 --anchor-bbox 50,900,64,64 --analyze speed --out tracks/run.json
"""

from __future__ import annotations

import argparse
import csv
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import remake_common as rc  # noqa: E402

TOOL = "motion_track"
SCHEMA = 1


# ----------------------------------------------------------------- matching

def _integral(a):
    np = rc.require_numpy()
    return np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)


def _box_sum(ii, th, tw):
    return ii[th:, tw:] - ii[:-th, tw:] - ii[th:, :-tw] + ii[:-th, :-tw]


def ncc_map(search, tmpl):
    """Normalized cross-correlation of tmpl over every valid position in search, in [-1, 1].

    A window with (almost) no variance has no defined correlation: it scores 0. Before 1.4 the
    variance was floored at 1e-9, so FFT rounding error over a flat wall scored up to 7.8 and the
    tracker jumped onto it.
    """
    np = rc.require_numpy()
    th, tw = tmpl.shape
    sh, sw = search.shape
    if sh < th or sw < tw:
        rc.fail("search window is smaller than the template; increase --search or move the bbox inside the frame")
    t = tmpl.astype(np.float64) - tmpl.mean()
    tnorm = math.sqrt(float((t * t).sum()))
    if tnorm < 1e-9:
        rc.fail("the template has no texture (flat color); choose a bbox with visible detail")
    s = search.astype(np.float64)
    F = np.fft.rfft2(s)
    T = np.fft.rfft2(t[::-1, ::-1], s.shape)
    full = np.fft.irfft2(F * T, s.shape)
    num = full[th - 1:sh, tw - 1:sw]
    n = th * tw
    s1 = _box_sum(_integral(s), th, tw)
    s2 = _box_sum(_integral(s * s), th, tw)
    var = s2 - s1 * s1 / n
    # Flat: the window's standard deviation is under 1% of the template's (or under 0.001 grey levels).
    flat = var <= n * max(1e-6, 1e-4 * tnorm * tnorm / n)
    out = num / (np.sqrt(np.where(flat, 1.0, var)) * tnorm)
    out[flat] = 0.0
    return np.clip(out, -1.0, 1.0)


def _subpixel(m, y, x):
    def refine(a, b, c):
        denom = a - 2 * b + c
        return 0.0 if abs(denom) < 1e-12 else 0.5 * (a - c) / denom

    dy = refine(m[y - 1, x], m[y, x], m[y + 1, x]) if 0 < y < m.shape[0] - 1 else 0.0
    dx = refine(m[y, x - 1], m[y, x], m[y, x + 1]) if 0 < x < m.shape[1] - 1 else 0.0
    return max(-0.5, min(0.5, dy)), max(-0.5, min(0.5, dx))


def _resize(tmpl, w: int, h: int):
    np = rc.require_numpy()
    Image = rc.require_pil()
    return np.asarray(Image.fromarray(tmpl.astype(np.float32), mode="F").resize((w, h), Image.BILINEAR), dtype=np.float32)


def _peaks(m, floor: float, k: int = 6):
    """Local maxima of m (3x3) at or above floor, best first: [(value, y, x)]."""
    np = rc.require_numpy()
    p = np.pad(m, 1, constant_values=-np.inf)
    c = p[1:-1, 1:-1]
    is_max = np.ones(m.shape, bool)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                is_max &= c >= p[1 + dy:1 + dy + m.shape[0], 1 + dx:1 + dx + m.shape[1]]
    ys, xs = np.nonzero(is_max & (m >= floor))
    order = np.argsort(-m[ys, xs])[:k]
    return [(float(m[ys[i], xs[i]]), int(ys[i]), int(xs[i])) for i in order]


def _window(img, cx: float, cy: float, tw: int, th: int, r: int):
    """Search window around a template centred at (cx, cy) with radius r: (array, x0, y0), or None."""
    H, W = img.shape
    if tw > W or th > H:
        return None
    qx = min(max(cx, tw / 2.0), W - tw / 2.0)
    qy = min(max(cy, th / 2.0), H - th / 2.0)
    x0 = int(max(0, math.floor(qx - tw / 2.0 - r)))
    y0 = int(max(0, math.floor(qy - th / 2.0 - r)))
    x1 = int(min(W, math.ceil(qx + tw / 2.0 + r)))
    y1 = int(min(H, math.ceil(qy + th / 2.0 + r)))
    if x1 - x0 < tw or y1 - y0 < th:
        return None
    return img[y0:y1, x0:x1], x0, y0


def _patch(img, cx: float, cy: float, tw: int, th: int):
    """The tw x th patch centred (to the nearest pixel) at (cx, cy), or None when it leaves the image."""
    x0, y0 = int(round(cx - tw / 2.0)), int(round(cy - th / 2.0))
    if x0 < 0 or y0 < 0 or x0 + tw > img.shape[1] or y0 + th > img.shape[0]:
        return None
    return img[y0:y0 + th, x0:x0 + tw]


# ----------------------------------------------------------------- camera motion
#
# A camera transform S = (a, b, tx, ty) maps where a static point of the scene was on the FIRST
# frame to where it is on frame i:  x' = a x - b y + tx,  y' = b x + a y + ty.
# scale = hypot(a, b) is the zoom (FOV change or dolly), roll = atan2(b, a). This similarity is exact
# for a FOV change and for roll, and a good model for pans across distant scenery. It does not
# model parallax: when the camera itself travels, near and far scenery shift by different amounts.

IDENTITY = (1.0, 0.0, 0.0, 0.0)


def sim_apply(S, x, y):
    a, b, tx, ty = S
    return a * x - b * y + tx, b * x + a * y + ty


def sim_inverse(S):
    a, b, tx, ty = S
    k = a * a + b * b
    ia, ib = a / k, -b / k
    return (ia, ib, -(ia * tx - ib * ty), -(ib * tx + ia * ty))


def sim_compose(S2, S1):
    """S2 after S1."""
    a2, b2, _, _ = S2
    a1, b1, tx1, ty1 = S1
    tx, ty = sim_apply(S2, tx1, ty1)
    return (a2 * a1 - b2 * b1, a2 * b1 + b2 * a1, tx, ty)


def sim_scale(S) -> float:
    return math.hypot(S[0], S[1])


def sim_roll_deg(S) -> float:
    return math.degrees(math.atan2(S[1], S[0]))


def sim_rescale(S, k: float):
    """The same transform in coordinates multiplied by k (pixels of a k-times larger image)."""
    return (S[0], S[1], S[2] * k, S[3] * k)


def fit_similarity(src, dst):
    """Least-squares similarity mapping src (N, 2) onto dst (N, 2)."""
    np = rc.require_numpy()
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    M = np.zeros((2 * n, 4))
    M[0::2, 0], M[0::2, 1], M[0::2, 2] = src[:, 0], -src[:, 1], 1.0
    M[1::2, 0], M[1::2, 1], M[1::2, 3] = src[:, 1], src[:, 0], 1.0
    sol = np.linalg.lstsq(M, dst.reshape(-1), rcond=None)[0]
    return tuple(float(v) for v in sol)


def robust_similarity(src, dst, thr: float, iters: int = 150, seed: int = 0):
    """RANSAC similarity (2-point samples) refined by least squares on the inliers.

    Returns (S, inlier mask, rms residual of the inliers) or None. Points on movers, the HUD and
    the subject disagree with the scenery and drop out as outliers, as long as the scenery has
    the largest consistent set of points.
    """
    np = rc.require_numpy()
    src, dst = np.asarray(src, float), np.asarray(dst, float)
    n = len(src)
    if n < 3:
        return None
    zs, zd = src[:, 0] + 1j * src[:, 1], dst[:, 0] + 1j * dst[:, 1]
    rng = np.random.default_rng(seed)
    best, best_n = None, 0
    pairs = rng.integers(0, n, size=(iters, 2))
    # Always try pure translation by the median shift too (the common case, and robust with few points).
    cands = [(1.0 + 0j, complex(np.median(zd - zs).real, np.median((zd - zs).imag)))]
    for i, j in pairs:
        if i == j or abs(zs[i] - zs[j]) < 1e-6:
            continue
        c = (zd[i] - zd[j]) / (zs[i] - zs[j])
        if not 0.5 < abs(c) < 2.0:
            continue
        cands.append((c, zd[i] - c * zs[i]))
    for c, t in cands:
        inl = np.abs(c * zs + t - zd) < thr
        k = int(inl.sum())
        if k > best_n:
            best, best_n = inl, k
    if best is None or best_n < 3:
        return None
    inl = best
    S = IDENTITY
    for _ in range(3):
        S = fit_similarity(src[inl], dst[inl])
        px, py = sim_apply(S, src[:, 0], src[:, 1])
        res = np.hypot(px - dst[:, 0], py - dst[:, 1])
        new = res < thr
        if new.sum() < 3:
            break
        inl = new
    S = fit_similarity(src[inl], dst[inl])
    px, py = sim_apply(S, src[:, 0], src[:, 1])
    res = np.hypot(px - dst[:, 0], py - dst[:, 1])
    return S, inl, float(np.sqrt((res[inl] ** 2).mean()))


def phase_correlate(a, b):
    """Sub-pixel (dx, dy) such that the content of a appears at +(dx, dy) in b, and the peak strength."""
    np = rc.require_numpy()
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    A = np.fft.fft2((a - a.mean()) * win)
    B = np.fft.fft2((b - b.mean()) * win)
    R = B * np.conj(A)
    R /= np.abs(R) + 1e-9
    r = np.fft.ifft2(R).real
    iy, ix = np.unravel_index(int(np.argmax(r)), r.shape)
    h, w = r.shape

    def ref(m1, m0, p1):
        den = m1 - 2 * m0 + p1
        return 0.0 if abs(den) < 1e-12 else max(-0.5, min(0.5, 0.5 * (m1 - p1) / den))

    fy = ref(r[(iy - 1) % h, ix], r[iy, ix], r[(iy + 1) % h, ix])
    fx = ref(r[iy, (ix - 1) % w], r[iy, ix], r[iy, (ix + 1) % w])
    dy, dx = iy + fy, ix + fx
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return float(dx), float(dy), float(r[iy, ix])


def _block_mean(img, k: int):
    if k <= 1:
        return img
    h, w = (img.shape[0] // k) * k, (img.shape[1] // k) * k
    return img[:h, :w].reshape(h // k, k, w // k, k).mean(axis=(1, 3))


class CameraMotion:
    """Whole-frame camera motion (shift, zoom, roll), estimated one frame at a time.

    Textured patches spread over a keyframe are matched in each new frame around where the
    previous motion predicts them; a robust similarity fit through the matches gives the
    keyframe-to-frame transform, and transforms chain through keyframes back to the first frame.
    A new keyframe is taken when the view has drifted (zoom over 6%, roll over 4 degrees, or under
    half of the patches still visible and matching), so error accumulates per keyframe, not per
    frame. Only the keyframe and the previous frame are kept, never the whole clip.

    Patches that stay put on screen while the camera moves (HUD) are learned and left out of later
    keyframes. Callers pass the subject's box to keep it out of the keyframe patches.

    update() returns a dict: S (first frame -> this frame, in the caller's pixels), ok (the fit
    is trustworthy), inliers, rms_px, keyframes, chain_ok (no unmeasured frame before this one).
    """

    def __init__(self, first, *, out_scale: float = 1.0, max_width: int = 640, patch: int = 24, step: int = 40,
                 radius: int = 8, max_points: int = 90):
        np = rc.require_numpy()
        self.k = max(1, int(math.ceil(first.shape[1] / max_width)))
        self.out = out_scale * self.k  # caller pixels per working pixel
        self.P, self.step, self.R, self.max_points = patch, step, radius, max_points
        w = _block_mean(np.asarray(first, np.float32), self.k)
        self.shape = w.shape
        self.hud = np.zeros(((w.shape[0] + step - 1) // step, (w.shape[1] + step - 1) // step), np.int32)
        self.S0 = IDENTITY            # first -> current, working pixels
        self.S_prev = IDENTITY        # first -> previous frame
        self.S_key = IDENTITY         # first -> keyframe
        self.prev_img = w
        self.keyframes = 1
        self.unmeasured = 0
        self.chain_ok = True
        self.fail_run = 0
        self._set_key(w, IDENTITY, ())

    def _to_work(self, box):
        x, y, w, h = box
        return (x / self.out, y / self.out, w / self.out, h / self.out)

    def _set_key(self, w, S_key, exclude):
        np = rc.require_numpy()
        P, st = self.P, self.step
        gy, gx = np.gradient(w)
        ixx = _box_sum(_integral(gx * gx), P, P)
        iyy = _box_sum(_integral(gy * gy), P, P)
        ixy = _box_sum(_integral(gx * gy), P, P)
        lam = ((ixx + iyy) / 2 - np.sqrt(((ixx - iyy) / 2) ** 2 + ixy ** 2)) / (P * P)  # Shi-Tomasi, per pixel
        pts = []
        H, W = w.shape
        for cy in range(0, H - P + 1, st):
            for cx in range(0, W - P + 1, st):
                if self.hud[min(self.hud.shape[0] - 1, (cy + P // 2) // st), min(self.hud.shape[1] - 1, (cx + P // 2) // st)] >= 3:
                    continue
                sub = lam[cy:min(cy + st, lam.shape[0]), cx:min(cx + st, lam.shape[1])]
                if sub.size == 0:
                    continue
                iy, ix = np.unravel_index(int(np.argmax(sub)), sub.shape)
                v = float(sub[iy, ix])
                if v < 4.0:  # too little texture (flat sky, walls, compression noise)
                    continue
                y0, x0 = cy + iy, cx + ix
                if any(x0 < ex + ew and ex < x0 + P and y0 < ey + eh and ey < y0 + P for ex, ey, ew, eh in exclude):
                    continue
                t = w[y0:y0 + P, x0:x0 + P]
                pts.append((v, x0 + P / 2.0, y0 + P / 2.0, t.copy()))
        pts.sort(key=lambda p: -p[0])
        self.pts = pts[: self.max_points]
        self.key_img_shape = w.shape
        self.S_key = S_key
        self.key_count = len(self.pts)

    def _match(self, w, S_rel, R):
        """Match keyframe patches into w around S_rel's prediction: (src, dst, idx)."""
        np = rc.require_numpy()
        s = sim_scale(S_rel)
        P = self.P
        tp = max(6, int(round(P * s)))
        src, dst, idx = [], [], []
        H, W = w.shape
        for n, (_, kx, ky, tmpl) in enumerate(self.pts):
            px, py = sim_apply(S_rel, kx, ky)
            if px - tp / 2 < 1 or py - tp / 2 < 1 or px + tp / 2 > W - 1 or py + tp / 2 > H - 1:
                continue
            t = tmpl if tp == P else _resize(tmpl, tp, tp)
            win = _window(w, px, py, tp, tp, R)
            if win is None:
                continue
            sw, x0, y0 = win
            m = ncc_map(sw, t)
            iy, ix = np.unravel_index(int(np.argmax(m)), m.shape)
            if m[iy, ix] < 0.6:
                continue
            fy, fx = _subpixel(m, iy, ix)
            src.append((kx, ky))
            dst.append((x0 + ix + fx + tp / 2.0, y0 + iy + fy + tp / 2.0))
            idx.append(n)
        return src, dst, idx

    def update(self, img, exclude=()):
        np = rc.require_numpy()
        w = _block_mean(np.asarray(img, np.float32), self.k)
        # Constant-motion prediction: the last frame-to-frame motion again.
        delta = sim_compose(self.S0, sim_inverse(self.S_prev))
        pred0 = sim_compose(delta, self.S0)
        key_inv = sim_inverse(self.S_key)
        fit = None
        for attempt in range(2):
            if attempt == 0:
                S_rel_pred, R = sim_compose(pred0, key_inv), self.R
            else:
                # Rescue (a fast whip pan or a stall): find the frame-to-frame shift by phase correlation.
                dx, dy, _ = phase_correlate(self.prev_img, w)
                S_rel_pred, R = sim_compose((1.0, 0.0, dx, dy), sim_compose(self.S0, key_inv)), 3 * self.R
            src, dst, idx = self._match(w, S_rel_pred, R)
            if len(src) >= 6:
                fit = robust_similarity(src, dst, thr=max(0.75, 0.02 * self.P))
            if fit and fit[1].sum() >= max(6, 0.3 * len(src)):
                break
            fit = None
        ok = fit is not None
        inliers, rms = 0, None
        if ok:
            S_rel, inl, rms = fit
            inliers = int(inl.sum())
            S0 = sim_compose(S_rel, self.S_key)
            # Learn screen-fixed patches (HUD): they stay put on screen while the camera moves.
            if len(src):
                src_a, dst_a = np.asarray(src), np.asarray(dst)
                static = np.hypot(*(dst_a - src_a).T) < 0.5
                cx_, cy_ = self.shape[1] / 2.0, self.shape[0] / 2.0
                mx, my = sim_apply(S_rel, cx_, cy_)
                if math.hypot(mx - cx_, my - cy_) > 2.0:
                    for (kx, ky), st_, good in zip(src_a, static, inl):
                        if st_ and not good:
                            self.hud[min(self.hud.shape[0] - 1, int(ky) // self.step),
                                     min(self.hud.shape[1] - 1, int(kx) // self.step)] += 1
            self.fail_run = 0
        else:
            S0 = pred0
            self.unmeasured += 1
            self.fail_run += 1
            self.chain_ok = False
        self.S_prev, self.S0 = self.S0, S0
        self.prev_img = w
        # New keyframe when the view drifted away from the keyframe or the matches thinned out.
        S_rel_now = sim_compose(S0, key_inv)
        if ok and (abs(sim_scale(S_rel_now) - 1) > 0.06 or abs(sim_roll_deg(S_rel_now)) > 4.0
                   or inliers < max(8, 0.5 * self.key_count)) or (not ok and self.fail_run >= 3):
            self._set_key(w, S0, [self._to_work(b) for b in exclude])
            self.keyframes += 1
        return {"S": sim_rescale(S0, self.out), "ok": ok, "inliers": inliers,
                "rms_px": None if rms is None else rms * self.out, "keyframes": self.keyframes, "chain_ok": self.chain_ok}


# ----------------------------------------------------------------- subject tracking

class Tracker:
    """Follow one template, a frame at a time, in the scene's coordinates.

    Each step gets the frame and the camera transform for it (first frame -> this frame). The
    subject's position is predicted at constant velocity in scene coordinates, so a camera that
    follows or zooms does not look like subject motion, and the template is scaled by the
    camera zoom. Then, at any match score:
      - among near-equal match peaks, the one that fits the motion so far wins (look-alikes);
      - a forward-backward check matches the found patch back into the previous frame; it must
        land where the subject was;
      - a jump larger than the subject itself, or an implausible move together with a weaker or
        ambiguous match, counts as losing the subject.
    A lost subject is not followed onto what replaced it: the prediction coasts, and the track
    resumes when a match agrees with it again (or re-locks after max_coast frames, flagged).
    A slowly updating template (10% per good frame) is matched together with the first-frame
    template, so animation does not wear the match down; scores are against the first frame.

    step() returns (x, y, score) in full-resolution pixels (plus scale with scale_search) and sets
    self.info = {fb_px, innovation_px, lost (reason or None), ambiguous, reacquired}.
    """

    def __init__(self, first, bbox, search: int, downscale: int, *, predict: bool = True, scale_search: bool = False,
                 checks: bool = True, adapt: float = 0.1, scale_step: float = 1.04, max_coast: int = 12, min_score: float = 0.6):
        d = max(1, downscale)
        x, y, w, h = bbox
        xs, ys, ws, hs = x // d, y // d, max(2, w // d), max(2, h // d)
        if ys + hs > first.shape[0] or xs + ws > first.shape[1] or xs < 0 or ys < 0:
            rc.fail(f"bbox {bbox} lies outside the first frame")
        self.d, self.ws, self.hs = d, ws, hs
        self.tmpl0 = first[ys:ys + hs, xs:xs + ws].astype("float32")
        self.tmpl_a = self.tmpl0.copy()
        self.r = max(2, search // d)
        self.predict, self.scale_search, self.checks, self.adapt = predict, scale_search, checks, adapt
        self.scale_step, self.max_coast, self.min_score = scale_step, max_coast, min_score
        self.q = (xs + ws / 2.0, ys + hs / 2.0)      # last accepted position, scene coordinates (working px)
        self.v = (0.0, 0.0)                           # scene velocity per frame
        self.n_acc = 1
        self.gap = 0                                  # frames since the last accepted position
        self.last_score = 1.0
        self.scale = 1.0                              # subject's own scale (camera zoom excluded)
        self.prev_img, self.prev_screen = first, self.q
        self.innov, self.fbs, self.scores, self.vh = [], [], [], []
        self.lost = None
        self.coast = 0
        self.cache: dict = {}
        self.info = {}

    def first(self):
        x, y = self.q
        return (x * self.d, y * self.d, 1.0, 1.0) if self.scale_search else (x * self.d, y * self.d, 1.0)

    def _sized(self, which, tw, th):
        if which == "0":
            key = (tw, th)
            if key not in self.cache:
                self.cache[key] = _resize(self.tmpl0, tw, th) if (tw, th) != (self.ws, self.hs) else self.tmpl0
            return self.cache[key]
        return _resize(self.tmpl_a, tw, th) if (tw, th) != (self.ws, self.hs) else self.tmpl_a

    def _typ(self, vals, default):
        np = rc.require_numpy()
        return float(np.median(vals[-15:])) if len(vals) >= 3 else default

    def step(self, img, S=IDENTITY):
        np = rc.require_numpy()
        d = self.d
        Sw = (S[0], S[1], S[2] / d, S[3] / d)
        cam_s = sim_scale(Sw)
        moving = self.predict and self.n_acc >= 2 and (self.last_score >= 0.5 or self.lost)
        k = self.gap + 1
        v = self.v
        if self.lost and len(self.vh) >= 3:
            # Coast on the median of the last three velocities: the last step before a loss is often off.
            v = (float(np.median([a for a, _ in self.vh[-3:]])), float(np.median([b for _, b in self.vh[-3:]])))
        qp = (self.q[0] + v[0] * k, self.q[1] + v[1] * k) if moving else self.q
        px, py = sim_apply(Sw, *qp)
        hyps = [(px, py)]
        r = self.r
        if self.lost:
            r += min(self.r, 2 * self.coast)
        if self.lost and "stalled" not in self.lost:
            # While lost, the subject either kept moving (coasting prediction) or stopped where it was last
            # seen (a landing, a stop behind cover): search both and accept a match that fits either. Not
            # after a stall: the stalled position is what replaced the subject.
            hyps.append(sim_apply(Sw, *self.q))
            r += int(math.ceil(math.hypot(hyps[1][0] - px, hyps[1][1] - py) / 2))
            px, py = (px + hyps[1][0]) / 2, (py + hyps[1][1]) / 2
        sizes = (self.scale / self.scale_step, self.scale, self.scale * self.scale_step) if self.scale_search else (self.scale,)
        innov_typ = self._typ(self.innov, 0.0)
        best = None
        for f in sizes:
            tw, th = max(4, int(round(self.ws * f * cam_s))), max(4, int(round(self.hs * f * cam_s)))
            win = _window(img, px, py, tw, th, r)
            if win is None:
                continue
            sw, x0, y0 = win
            m0 = ncc_map(sw, self._sized("0", tw, th))
            m = 0.5 * (m0 + ncc_map(sw, self._sized("a", tw, th))) if self.adapt else m0
            peaks = _peaks(m, float(m.max()) - 0.15, k=24)
            if not peaks:
                iy, ix = np.unravel_index(int(np.argmax(m)), m.shape)
                peaks = [(float(m[iy, ix]), int(iy), int(ix))]
            chosen, alt = peaks[0], None

            def dist(pk):
                return min(math.hypot(x0 + pk[2] + tw / 2.0 - hx, y0 + pk[1] + th / 2.0 - hy) for hx, hy in hyps)

            # The best match wins unless it breaks from the motion so far and a near-equal match fits it
            # (a look-alike crossing). Not always nearest-to-prediction: along a motion-blur streak that
            # would make the track oscillate.
            if moving and len(peaks) > 1 and dist(chosen) > max(2.0, 4.0 * innov_typ + 1.0):
                chosen = min([pk for pk in peaks if pk[0] >= peaks[0][0] - 0.06], key=dist)
            for pk in peaks:
                if pk is not chosen and chosen[0] >= self.min_score and pk[0] >= chosen[0] - 0.05 and math.hypot(pk[1] - chosen[1], pk[2] - chosen[2]) >= 3:
                    alt = pk
                    break
            val, iy, ix = chosen
            if best is None or val > best[0]:
                sdy, sdx = _subpixel(m, iy, ix)
                best = (val, x0 + ix + sdx + tw / 2.0, y0 + iy + sdy + th / 2.0, f, float(m0[iy, ix]), tw, th, alt is not None)
        if best is None:
            rc.fail("the template grew larger than the frame; disable --scale-search or use a smaller bbox", rc.EXIT_FAIL)
        _, cx, cy, f, score, tw, th, ambiguous = best
        innov = min(math.hypot(cx - hx, cy - hy) for hx, hy in hyps)
        # Forward-backward: the patch found here, matched back into the previous frame, must land where
        # the subject was. Near-equal back peaks (an identical look-alike) count as agreement.
        fb, fb_ok = None, True
        if self.checks:
            pt = _patch(img, cx, cy, tw, th)
            back = _window(self.prev_img, *self.prev_screen, tw, th, max(3, min(self.r, max(tw, th) // 2)))
            if pt is not None and back is not None and float(pt.std()) > 1e-3:
                bw, bx0, by0 = back
                mb = ncc_map(bw, pt)
                pks = _peaks(mb, float(mb.max()) - 0.05) or [(float(mb.max()),) + tuple(int(v) for v in np.unravel_index(int(np.argmax(mb)), mb.shape))]
                # Motion blur smears the match along the motion, so the back-match may land off along the
                # step by up to most of the step; across it the tolerance stays tight (a look-alike beside).
                sx, sy = cx - self.prev_screen[0], cy - self.prev_screen[1]
                step = math.hypot(sx, sy)
                ux, uy = (sx / step, sy / step) if step > 0.5 else (0.0, 0.0)
                base = max(2.0, 3.0 * self._typ(self.fbs, 0.5) + 1.0)
                fb_ok = False
                for j, p_ in enumerate(pks):
                    ex = bx0 + p_[2] + tw / 2.0 - self.prev_screen[0]
                    ey = by0 + p_[1] + th / 2.0 - self.prev_screen[1]
                    if j == 0:
                        fb = math.hypot(ex, ey)
                    along, across = abs(ex * ux + ey * uy), abs(ex * uy - ey * ux)
                    if (along <= base + 0.6 * step and across <= base) if step > 0.5 else math.hypot(ex, ey) <= base:
                        fb_ok = True
        reason = None
        size = min(tw, th)
        q_new = sim_apply(sim_inverse(Sw), cx, cy)
        score_typ = self._typ(self.scores, 1.0)
        weak = score < max(self.min_score, score_typ - 0.1)
        if self.checks and self.n_acc >= 2 and self.lost is None:
            if innov > 1.5 * max(tw, th) + 2 * innov_typ:
                reason = "position jumped further than the subject's size"
            elif not fb_ok:
                reason = "forward-backward check failed"
            elif weak and moving and math.hypot(*self.v) > 1.5 and innov > max(3.0, 4 * innov_typ + 2) and \
                    math.hypot(q_new[0] - self.q[0], q_new[1] - self.q[1]) < 0.3 * math.hypot(*self.v) * (self.gap + 1):
                reason = "the match weakened and the position stalled while the motion continued"
            elif ambiguous and innov > max(0.4 * size, 6 * innov_typ + 2):
                reason = "implausible motion with an ambiguous match"
        reacquired = False
        if self.lost is not None:
            base = max(3.0, 4 * innov_typ + 2)
            # On the coasting path the gate widens as the coast gets longer; where it stopped, it does not.
            fits = math.hypot(cx - hyps[0][0], cy - hyps[0][1]) <= base + 0.5 * self.coast or \
                (len(hyps) > 1 and math.hypot(cx - hyps[1][0], cy - hyps[1][1]) <= base)
            if fits and score >= max(0.5 * self.min_score, score_typ - 0.3) and fb_ok:
                reason = None  # back on the predicted path (or where it stopped): resumed
            elif not fits and self.coast >= self.max_coast and score >= self.min_score and not weak:
                reacquired = True  # re-lock on appearance alone; the caller flags it
            else:
                reason = self.lost
        if reason is None:
            if self.n_acc >= 1 and not reacquired:
                kk = self.gap + 1
                self.v = ((q_new[0] - self.q[0]) / kk, (q_new[1] - self.q[1]) / kk)
                self.vh.append(self.v)
            else:
                self.v = (0.0, 0.0)
            self.q, self.gap, self.n_acc = q_new, 0, self.n_acc + 1
            if not reacquired and self.lost is None:
                self.innov.append(innov)
                if fb is not None:
                    self.fbs.append(fb)
                self.scores.append(score)
            self.lost, self.coast = None, 0
            self.scale = f
            if self.adapt and score >= max(0.7, self.min_score) and not ambiguous:
                pt = _patch(img, cx, cy, tw, th)
                if pt is not None:
                    pa = pt if (tw, th) == (self.ws, self.hs) else _resize(pt, self.ws, self.hs)
                    self.tmpl_a = (1 - self.adapt) * self.tmpl_a + self.adapt * pa
            self.prev_screen = (cx, cy)
        else:
            self.lost, self.gap, self.coast = reason, self.gap + 1, self.coast + 1
            self.prev_screen = (cx, cy)
        self.prev_img = img
        self.last_score = score
        self.info = {"fb_px": None if fb is None else fb * d, "innovation_px": innov * d, "lost": reason,
                     "ambiguous": bool(ambiguous), "reacquired": reacquired}
        sc_out = f * cam_s
        return (cx * d, cy * d, score, sc_out) if self.scale_search else (cx * d, cy * d, score)


def track(frames, bbox, search: int, downscale: int, predict: bool = True, scale_search: bool = False):
    """Return [(cx, cy, score)] in full-resolution pixels for each frame (any iterable of frames).

    With scale_search, each frame also tries the template at 4% smaller and larger sizes than the
    previous match, and returns [(cx, cy, score, scale)]; use it when the subject moves toward or
    away from the camera. No camera compensation; see Tracker for the per-frame checks.
    """
    out, tr = [], None
    for img in frames:
        if tr is None:
            tr = Tracker(img, bbox, search, downscale, predict=predict, scale_search=scale_search)
            out.append(tr.first())
        else:
            out.append(tr.step(img))
    return out


# ----------------------------------------------------------------- analyses

def _runs(mask):
    runs, start = [], None
    for i, v in enumerate(mask):
        if v and start is None:
            start = i
        elif not v and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(mask) - 1))
    return runs


def analyze_jump(t, v, unit: str, px_unit: float, fps: float, air_range=None) -> dict:
    np = rc.require_numpy()
    t = np.asarray(t, float)
    v = np.asarray(v, float)
    n0 = max(3, len(v) // 10)
    ground = float(np.median(v[:n0]))
    noise = float(np.median(np.abs(v[:n0] - ground)) * 1.4826)
    eps = max(3 * noise, 1.5 * px_unit)
    if air_range:
        i0, i1 = air_range
    else:
        runs = _runs(v > ground + eps)
        if not runs:
            rc.fail("no airborne segment found; pass --air-range first,last (sample indexes) or check the track", rc.EXIT_FAIL)
        i0, i1 = max(runs, key=lambda r: r[1] - r[0])
    if i1 - i0 + 1 < 5:
        rc.fail("airborne segment has fewer than 5 samples; extract every frame of the jump", rc.EXIT_FAIL)
    ts, vs = t[i0:i1 + 1] - t[i0], v[i0:i1 + 1]
    # Fit airborne samples only. A grounded sample just before takeoff or after landing is not on the
    # flight parabola unless takeoff falls exactly on a frame; including it biased the rise and fall
    # gravities whenever it did not (variable frame rate, dropped frames, 30 fps content).
    (a, b, c), cov = np.polyfit(ts, vs, 2, cov=True)
    if a >= 0:
        rc.fail("airborne segment is not concave (no deceleration); the tracked feature may be wrong", rc.EXIT_FAIL)

    def roots(pa, pb, pc):
        disc = pb * pb - 4 * pa * (pc - ground)
        if disc <= 0:
            rc.fail("could not intersect the jump parabola with the ground level", rc.EXIT_FAIL)
        r1 = (-pb + math.sqrt(disc)) / (2 * pa)
        r2 = (-pb - math.sqrt(disc)) / (2 * pa)
        return min(r1, r2), max(r1, r2)

    # Iterated piecewise fit: rise and fall get separate parabolas whose vertices meet at the apex.
    # This is unbiased for games that fall faster than they rise.
    ta = -b / (2 * a)
    piece = None
    for _ in range(4):
        up, down = ts <= ta, ts >= ta
        if up.sum() < 4 or down.sum() < 4:
            break
        (ar, br, cr), cov_r = np.polyfit(ts[up], vs[up], 2, cov=True)
        (af, bf, cf), cov_f = np.polyfit(ts[down], vs[down], 2, cov=True)
        if ar >= 0 or af >= 0:
            break
        ta_r, ta_f = -br / (2 * ar), -bf / (2 * af)
        piece = (ar, br, cr, af, bf, cf, ta_r, ta_f, cov_r, cov_f)
        ta = 0.5 * (ta_r + ta_f)

    res = {"segment_samples": [int(i0), int(i1)], "ground_level": round(ground, 4), "unit": unit}
    if piece:
        ar, br, cr, af, bf, cf, ta_r, ta_f, cov_r, cov_f = piece
        h_r = cr - br * br / (4 * ar) - ground
        h_f = cf - bf * bf / (4 * af) - ground
        h = 0.5 * (h_r + h_f)
        t_take = roots(ar, br, cr)[0]
        t_land = roots(af, bf, cf)[1]
        rise, fall = ta_r - t_take, t_land - ta_f
        model = np.where(ts <= ta, ar * ts * ts + br * ts + cr, af * ts * ts + bf * ts + cf)
        res.update({
            "method": "piecewise",
            "apex_height": round(h, 4),
            "apex_height_rise_fit": round(h_r, 4),
            "apex_height_fall_fit": round(h_f, 4),
            "rise_time_s": round(rise, 4),
            "fall_time_s": round(fall, 4),
            "airtime_s": round(t_land - t_take, 4),
            "g_rise": round(-2 * ar, 4),
            "g_rise_std": round(2 * math.sqrt(max(cov_r[0, 0], 0.0)), 4),
            "g_fall": round(-2 * af, 4),
            "g_fall_std": round(2 * math.sqrt(max(cov_f[0, 0], 0.0)), 4),
            "takeoff_speed": round(-2 * ar * (ta_r - t_take), 4),
        })
    else:
        h = c - b * b / (4 * a) - ground
        t_take, t_land = roots(a, b, c)
        ta = -b / (2 * a)
        rise, fall = ta - t_take, t_land - ta
        model = a * ts * ts + b * ts + c
        res.update({
            "method": "single-parabola (too few samples for separate rise/fall fits; assumes symmetric gravity)",
            "apex_height": round(h, 4),
            "rise_time_s": round(rise, 4),
            "fall_time_s": round(fall, 4),
            "airtime_s": round(t_land - t_take, 4),
            "g_rise": round(-2 * a, 4),
            "g_fall": round(-2 * a, 4),
            "takeoff_speed": round(-2 * a * rise, 4),
        })
    res["gravity_single_fit"] = round(-2 * a, 4)
    res["gravity_single_fit_std"] = round(2 * math.sqrt(max(cov[0, 0], 0.0)), 4)
    res["fit_rms"] = round(float(np.sqrt(((vs - model) ** 2).mean())), 5)
    res["time_precision_s"] = round(1.0 / fps, 5) if fps else None
    if res["g_rise"] and res["g_fall"]:
        ratio = res["g_fall"] / res["g_rise"]
        res["fall_gravity_multiplier"] = round(ratio, 4)
        res["asymmetric"] = bool(abs(ratio - 1.0) > 0.1)
    return res


def _fit_onset_model(tt, ss, V, kind: str, dt: float, t_hint: float):
    """Grid-fit (start time, ramp parameter) for a standing-start displacement curve."""
    np = rc.require_numpy()

    def model(ts, P):
        x = np.clip(tt[None, None, :] - ts[:, None, None], 0.0, None)
        if kind == "linear":
            T = P[None, :, None]
            return np.where(x < T, V * x * x / (2 * T), V * (x - T / 2))
        tau = P[None, :, None]
        return V * (x - tau * (1 - np.exp(-x / tau)))

    def search(ts_grid, p_grid):
        # In blocks of start times, so memory stays bounded on long clips (one block is ~16 x grid x samples).
        err = np.concatenate([np.sqrt(((model(ts_grid[i:i + 16], p_grid) - ss[None, None, :]) ** 2).mean(axis=2))
                              for i in range(0, len(ts_grid), 16)])
        i, j = np.unravel_index(int(np.argmin(err)), err.shape)
        return float(ts_grid[i]), float(p_grid[j]), float(err[i, j])

    ts_grid = np.arange(t_hint - 1.0, t_hint + dt, dt / 2)
    p_grid = np.arange(dt / 2, 2.0, dt / 2)
    t_s, P, _ = search(ts_grid, p_grid)
    ts_fine = np.arange(t_s - dt, t_s + dt, dt / 16)
    p_fine = np.arange(max(dt / 16, P - dt), P + dt, dt / 16)
    return search(ts_fine, p_fine)


def analyze_speed(t, u, unit: str, px_unit: float, fps: float) -> dict:
    np = rc.require_numpy()
    t = np.asarray(t, float)
    u = np.asarray(u, float)
    direction = 1.0 if u[-1] >= u[0] else -1.0
    s = (u - u[0]) * direction
    n0 = max(3, len(s) // 10)
    noise = float(np.median(np.abs(s[:n0] - np.median(s[:n0]))) * 1.4826)
    eps = max(3 * noise, 1.5 * px_unit)
    moving = np.nonzero(s > eps)[0]
    if len(moving) == 0:
        rc.fail("no motion detected", rc.EXIT_FAIL)
    k = int(moving[0])
    notes = []
    if k <= 1:
        notes.append("motion starts at the first samples: the start time is extrapolated, so treat t90 with care")
    if len(t) - k < 8:
        rc.fail("too few samples after motion starts; extract more frames", rc.EXIT_FAIL)
    tail = max(4, int((len(t) - k) * 0.4))
    if tail >= 4:
        (V, _), vcov = np.polyfit(t[-tail:], s[-tail:], 1, cov=True)
        v_std = float(np.sqrt(max(vcov[0, 0], 0.0)))
    else:
        V, _ = np.polyfit(t[-tail:], s[-tail:], 1)
        v_std = 0.0
    V = float(V)
    if V <= 0:
        rc.fail("could not fit a positive steady speed", rc.EXIT_FAIL)
    # Split-half check: a tracker or anchor that drifts slowly bends the tail without adding scatter,
    # so the fit's own std understates the error. Fit each half of the tail and widen the
    # uncertainty to cover their disagreement.
    split = None
    if tail >= 8:
        h = tail // 2
        v1 = float(np.polyfit(t[-tail:-tail + h], s[-tail:-tail + h], 1)[0])
        v2 = float(np.polyfit(t[-h:], s[-h:], 1)[0])
        split = [round(v1, 4), round(v2, 4)]
        if abs(v1 - v2) / 2 > v_std:
            notes.append(f"the two halves of the steady segment disagree ({v1:.3f} vs {v2:.3f}): the track drifts or the "
                         "speed is not steady; the uncertainty covers the difference")
            v_std = abs(v1 - v2) / 2
    dt = 1.0 / (fps or 60.0)
    lin_ts, lin_T, lin_rms = _fit_onset_model(t, s, V, "linear", dt, float(t[k]))
    exp_ts, exp_tau, exp_rms = _fit_onset_model(t, s, V, "exponential", dt, float(t[k]))
    preferred = "linear_ramp" if lin_rms <= exp_rms else "exponential"
    t_start = lin_ts if preferred == "linear_ramp" else exp_ts
    t90_model = 0.9 * lin_T if preferred == "linear_ramp" else exp_tau * math.log(10)
    # The ramp fit depends on the steady speed: carry its uncertainty into t90.
    t90_unc = dt
    if v_std > 0.002 * V:
        kind = "linear" if preferred == "linear_ramp" else "exponential"
        for vv in (V - v_std, V + v_std):
            _, p_alt, _ = _fit_onset_model(t, s, vv, kind, dt, float(t[k]))
            alt = 0.9 * p_alt if kind == "linear" else p_alt * math.log(10)
            t90_unc = max(t90_unc, abs(alt - t90_model))
    vel = np.gradient(s, t)
    if len(vel) >= 3:
        vel = np.convolve(vel, np.ones(3) / 3, mode="same")
    reach = np.nonzero((vel >= 0.9 * V) & (t > t_start))[0]
    t90_samples = float(t[reach[0]] - t_start) if len(reach) else None
    return {
        "unit": unit,
        "first_moving_sample": k,
        "motion_start_s": round(t_start, 4),
        "steady_speed": round(V, 4),
        "steady_speed_std": round(v_std, 5),
        "steady_speed_halves": split,
        "t90_s": round(t90_model, 4),
        "t90_uncertainty_s": round(t90_unc, 5),
        "t90_from_samples_s": round(t90_samples, 4) if t90_samples is not None else None,
        "linear_ramp": {"start_s": round(lin_ts, 4), "time_to_full_s": round(lin_T, 4),
                        "acceleration": round(V / lin_T, 4), "rms": round(lin_rms, 5)},
        "exponential": {"start_s": round(exp_ts, 4), "tau_s": round(exp_tau, 4), "rms": round(exp_rms, 5)},
        "preferred_model": preferred,
        "time_precision_s": round(dt, 5),
        "notes": notes,
    }


def repeated_frames(xs, ys, fps: float):
    """Detect content that updates slower than the container (30 fps game in a 60 fps file).

    While the subject moves (mean step over 4 frames > 0.5 px), a frame whose tracked position
    equals the previous one (< 0.15 px) repeats stale content. Returns (keep mask, effective
    content fps or None, repeat ratio while moving). Only acts when more than 25% of moving
    frames repeat, so a slow apex or integer-pixel staircase in clean footage is left alone.
    """
    np = rc.require_numpy()
    xs, ys = np.asarray(xs, float), np.asarray(ys, float)
    d = np.r_[np.inf, np.hypot(np.diff(xs), np.diff(ys))]
    dd = np.where(np.isfinite(d), d, 0.0)
    mean4 = np.convolve(dd, np.ones(4) / 4, mode="same")
    moving = mean4 > 0.5
    moving[0] = False
    if moving.sum() < 6:
        return np.ones(len(xs), bool), None, 0.0
    rep = (d < 0.15) & moving
    ratio = float(rep[moving].mean())
    if ratio <= 0.25:
        return np.ones(len(xs), bool), None, ratio
    return ~rep, fps * (1 - ratio), ratio


def unusable_samples(samples, min_score: float, has_anchor: bool):
    """Samples to leave out of the analyses, with the reason.

    - camera motion not measured: the whole-frame camera fit failed on that frame (or an earlier
      failure broke the chain back to the first frame), so the scene position is unknown
    - anchor lost: the static anchor matched below min_score and nothing could take over from it
      (with the whole-frame camera model the anchor hands off instead; see anchor_handoff)
    - subject lost (tracker): the tracker's own checks failed at any score: a forward-backward
      mismatch, a jump larger than the subject, or an implausible move with a weaker or ambiguous
      match; it stays lost until a match agrees with the predicted motion again
    - subject lost: the subject matched below min_score AND its position is inconsistent with the
      rest of the track (a jump far larger than the typical step, or standing still in the middle
      of a movement). A low score with smooth motion, as with motion blur, is kept.
    Positions are compared after camera compensation whenever the samples carry it.
    """
    np = rc.require_numpy()
    n = len(samples)
    x = np.array([s["x_px"] - s.get("x_cam_px", 0.0) for s in samples], float)
    y = np.array([s["y_px"] - s.get("y_cam_px", 0.0) for s in samples], float)
    steps = np.r_[0.0, np.hypot(np.diff(x), np.diff(y))]
    moving_steps = steps[steps > 0.5]
    typical = float(np.median(moving_steps)) if len(moving_steps) else 0.0
    reasons: dict[int, str] = {}
    for i, s in enumerate(samples):
        if i and s.get("cam_ok") is False:
            reasons[i] = "camera motion not measured"
            continue
        if has_anchor and s.get("anchor_score") is not None and s["anchor_score"] < min_score and not s.get("anchor_handoff"):
            reasons[i] = "anchor lost"
            continue
        if s.get("lost"):
            reasons[i] = f"subject lost ({s['lost']})"
            continue
        if s["score"] >= min_score or i == 0:
            continue
        lo, hi = max(1, i - 3), min(n, i + 4)
        around = [steps[j] for j in range(lo, hi) if j != i]
        local = float(np.median(around)) if around else typical
        if steps[i] > 4 * max(local, typical) + 3:
            reasons[i] = "subject lost (position jumped)"
        elif typical > 1.0 and steps[i] < 0.2 and local < 0.2 and (i + 1 >= n or samples[i + 1]["score"] < min_score):
            reasons[i] = "subject lost (stalled while the motion continued)"
    # Once the subject is lost, later low-score samples stay lost until a good match returns.
    lost = False
    for i, s in enumerate(samples):
        if reasons.get(i, "").startswith("subject lost"):
            lost = True
        elif s["score"] >= min_score:
            lost = False
        elif lost:
            reasons.setdefault(i, "subject lost (after a jump or stall)")
    return reasons


# ----------------------------------------------------------------- clip tracking (streamed)

def track_clip(frames, bbox, abox, mode: str, args) -> dict:
    """One pass over the frames (only the current, previous and camera keyframe are kept in memory).

    mode: global (whole-frame camera model), anchor (anchor for the shift, whole-frame model for zoom
    and roll and as the hand-off when the anchor is lost), none (fixed camera; an anchor, if given,
    cancels shifts only, as before 1.4). Returns per-frame raw measurements; compensate() turns them
    into scene positions.
    """
    ds = max(1, args.downscale)
    sub = anc = cam = None
    rows = []
    for i, img in enumerate(frames):
        if i == 0:
            sub = Tracker(img, bbox, args.search, ds, scale_search=args.scale_search, min_score=args.min_score)
            if mode in ("global", "anchor"):
                cam = CameraMotion(img, out_scale=ds)
            if abox:
                anc = Tracker(img, abox, args.search, ds, checks=False, adapt=0.0, min_score=args.min_score,
                              scale_search=cam is None, scale_step=1.02)
            H, W = img.shape[0] * ds, img.shape[1] * ds
            p = sub.first()
            rows.append({"p": p, "S": IDENTITY, "cam_ok": True, "info": {}, "a": anc.first() if anc else None, "a_in": True})
            continue
        S_prev = rows[-1]["S"]
        cs = sim_scale(S_prev) * sub.scale
        px, py = rows[-1]["p"][0], rows[-1]["p"][1]
        bw, bh = bbox[2] * cs * 1.5 + 16, bbox[3] * cs * 1.5 + 16
        cinfo = cam.update(img, [(px - bw / 2, py - bh / 2, bw, bh)]) if cam else None
        S = cinfo["S"] if cinfo else IDENTITY
        a, a_in = None, True
        if anc:
            a = anc.step(img, S)
            asz = (sim_scale(S) if cam else a[3]) * 1.0
            ax0, ay0 = a[0] - abox[2] * asz / 2, a[1] - abox[3] * asz / 2
            a_in = ax0 >= 0 and ay0 >= 0 and ax0 + abox[2] * asz <= W and ay0 + abox[3] * asz <= H
        # The subject's prediction uses the best camera estimate available this frame.
        S_sub = S
        if anc and (cam is None or not cinfo["ok"]) and a[2] >= args.min_score and a_in:
            k = a[3] if cam is None else sim_scale(S)
            S_sub = (k, 0.0, a[0] - k * rows[0]["a"][0], a[1] - k * rows[0]["a"][1])
        p = sub.step(img, S_sub)
        rows.append({"p": p, "S": S, "cam_ok": bool(cinfo["ok"] and cinfo["chain_ok"]) if cinfo else True,
                     "cam_inliers": cinfo["inliers"] if cinfo else None, "cam_rms": cinfo["rms_px"] if cinfo else None,
                     "info": dict(sub.info), "a": a, "a_in": a_in})
    return {"rows": rows, "camera": cam, "size": (W, H)}


def compensate(raw: dict, mode: str, abox, min_score: float) -> dict:
    """Per-frame camera transforms actually applied, and a summary of the camera motion."""
    np = rc.require_numpy()
    rows = raw["rows"]
    cam = raw["camera"]
    W, H = raw["size"]
    n = len(rows)
    ok = [r["cam_ok"] for r in rows]
    Sg = [r["S"] for r in rows]
    okS = [S for S, o in zip(Sg, ok) if o] or [IDENTITY]
    scales = [sim_scale(S) for S in okS]
    rolls = [sim_roll_deg(S) for S in okS]

    def shift(S):  # how far the frame centre moved
        x, y = sim_apply(S, W / 2.0, H / 2.0)
        return math.hypot(x - W / 2.0, y - H / 2.0)

    zoom_span = max(scales) / min(scales)
    roll_span = max(rolls) - min(rolls)
    measured = cam is not None and sum(ok[1:]) > 0 and any(r.get("cam_inliers") for r in rows[1:])
    zoom_on = measured and (zoom_span > 1.004 or roll_span > 0.1)
    summary = {"mode": mode, "model": "similarity: shift, zoom, roll" if cam else ("anchor shift" if abox else "fixed camera"),
               "measured": bool(measured) if cam else False}
    applied = [IDENTITY] * n
    handoff = None
    a_scale_span = None
    if mode == "global":
        moves = measured and (max(shift(S) for S in okS) > 0.3 or zoom_on)
        if moves:
            applied = list(Sg)
        summary["moves"] = bool(moves)
    else:  # anchor, or none with an anchor
        if abox:
            a0 = rows[0]["a"]
            if cam is None:
                a_sc = [r["a"][3] for r in rows]
                a_scale_span = max(a_sc) / min(a_sc)
            for i, r in enumerate(rows):
                a = r["a"]
                good = a[2] >= min_score and r["a_in"]
                if handoff is None and i and not good and cam is not None and r["cam_ok"]:
                    handoff = i
                if handoff is not None and i >= handoff:
                    # Continue from the whole-frame model, offset so the camera path stays continuous.
                    L = handoff - 1
                    AL, AI = applied[L], Sg[i]
                    dl = (AL[2] - Sg[L][2], AL[3] - Sg[L][3])
                    ab = sim_compose((AI[0], AI[1], 0.0, 0.0), sim_inverse((Sg[L][0], Sg[L][1], 0.0, 0.0)))
                    dx, dy = sim_apply(ab, *dl)
                    applied[i] = (AI[0], AI[1], AI[2] + dx, AI[3] + dy)
                    continue
                if cam is not None and zoom_on and r["cam_ok"]:
                    A = (Sg[i][0], Sg[i][1])
                else:
                    A = (1.0, 0.0)
                tx = a[0] - (A[0] * a0[0] - A[1] * a0[1])
                ty = a[1] - (A[1] * a0[0] + A[0] * a0[1])
                applied[i] = (A[0], A[1], tx, ty)
        summary["moves"] = bool(abox) and max(shift(S) for S in applied) > 0.3 or zoom_on
    summary.update({
        "applied": any(S != IDENTITY for S in applied),
        "max_shift_px": round(max(shift(S) for S in (Sg if cam else applied)), 2),
        "zoom_range": [round(min(scales), 5), round(max(scales), 5)] if cam else None,
        "roll_range_deg": [round(min(rolls), 3), round(max(rolls), 3)] if cam else None,
    })
    if cam is not None:
        inl = [r["cam_inliers"] for r in rows[1:] if r.get("cam_inliers")]
        rms = [r["cam_rms"] for r in rows[1:] if r.get("cam_rms") is not None]
        summary.update({"keyframes": cam.keyframes, "unmeasured_frames": int(sum(1 for o in ok[1:] if not o)),
                        "median_inliers": int(np.median(inl)) if inl else 0,
                        "median_fit_rms_px": round(float(np.median(rms)), 3) if rms else None})
    if abox:
        summary["anchor_handoff_sample"] = handoff
    if a_scale_span is not None:
        summary["anchor_scale_range"] = round(a_scale_span, 4)
    return {"applied": applied, "summary": summary, "zoom_span": zoom_span if cam else (a_scale_span or 1.0),
            "zoom_removed": cam is not None, "handoff": handoff}


# ----------------------------------------------------------------- cli

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifest", type=Path, help="extract_frames manifest.json (or its directory)")
    ap.add_argument("--bbox", required=True, help="x,y,w,h of the tracked feature on the first frame")
    ap.add_argument("--anchor-bbox", help="x,y,w,h of a static background feature: its position gives the camera shift")
    ap.add_argument("--camera", choices=["auto", "global", "anchor", "none"], default="auto",
                    help="camera compensation. global: whole-frame shift, zoom and roll; anchor: the --anchor-bbox shift with "
                         "the whole-frame zoom and roll, handing off to the whole-frame model when the anchor is lost; none: "
                         "a fixed camera (with --anchor-bbox: its shift only, the pre-1.4 behaviour); auto (default): "
                         "anchor with --anchor-bbox, else global")
    ap.add_argument("--search", type=int, default=64, help="search radius in pixels around the predicted position (default 64)")
    ap.add_argument("--downscale", type=int, default=1, help="integer downscale for speed (default 1)")
    ap.add_argument("--px-per-unit", type=float, help="pixels per world unit at the subject's depth")
    ap.add_argument("--unit", default="studs", help="name of the world unit (default studs)")
    ap.add_argument("--analyze", choices=["jump", "speed", "none"], default="none")
    ap.add_argument("--air-range", help="first,last sample indexes of the airborne segment (jump analysis override)")
    ap.add_argument("--min-score", type=float, default=0.6, help="warn when match scores fall below this (default 0.6)")
    ap.add_argument("--scale-search", action="store_true",
                    help="also track the subject's apparent size (subjects moving toward or away from the camera)")
    ap.add_argument("--out", type=Path, help="write JSON results here")
    ap.add_argument("--csv", type=Path, help="also write per-frame samples as CSV")
    args = ap.parse_args()

    np = rc.require_numpy()
    manifest, frames_meta, base = rc.load_manifest(args.manifest)
    bbox = rc.parse_bbox(args.bbox, "--bbox")
    if manifest.get("crop"):
        cx0, cy0 = manifest["crop"][0], manifest["crop"][1]
        print(f"note: frames were cropped at {cx0},{cy0}; --bbox is relative to the cropped frames", file=sys.stderr)
    times = [float(fr.get("pts_time", i / 60.0)) for i, fr in enumerate(frames_meta)]
    if len(frames_meta) < 3:
        rc.fail("need at least 3 frames")
    mode = args.camera
    if mode == "auto":
        mode = "anchor" if args.anchor_bbox else "global"
    if mode == "anchor" and not args.anchor_bbox:
        rc.fail("--camera anchor needs --anchor-bbox")
    if mode == "global" and args.anchor_bbox:
        rc.fail("--camera global ignores --anchor-bbox; drop one of them (or use --camera anchor)")
    abox = rc.parse_bbox(args.anchor_bbox, "--anchor-bbox") if args.anchor_bbox else None
    ds = max(1, args.downscale)
    raw = track_clip((rc.load_gray(base / fr["file"], ds) for fr in frames_meta), bbox, abox, mode, args)
    comp = compensate(raw, mode, abox, args.min_score)
    rows, applied, cam_sum = raw["rows"], comp["applied"], comp["summary"]
    use_cam = cam_sum["applied"] or bool(abox)

    ppu = args.px_per_unit
    unit = args.unit if ppu else "px"
    scale = 1.0 / ppu if ppu else 1.0
    x0, y0 = rows[0]["p"][0], rows[0]["p"][1]
    samples = []
    low = 0
    zoom_on = comp["zoom_span"] > 1.004
    for i, (fr, r) in enumerate(zip(frames_meta, rows)):
        x, y, sc = r["p"][:3]
        Sa = applied[i]
        xc, yc = sim_apply(sim_inverse(Sa), x, y)
        u = (xc - x0) * scale
        v = (y0 - yc) * scale
        a = r["a"]
        low += sc < args.min_score or bool(a and a[2] < args.min_score and not (comp["handoff"] is not None and i >= comp["handoff"]))
        s = {"sample": i, "index": fr.get("index"), "t": round(times[i], 6),
             "x_px": round(x, 3), "y_px": round(y, 3), "score": round(sc, 4),
             "u": round(u, 5), "v": round(v, 5),
             "anchor_score": round(a[2], 4) if a else None}
        if use_cam:
            s["x_cam_px"], s["y_cam_px"] = round(x - xc, 3), round(y - yc, 3)
        if zoom_on:
            s["cam_scale"] = round(sim_scale(Sa), 5)
            s["cam_roll_deg"] = round(sim_roll_deg(Sa), 4)
        if raw["camera"] is not None and not r["cam_ok"] and (cam_sum["applied"] or abox):
            s["cam_ok"] = False
        if comp["handoff"] is not None and i >= comp["handoff"]:
            s["anchor_handoff"] = True
        info = r["info"]
        if info.get("lost"):
            s["lost"] = info["lost"]
        if info.get("ambiguous"):
            s["ambiguous"] = True
        if info.get("reacquired"):
            s["reacquired"] = True
        if info.get("fb_px") is not None:
            s["fb_px"] = round(info["fb_px"], 3)
        if args.scale_search:
            s["scale"] = round(r["p"][3], 4)
            s["subject_scale"] = round(r["p"][3] / sim_scale(Sa), 4) if zoom_on else s["scale"]
        samples.append(s)

    if len(times) > 1 and times[-1] > times[0]:
        fps = (len(times) - 1) / (times[-1] - times[0])
    else:
        fps = 60.0
    result = {
        "tool": TOOL, "schema": SCHEMA, "manifest": str(args.manifest), "bbox": list(bbox),
        "anchor_bbox": args.anchor_bbox, "px_per_unit": ppu, "unit": unit,
        "fps_from_samples": round(fps, 4), "low_score_samples": int(low), "samples": samples,
        "warnings": [], "camera": cam_sum,
    }
    warn = result["warnings"]
    unreliable_why = []
    if args.scale_search:
        sc_all = [s["subject_scale"] for s in samples]
        span = max(sc_all) / min(sc_all)
        result["scale_range"] = [round(min(sc_all), 4), round(max(sc_all), 4)]
        if span > 1.08 and ppu:
            warn.append(
                f"the subject's apparent size changed {100 * (span - 1):.0f}% during the clip{' (camera zoom excluded)' if zoom_on else ''}, "
                "so one --px-per-unit cannot be right for every frame (perspective); convert positions with camera_solve.py ground instead")
    zspan = comp["zoom_span"]
    if zspan > 1.02:
        if comp["zoom_removed"]:
            warn.append(f"the camera zoomed {100 * (zspan - 1):.0f}% during the clip (FOV change or dolly; roll "
                        f"{cam_sum['roll_range_deg'][0]:.1f} to {cam_sum['roll_range_deg'][1]:.1f} deg): positions are divided by the "
                        "per-frame camera scale, so --px-per-unit must be measured at the FIRST frame's zoom")
        else:
            warn.append(f"the anchor's apparent size changed {100 * (zspan - 1):.0f}% (camera zoom or FOV change), which an anchor "
                        "shift cannot remove: speeds and distances are inflated by up to that much. Run with --camera anchor or "
                        "--camera global so the whole-frame camera model divides the zoom out")
            unreliable_why.append("camera zoom not removed")
    if raw["camera"] is not None and not cam_sum["measured"]:
        warn.append("the camera motion could not be measured (too little background texture): positions are screen positions, "
                    "assuming a fixed camera. If the camera moves, pass --anchor-bbox on a textured static feature")
    if cam_sum.get("anchor_handoff_sample") is not None:
        hs = cam_sum["anchor_handoff_sample"]
        warn.append(f"the anchor was lost or left the view at sample {hs} (t={samples[hs]['t']:.3f} s); from there the whole-frame "
                    "camera model carries the camera shift (anchor_handoff in samples)")
    keep, eff_fps, rep_ratio = repeated_frames([s["x_px"] - s.get("x_cam_px", 0.0) for s in samples],
                                               [s["y_px"] - s.get("y_cam_px", 0.0) for s in samples], fps)
    used = samples
    if eff_fps:
        for s_, k in zip(samples, keep):
            s_["repeat"] = not bool(k)
        used = [s_ for s_, k in zip(samples, keep) if k]
        result["content_fps"] = round(eff_fps, 3)
        result["repeated_samples"] = int((~keep).sum())
        warn.append(
            f"{100 * rep_ratio:.0f}% of the frames while the subject moves repeat the previous position: the content updates at "
            f"about {eff_fps:.1f} fps, not {fps:.1f}. Analyses use only the first frame of each repeat, and timings are only "
            f"precise to ±{1000 / eff_fps:.1f} ms")
    amb = [s["sample"] for s in samples if s.get("ambiguous")]
    if amb:
        result["ambiguous_samples"] = len(amb)
        warn.append(f"a look-alike matched almost as well as the subject at {len(amb)} samples ({amb[0]}-{amb[-1]}); the tracker kept "
                    "the match that fits the motion so far. Confirm the identity with frame_zoom.py --mark on those frames")
    bad = unusable_samples(samples, args.min_score, bool(abox))
    if bad:
        for i, why in bad.items():
            samples[i]["excluded"] = why
        used = [s_ for s_ in used if "excluded" not in s_]
        kinds = sorted(set(bad.values()))
        result["excluded_samples"] = len(bad)
        warn.append(f"{len(bad)} samples left out of the analysis ({'; '.join(kinds)}); see 'excluded' in samples")
        lost = [i for i, why in sorted(bad.items()) if why.startswith("subject lost")]
        if lost:
            result["first_lost_sample"] = lost[0]
            warn.append(f"the subject was first lost at sample {lost[0]} (t={samples[lost[0]]['t']:.3f} s): {bad[lost[0]]}")
    relock = [s["sample"] for s in samples if s.get("reacquired")]
    if relock:
        unreliable_why.append("re-acquired on appearance alone")
        warn.append(f"after losing the subject the tracker re-locked at sample {relock[0]} on appearance alone (the match did not "
                    "fit the predicted motion); samples after it may be another object. Check that frame with frame_zoom.py --mark")
    excluded_frac = len(bad) / len(samples)
    if excluded_frac > 0.2 or len(used) < 8:
        unreliable_why.insert(0, f"{100 * excluded_frac:.0f}% of the samples were unusable")
    result["reliable"] = not unreliable_why
    if not result["reliable"]:
        warn.append(f"UNRELIABLE: {'; '.join(unreliable_why)}; the analysis below is for "
                    "inspection only and ledger.py will not import it. Fix the track (smaller or sharper feature, "
                    "--scale-search, another anchor, a shorter range)")
    if len(used) < 3:
        rc.fail("fewer than 3 usable samples remain; the track lost the subject", rc.EXIT_FAIL)
    tt = [s["t"] for s in used]
    rate = eff_fps or fps
    if args.analyze == "jump":
        air = None
        if args.air_range:
            a, b = (int(v) for v in args.air_range.split(","))
            if len(used) != len(samples):
                a, b = (sum(1 for s_ in used if s_["sample"] < a), sum(1 for s_ in used if s_["sample"] <= b) - 1)
            air = (a, b)
        result["jump"] = analyze_jump(tt, [s["v"] for s in used], unit, scale, rate, air)
        result["jump"]["segment_samples"] = [used[i]["sample"] for i in result["jump"]["segment_samples"]]
    elif args.analyze == "speed":
        result["speed"] = analyze_speed(tt, [s["u"] for s in used], unit, scale, rate)
        result["speed"]["first_moving_sample"] = used[result["speed"]["first_moving_sample"]]["sample"]

    if args.out:
        rc.write_json(args.out, result)
    if args.csv:
        rc.ensure_parent(args.csv)
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(samples[0].keys()))
            w.writeheader()
            w.writerows(samples)

    print(f"tracked {len(samples)} frames; {low} below score {args.min_score}; unit {unit}")
    if cam_sum.get("moves"):
        z = cam_sum.get("zoom_range")
        print(f"camera ({cam_sum['mode']}): moves up to {cam_sum['max_shift_px']} px" +
              (f", zoom {z[0]:.3f}-{z[1]:.3f}" if z else "") + ("; compensated" if cam_sum["applied"] else ""))
    if low:
        print("WARNING: low match scores - the feature changed appearance or left the search window; "
              "check the track or use a smaller, more rigid feature", file=sys.stderr)
    for wmsg in result["warnings"]:
        print(f"WARNING: {wmsg}", file=sys.stderr)
    for key in ("jump", "speed"):
        if key in result:
            for k, val in result[key].items():
                print(f"  {k}: {val}")
    if args.out:
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    rc.run_main(main)
