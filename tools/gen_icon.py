#!/usr/bin/env python3
"""
Custom Stem Injector — app icon generator.

Draws a teal syringe on a dark background at every required macOS
iconset resolution, then calls iconutil to build the .icns file.

Usage:
    python3 tools/gen_icon.py [--out PATH]

Default output: tools/AppIcon.icns
"""

import math
import os
import subprocess
import shutil
import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# ── Palette ──────────────────────────────────────────────────────────────────
BG        = (4,   6,  15, 255)   # #04060f
TEAL      = (20, 217, 204, 255)  # #14d9cc
TEAL_DIM  = (10, 120, 115, 200)
TEAL_MID  = (14, 170, 160, 230)
PLUNGER   = (148, 196, 255, 200)
PLUNGER_D = (100, 145, 200, 170)
NEEDLE_W  = (220, 252, 250, 255)
WHITE     = (255, 255, 255, 255)
VIOLET    = (157, 123, 255, 180)


def lerp_color(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def rgba(r, g, b, a=255):
    return (r, g, b, a)


def draw_syringe(size: int) -> Image.Image:
    """Render the icon at `size`×`size` px (no AA padding needed — caller handles that)."""

    W = H = size
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # ── Background: dark rounded square ──────────────────────────────────────
    R = int(W * 0.215)          # ~macOS squircle feel
    draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=R, fill=BG)

    # Subtle inner glow: small radial-ish highlight in top-left
    glow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_layer)
    gd.ellipse([-W // 3, -H // 3, W // 1.2, H // 1.2],
               fill=(20, 217, 204, 14))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(W * 0.18))
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img)

    # ── Syringe geometry — proportions match the in-app header syringe ─────────
    # Header SVG viewBox is -12,-4 240 74 → barrel 108 wide × 30 tall (3.6:1)
    # Here: barrel ~580px wide × 97px tall inside a 1024×1024 icon canvas.

    cy     = H * 0.50
    bh     = H * 0.095   # barrel height — slim like header syringe
    bh2    = bh / 2

    # Key X positions (left → right), matching header proportions
    x_t_left   = W * 0.055  # T-handle outer left
    x_t_right  = W * 0.155  # T-handle outer right
    x_t_cx     = (x_t_left + x_t_right) / 2
    x_rod_r    = W * 0.195  # plunger rod right / stopper left
    x_bar_l    = W * 0.215  # barrel body left
    x_fluid_r  = W * 0.555  # fluid fill right (≈62% of barrel length)
    x_bar_r    = W * 0.775  # barrel body right
    x_conn_r   = W * 0.832  # connector right
    x_hub_r    = W * 0.875  # needle hub right
    x_tip      = W * 0.945  # needle tip x

    brl_r = bh * 0.30       # barrel corner radius (rounder on thin barrel)

    top  = cy - bh2
    bot  = cy + bh2

    # ── Syringe glow pass (blurred silhouette behind everything) ─────────────
    glow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g2d   = ImageDraw.Draw(glow2)
    # Barrel glow outline
    g2d.rounded_rectangle(
        [x_bar_l - 4, top - 4, x_bar_r + 4, bot + 4],
        radius=brl_r + 4,
        fill=(20, 217, 204, 80)
    )
    # Needle glow
    needle_pts = [
        (x_hub_r, top + bh * 0.28),
        (x_tip + 4, cy),
        (x_hub_r, bot - bh * 0.28),
    ]
    g2d.polygon(needle_pts, fill=(20, 217, 204, 80))
    glow2 = glow2.filter(ImageFilter.GaussianBlur(W * 0.028))
    img = Image.alpha_composite(img, glow2)
    draw = ImageDraw.Draw(img)

    # ── T-Handle ─────────────────────────────────────────────────────────────
    t_bar_w   = W * 0.018          # T vertical bar width (slim)
    t_cross_h = bh * 0.55          # crossbar height
    # T arms extend well above/below barrel — gives classic syringe thumb-ring look
    t_ext     = bh * 1.05          # how far T arms extend above/below barrel

    # Vertical bar (connecting to plunger rod)
    draw.rounded_rectangle(
        [x_t_cx - t_bar_w / 2, top - t_ext,
         x_t_cx + t_bar_w / 2, bot + t_ext],
        radius=t_bar_w / 2,
        fill=PLUNGER_D,
        outline=PLUNGER,
        width=max(1, int(W * 0.004)),
    )
    # Top crossbar
    draw.rounded_rectangle(
        [x_t_left, top - t_ext,
         x_t_right, top - t_ext + t_cross_h],
        radius=t_cross_h / 2,
        fill=PLUNGER_D,
        outline=PLUNGER,
        width=max(1, int(W * 0.004)),
    )
    # Bottom crossbar
    draw.rounded_rectangle(
        [x_t_left, bot + t_ext - t_cross_h,
         x_t_right, bot + t_ext],
        radius=t_cross_h / 2,
        fill=PLUNGER_D,
        outline=PLUNGER,
        width=max(1, int(W * 0.004)),
    )

    # ── Plunger rod (horizontal, T to stopper) ───────────────────────────────
    rod_h = bh * 0.28
    draw.rounded_rectangle(
        [x_t_right, cy - rod_h / 2,
         x_rod_r,   cy + rod_h / 2],
        radius=rod_h / 2,
        fill=PLUNGER_D,
        outline=PLUNGER,
        width=max(1, int(W * 0.003)),
    )

    # ── Barrel body ──────────────────────────────────────────────────────────
    # Outer shell
    draw.rounded_rectangle(
        [x_bar_l, top, x_bar_r, bot],
        radius=brl_r,
        fill=(8, 20, 30, 200),
        outline=(*TEAL[:3], 200),
        width=max(1, int(W * 0.005)),
    )

    # ── Fluid fill ───────────────────────────────────────────────────────────
    fluid_pad = bh * 0.12
    draw.rounded_rectangle(
        [x_bar_l + 2, top + fluid_pad,
         x_fluid_r,   bot - fluid_pad],
        radius=brl_r * 0.6,
        fill=TEAL_MID,
    )
    # Fluid highlight shimmer (lighter strip along top)
    sh_h = fluid_pad * 0.7
    draw.rounded_rectangle(
        [x_bar_l + 6, top + fluid_pad,
         x_fluid_r - 8, top + fluid_pad + sh_h],
        radius=sh_h / 2,
        fill=(180, 255, 250, 60),
    )

    # ── Graduation ticks on barrel ───────────────────────────────────────────
    tick_count = 4
    tick_span  = x_fluid_r - x_bar_l
    tick_color = (*TEAL[:3], 90)
    tick_w     = max(1, int(W * 0.003))
    tick_h_long = bh * 0.22
    for i in range(1, tick_count + 1):
        tx = x_bar_l + tick_span * i / (tick_count + 1)
        draw.line([(tx, top - 1), (tx, top + tick_h_long)],
                  fill=tick_color, width=tick_w)
        draw.line([(tx, bot + 1), (tx, bot - tick_h_long)],
                  fill=tick_color, width=tick_w)

    # ── Plunger stopper (inside barrel, left end) ────────────────────────────
    stopper_w = bh * 0.12
    draw.rounded_rectangle(
        [x_rod_r - stopper_w * 0.3, top + 2,
         x_rod_r + stopper_w,       bot - 2],
        radius=max(2, int(stopper_w * 0.4)),
        fill=(*TEAL[:3], 120),
        outline=(*TEAL[:3], 210),
        width=max(1, int(W * 0.004)),
    )

    # ── Barrel flange ring (right end of barrel) ─────────────────────────────
    flange_w = bh * 0.10
    draw.rounded_rectangle(
        [x_bar_r - flange_w, top - bh * 0.14,
         x_bar_r + flange_w * 0.4, bot + bh * 0.14],
        radius=flange_w * 0.5,
        fill=(*TEAL[:3], 60),
        outline=(*TEAL[:3], 190),
        width=max(1, int(W * 0.005)),
    )

    # ── Connector (barrel to hub) ─────────────────────────────────────────────
    conn_taper = bh * 0.12
    conn_pts = [
        (x_bar_r, top + conn_taper),
        (x_conn_r, top + conn_taper * 1.4),
        (x_conn_r, bot - conn_taper * 1.4),
        (x_bar_r,  bot - conn_taper),
    ]
    draw.polygon(conn_pts, fill=(*TEAL[:3], 80))
    draw.line(conn_pts[:2], fill=(*TEAL[:3], 180), width=max(1, int(W * 0.004)))
    draw.line(conn_pts[2:] + [conn_pts[0]], fill=(*TEAL[:3], 180), width=max(1, int(W * 0.004)))

    # ── Needle hub ───────────────────────────────────────────────────────────
    hub_top = top + bh * 0.25
    hub_bot = bot - bh * 0.25
    draw.rounded_rectangle(
        [x_conn_r, hub_top, x_hub_r, hub_bot],
        radius=bh * 0.08,
        fill=(*TEAL[:3], 100),
        outline=(*TEAL[:3], 220),
        width=max(1, int(W * 0.005)),
    )

    # ── Needle (tapered path) ─────────────────────────────────────────────────
    needle_top = top + bh * 0.30
    needle_bot = bot - bh * 0.30
    needle_pts = [
        (x_hub_r, needle_top),
        (x_tip,   cy),
        (x_hub_r, needle_bot),
    ]
    draw.polygon(needle_pts, fill=(*NEEDLE_W[:3], 235))

    # Needle highlight (top edge)
    draw.line([(x_hub_r, needle_top), (x_tip, cy)],
              fill=WHITE, width=max(1, int(W * 0.004)))

    # ── Needle tip glow ───────────────────────────────────────────────────────
    tip_r = W * 0.018
    # Outer glow
    glow3 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g3d   = ImageDraw.Draw(glow3)
    g3d.ellipse(
        [x_tip - tip_r * 3, cy - tip_r * 3,
         x_tip + tip_r * 3, cy + tip_r * 3],
        fill=(*TEAL[:3], 160)
    )
    glow3 = glow3.filter(ImageFilter.GaussianBlur(tip_r * 2.5))
    img   = Image.alpha_composite(img, glow3)
    draw  = ImageDraw.Draw(img)
    # Core dot
    draw.ellipse(
        [x_tip - tip_r, cy - tip_r,
         x_tip + tip_r, cy + tip_r],
        fill=TEAL
    )
    # Bright center pin
    pin_r = tip_r * 0.4
    draw.ellipse(
        [x_tip - pin_r, cy - pin_r,
         x_tip + pin_r, cy + pin_r],
        fill=WHITE
    )

    return img


def make_iconset(iconset_dir: Path):
    """Generate all required sizes into `iconset_dir`."""
    iconset_dir.mkdir(parents=True, exist_ok=True)

    # macOS iconset spec: (filename, logical_size, scale)
    sizes = [
        ("icon_16x16.png",       16,   1),
        ("icon_16x16@2x.png",    16,   2),
        ("icon_32x32.png",       32,   1),
        ("icon_32x32@2x.png",    32,   2),
        ("icon_64x64.png",       64,   1),  # some tools expect this
        ("icon_64x64@2x.png",    64,   2),
        ("icon_128x128.png",     128,  1),
        ("icon_128x128@2x.png",  128,  2),
        ("icon_256x256.png",     256,  1),
        ("icon_256x256@2x.png",  256,  2),
        ("icon_512x512.png",     512,  1),
        ("icon_512x512@2x.png",  512,  2),
    ]

    # Always render at max 1024 then downsample (best quality at every size)
    RENDER_SIZE = 1024
    print(f"  Rendering master at {RENDER_SIZE}px …")

    # Render at 4× then downsample for the master (AA)
    master_raw = draw_syringe(RENDER_SIZE * 2)
    master = master_raw.resize((RENDER_SIZE, RENDER_SIZE), Image.LANCZOS)

    for filename, logical, scale in sizes:
        px = logical * scale
        if px == RENDER_SIZE:
            icon = master.copy()
        elif px > RENDER_SIZE:
            icon = draw_syringe(px)
        else:
            icon = master.resize((px, px), Image.LANCZOS)
        out = iconset_dir / filename
        icon.save(str(out), "PNG")
        print(f"  Saved {filename} ({px}×{px})")


def build_icns(iconset_dir: Path, out_path: Path):
    """Run iconutil to convert .iconset → .icns."""
    result = subprocess.run(
        ["iconutil", "-c", "icns", "-o", str(out_path), str(iconset_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("iconutil stderr:", result.stderr)
        raise RuntimeError("iconutil failed")
    print(f"  Built: {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=None,
                        help="Output .icns path (default: tools/AppIcon.icns)")
    args = parser.parse_args()

    script_dir = Path(__file__).parent
    repo_root  = script_dir.parent

    out_path = Path(args.out) if args.out else script_dir / "AppIcon.icns"
    iconset_dir = out_path.with_suffix(".iconset")

    print("── Custom Stem Injector icon generator ──")
    print(f"Iconset dir : {iconset_dir}")
    print(f"Output .icns: {out_path}")

    make_iconset(iconset_dir)
    build_icns(iconset_dir, out_path)

    # Clean up temp iconset
    shutil.rmtree(iconset_dir)
    print("── Done ──")


if __name__ == "__main__":
    main()
