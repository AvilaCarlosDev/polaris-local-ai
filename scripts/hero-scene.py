#!/usr/bin/env python3
"""FLOATING ISLAND MIRAGE — animated voxel hero scene for polaris-local-ai.

Isometric voxel diorama with an original design: a floating island with a
beach, a giant straw hat, palms and a small sailboat, orbited by the camera.
Runs 100% local: Pillow only, no network, no model.

    python3 scripts/hero-scene.py out.png [frame]
    python3 scripts/hero-scene.py --range 0 869 --outdir frames/
    scripts/hero-scene.sh                 # render + encode the 29 s video
"""
import math
import random
import sys

from PIL import Image, ImageDraw, ImageFont

W, H = 1600, 900
SCALE = 25.0
CX, CY = W * 0.57, H * 0.58
COS30, SIN30 = 0.8660254, 0.5
FPS = 30
FRAMES = 870  # 29 s

GRASS = (94, 176, 78)
GRASS_D = (76, 150, 62)
SAND = (240, 224, 160)
DIRT = (140, 104, 74)
STONE = (116, 96, 86)
WATER = (54, 154, 220)
WATER_D = (38, 128, 196)
FOAM = (168, 222, 246)
HAT_Y = (246, 198, 69)
HAT_Y_D = (214, 168, 48)
BAND = (214, 68, 58)
TRUNK = (128, 92, 62)
LEAF = (52, 138, 74)
WOOD = (156, 108, 70)
SAIL = (245, 245, 240)
GULL = (58, 66, 78)

VOXELS = {}
SEA_TOP = set()


def rot(x, y, th):
    c, s = math.cos(th), math.sin(th)
    return x * c - y * s, x * s + y * c


def proj(x, y, z, th):
    rx, ry = rot(x, y, th)
    return (CX + (rx - ry) * COS30 * SCALE,
            CY + ((rx + ry) * SIN30 - z) * SCALE)


def depth(x, y, z, th):
    rx, ry = rot(x, y, th)
    return rx + ry + z


def shade(color, f):
    return tuple(max(0, min(255, int(c * f))) for c in color)


def put(x, y, z, color):
    VOXELS[(x, y, z)] = color


def build_island(rng):
    for x in range(-24, 25):
        for y in range(-24, 25):
            cx, cy = x + 0.5, y + 0.5
            ang = math.atan2(cy, cx)
            d = math.hypot(cx, cy)
            wobble = 0.9 * math.sin(3 * ang + 1.2) + 0.5 * math.sin(7 * ang)
            if d <= 11.5 + wobble:
                if d > 9.4 + wobble:
                    put(x, y, 0, SAND)
                else:
                    put(x, y, 0, GRASS if rng.random() > 0.35 else GRASS_D)
                depth_layers = 3 if d < 10 else 2
                for k in range(1, depth_layers + 1):
                    put(x, y, -k, DIRT if k < 3 else STONE)
            elif d <= 18.5 + wobble:
                put(x, y, -1, WATER)
                SEA_TOP.add((x, y, -1))
                put(x, y, -2, shade(WATER_D, 0.7))


def build_hat():
    for x in range(-7, 8):
        for y in range(-7, 8):
            d = math.hypot(x + 0.5, y + 0.5)
            if d <= 7.2:
                put(x, y, 1, HAT_Y if (x + y) % 2 == 0 else HAT_Y_D)
    for x in range(-4, 5):
        for y in range(-4, 5):
            d = math.hypot(x + 0.5, y + 0.5)
            if d <= 4.2:
                for z in (2, 3):
                    put(x, y, z, BAND if d > 3.0 else HAT_Y)
                for z in (4, 5, 6):
                    put(x, y, z, HAT_Y if (x + y) % 2 == 0 else HAT_Y_D)


def build_palm(px, py, frame):
    sway = int(round(math.sin(frame * 0.05) * 1.0))
    for z in range(1, 6):
        put(px, py, z, TRUNK)
    for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1),
                   (2, 0), (-2, 0), (0, 2), (0, -2)):
        put(px + dx + sway, py + dy, 6, LEAF)
    for dx, dy in ((1, 1), (-1, 1), (1, -1), (-1, -1)):
        put(px + dx + sway, py + dy, 5, shade(LEAF, 0.85))


def build_ship(frame):
    px = 14 + 2.4 * math.sin(frame * 0.014)
    py = 9 + 1.8 * math.cos(frame * 0.011)
    bob = 0.5 * math.sin(frame * 0.11)
    for x in range(-3, 4):
        for y in range(-1, 2):
            if abs(x) == 3 and abs(y) == 1:
                continue
            put(px + x, py + y, -1 + bob, WOOD)
            if abs(x) <= 2:
                put(px + x, py + y, 0 + bob, shade(WOOD, 1.15))
    for z in (1, 2, 3):
        put(px, py, z + bob, TRUNK)
    for z in (2, 3, 4, 5):
        for dx in range(1, 4):
            put(px + dx, py, z + bob, SAIL if (z + dx) % 2 else shade(SAIL, 0.92))


def build(frame):
    VOXELS.clear()
    SEA_TOP.clear()
    build_island(random.Random(7))
    build_hat()
    for px, py in ((-8, 7), (8, -6), (6, 8)):
        build_palm(px, py, frame)
    build_ship(frame)


def water_color(x, y, frame):
    ph = math.sin(x * 0.7 + y * 0.55 + frame * 0.16)
    if (x * 31 + y * 17 + frame // 3) % 41 == 0:
        return FOAM
    if ph > 0.55:
        return WATER
    if ph < -0.35:
        return shade(WATER_D, 0.85)
    return WATER_D


def face_visible(nx, ny, nz, th):
    rx, ry = rot(nx, ny, th)
    return rx + ry + nz > 0


def face_shade(nx, ny, th):
    rx, ry = rot(nx, ny, th)
    return 0.78 if (rx - ry) > 0 else 0.62


def render(path, frame=0):
    th = 2 * math.pi * frame / FRAMES
    build(frame)

    img = Image.new("RGB", (W, H), (174, 205, 232))
    draw = ImageDraw.Draw(img, "RGBA")
    for i in range(H):
        t = i / H
        draw.line([(0, i), (W, i)],
                  fill=(int(168 + 60 * t), int(200 + 45 * t), int(232 + 20 * t)))

    for key in sorted(VOXELS, key=lambda v: depth(*v, th)):
        x, y, z = key
        color = water_color(x, y, frame) if key in SEA_TOP else VOXELS[key]
        corners = [proj(x, y, z + 1, th), proj(x + 1, y, z + 1, th),
                   proj(x + 1, y + 1, z + 1, th), proj(x, y + 1, z + 1, th),
                   proj(x, y, z, th), proj(x + 1, y, z, th),
                   proj(x + 1, y + 1, z, th), proj(x, y + 1, z, th)]
        faces = (
            ((4, 5, 6, 7), (0, 0, -1)),
            ((0, 3, 7, 4), (-1, 0, 0)),
            ((1, 2, 6, 5), (1, 0, 0)),
            ((0, 1, 5, 4), (0, -1, 0)),
            ((2, 3, 7, 6), (0, 1, 0)),
            ((0, 1, 2, 3), (0, 0, 1)),
        )
        for pts_id, (nx, ny, nz) in faces:
            if not face_visible(nx, ny, nz, th):
                continue
            f = 1.0 if nz == 1 else face_shade(nx, ny, th)
            fill = shade(color, f)
            draw.polygon([corners[i] for i in pts_id], fill=fill,
                         outline=shade(fill, 0.78))

    draw_gulls(draw, frame)
    draw_panel(draw, len(VOXELS), frame, th)
    img.save(path)
    return img


def draw_gulls(draw, frame):
    for i, (x0, y0, sp, ph) in enumerate(((0.18, 0.2, 0.0035, 0.0),
                                          (0.62, 0.13, 0.0026, 2.1),
                                          (0.4, 0.3, 0.0031, 4.0))):
        gx = (x0 + frame * sp) % 1.15 * W - 0.07 * W
        gy = y0 * H + 26 * math.sin(frame * 0.045 + ph)
        flap = 7 * math.sin(frame * 0.5 + ph)
        draw.line([(gx - 13, gy - flap), (gx - 3, gy), (gx, gy + 4)],
                  fill=GULL + (215,), width=3)
        draw.line([(gx, gy + 4), (gx + 3, gy), (gx + 13, gy - flap)],
                  fill=GULL + (215,), width=3)


def _font(size, bold=True):
    names = (["NotoSansMono-Bold.ttf", "DejaVuSansMono-Bold.ttf",
              "LiberationMono-Bold.ttf"] if bold else
             ["NotoSansMono-Regular.ttf", "DejaVuSansMono.ttf",
              "LiberationMono-Regular.ttf"])
    bases = ("/usr/share/fonts/noto/", "/usr/share/fonts/truetype/dejavu/",
             "/usr/share/fonts/truetype/liberation/")
    for name in names:
        for base in bases:
            try:
                return ImageFont.truetype(base + name, size)
            except OSError:
                continue
    return ImageFont.load_default()


def draw_panel(draw, nvox, frame, th):
    px, py, pw, ph = 24, 24, 300, 430
    draw.rounded_rectangle([px, py, px + pw, py + ph], 10, fill=(30, 34, 40, 225))
    draw.text((px + 18, py + 14), "Controls", font=_font(19), fill=(235, 238, 242))
    t_sec = int(frame / FPS)
    clock = f"17:{40 + t_sec // 60:02d}" if 40 + t_sec // 60 < 60 else "18:00"
    sliders = (("Time", clock), ("Waves", f"{0.5 + 0.3 * math.sin(frame * 0.06):.2f}"),
               ("Wind", f"{0.4 + 0.2 * math.sin(frame * 0.04 + 1.5):.2f}"))
    y = py + 52
    for i, (label, val) in enumerate(sliders):
        draw.text((px + 18, y), label, font=_font(15, False), fill=(210, 215, 222))
        draw.text((px + pw - 58, y), val, font=_font(14, False), fill=(170, 178, 188))
        y += 22
        draw.rounded_rectangle([px + 18, y, px + pw - 18, y + 8], 4, fill=(60, 66, 76))
        pos = 0.5 + 0.45 * math.sin(frame * 0.02 + i * 1.7)
        knob = px + 60 + 170 * max(0.0, min(1.0, pos))
        draw.ellipse([knob - 7, y - 4, knob + 7, y + 12], fill=(255, 105, 135))
        y += 34
    for label, on in (("Auto-rotate", True), ("Shadows", True),
                      ("Water anim", True), ("Wind", True)):
        box = [px + 18, y, px + 32, y + 14]
        draw.rounded_rectangle(box, 3, fill=(45, 120, 235) if on else (60, 66, 76))
        if on:
            draw.line([(px + 21, y + 7), (px + 25, y + 11), (px + 30, y + 3)],
                      fill=(255, 255, 255), width=2)
        draw.text((px + 42, y - 3), label, font=_font(14, False), fill=(210, 215, 222))
        y += 26
    y += 8
    for i, label in enumerate(("1 Isle", "2 Ship", "3 Palms", "4 Hat")):
        bx = px + 18 + (i % 2) * 140
        by = y + (i // 2) * 34
        active = i == (frame // 220) % 4
        draw.rounded_rectangle([bx, by, bx + 128, by + 26], 5,
                               fill=(45, 120, 235) if active else (52, 58, 68))
        draw.text((bx + 12, by + 4), label, font=_font(14, False), fill=(215, 220, 228))
    draw.text((px + 18, py + ph - 34), f"voxels: {nvox}",
              font=_font(14, False), fill=(170, 178, 188))
    draw.text((px + 150, py + ph - 34), f"orbit: {int(math.degrees(th)) % 360}°",
              font=_font(14, False), fill=(170, 178, 188))
    draw.text((px + 250, py + ph - 34), f"fps: {FPS}",
              font=_font(14, False), fill=(170, 178, 188))
    draw.text((W - 470, 30), "FLOATING ISLAND MIRAGE", font=_font(27),
              fill=(255, 255, 255))
    draw.text((W - 470, 68), "L O C A L   A I   A R T   ·   V O X E L   D I O R A M A",
              font=_font(12, False), fill=(240, 248, 255))
    bar = [W - 470, 104, W - 60, 110]
    draw.rounded_rectangle(bar, 3, fill=(40, 52, 70, 180))
    head = W - 470 + int(410 * frame / FRAMES)
    draw.rounded_rectangle([W - 470, 104, head, 110], 3, fill=(246, 198, 69))


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "--range":
        lo, hi = int(argv[1]), int(argv[2])
        outdir = argv[argv.index("--outdir") + 1] if "--outdir" in argv else "frames"
        import os
        os.makedirs(outdir, exist_ok=True)
        import time
        t0 = time.time()
        for f in range(lo, hi + 1):
            render(f"{outdir}/f{f:04d}.png", f)
        dt = time.time() - t0
        print(f"frames {lo}..{hi}: {dt:.1f}s ({dt / (hi - lo + 1):.2f}s/frame)")
    else:
        out = argv[0] if argv else "scene.png"
        frame = int(argv[1]) if len(argv) > 1 else 0
        render(out, frame)
        print(f"wrote {out} with {len(VOXELS)} voxels")
