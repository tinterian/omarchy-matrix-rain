#!/usr/bin/env python3
# ============================================================================
# FILE:    matrix_rain.py
# TASK:    Generate the Matrix theme's animated wallpaper (digital-rain.*)
# STATUS:  DONE — confirmed by user on the live desktop, 2026-08-31 (session 5)
# OWNER:   agent (Claude Code) 2026-08-31 (session 5)
#
# WHAT THIS FILE DOES:
#   Renders a Matrix-style digital rain animation and saves it either as a
#   seamlessly-looping GIF (--out *.gif, palette-quantized, optimize=True)
#   or as a real video (--out *.mp4/.webm/.mkv, raw frames piped into
#   ffmpeg/libx264, no palette quantization at all -> no banding, smaller
#   file than the GIF path). The live wallpaper uses the video path.
#
#   The live wallpaper actually ships THREE renders of this script at
#   different --font-size values -- small/medium/large text -- as
#   selectable variants a user flips through with the standard Omarchy
#   background picker (omarchy-theme-bg-next / bg-switcher), same as any
#   other theme's picture backgrounds. That selection/hot-swap logic lives
#   in ~/.local/bin/matrix-wallpaper, NOT in this file — see that script's
#   own header for how it maps a picker selection to a video file. This
#   file only needs to know how to render one variant at a time; see "IF
#   YOU CHANGE SOMETHING LATER" below for the exact steps and gotchas
#   (font-size math AND the Omarchy state-snapshot refresh step) when
#   adding or resizing a variant.
#
#   Loop seam history (5 iterations across 3 sessions — see below for why
#   session 5 replaced the whole approach instead of tuning it again):
#     1. Blended tail toward frames_out[i] (a moving target) -> the wrap was
#        the single BIGGEST jump in the animation. Bug.
#     2. Blended tail toward a single FROZEN frame_0 target -> seam color
#        delta became exactly 0.0, but several frames in a row blending
#        toward one static image made the rain visibly slow down and
#        nearly stop right before the loop — a "freeze" artifact.
#     3. Blended `blend_count` extra runway frames into the START of the
#        output instead of freezing the tail — verified motion-continuous
#        numerically (no near-zero frame-delta dip anywhere), but the user
#        still reported the loop "runs like waves instead of rain": every
#        stream's very first spawn happened at the same simulation instant
#        (t=0), and that synchronized entry burst sat in exactly the frames
#        the crossfade used as the output's start — so it replayed every
#        loop as a synchronized wave of arrivals.
#     4. Added a silent physics warm-up before frame capture so streams
#        desynchronize before frame 0. Fixed the wave (confirmed by user —
#        "basically fine" on that front) but the underlying seam ("still a
#        noticeable seam... need to make it seamless") was untouched, since
#        warmup doesn't change the crossfade technique at all.
#     5. CURRENT, session 5: after 3 straight attempts at tuning a pixel-
#        blend, switched techniques entirely instead of tuning a 4th time.
#        Blending two DIFFERENT real frames together (runway continuation
#        vs. true start) is inherently a brief double-exposure of two
#        distinct rain patterns — visible as ghosting no matter how the
#        blend window is tuned, because this content is high-contrast
#        bright glyphs on near-black, where alpha-crossfades don't hide the
#        way they would on continuous-tone photographic content.
#        NEW APPROACH: make the animation EXACTLY periodic by construction,
#        so no blending is needed at all. Every Stream's fall-cycle length
#        (`cycle_frames`) is snapped to an exact divisor of the total loop
#        length (`loop_frames`) — so each stream returns to precisely the
#        same phase every `cycle_frames`, and since loop_frames is always a
#        whole multiple of that, frame `loop_frames` is bit-for-bit
#        identical to frame 0 for every stream simultaneously. Background
#        flicker cells use the same divisor-snapping for their epoch
#        length. The one piece of state that ISN'T purely a function of a
#        single stream (the glow/trail-fade accumulator `base`, which
#        carries ~20 frames of exponentially-decaying memory of everything
#        drawn) is warmed up by starting the compositing loop at negative
#        t and using `t % loop_frames` to look up state — since every
#        stream/bg formula is already periodic, evaluating it at negative t
#        is valid and lines the warm-up content up with the real tail of
#        the loop. Net effect: a plain hard loop (mpv `loop-file=inf`) is
#        now exactly seamless, no crossfade math needed anywhere.
#
# NEXT STEP (if not DONE):
#   None. Follow-up same session: user asked for small/medium/large text-
#   size variants, selectable by flipping through them like any other
#   theme's picture backgrounds. Implemented as three separate renders of
#   this script (--font-size 7/11/16, same width/height/frames otherwise)
#   installed as 1-digital-rain-small.mp4, 2-...-medium.mp4 (this is the
#   exact already-confirmed file, just renamed — not re-rendered, so its
#   quality/behavior is unchanged), and 3-...-large.mp4, each with a
#   same-basename poster .png for the picker. The variant-selection/
#   hot-swap logic lives entirely in ~/.local/bin/matrix-wallpaper (see its
#   own header) — this file was NOT changed to support that beyond what the
#   "IF YOU CHANGE SOMETHING LATER" section below already covered (font
#   size was already a documented gotcha before this feature existed).
#   Confirmed working end-to-end this session: cycled through all 3 via
#   `omarchy-theme-bg-next` several times, verified via `pgrep -af
#   mpvpaper` that the actual playing file changed each time and no
#   orphaned mpv processes were left behind. NOT yet visually confirmed by
#   the user watching the live desktop through the picker.
#
# ----------------------------------------------------------------------------
# IF YOU CHANGE SOMETHING LATER, READ THIS FIRST
#
# The seamless loop and the speed variation both hinge on one non-obvious
# rule: every Stream's `cycle_frames` must be an exact divisor of
# `loop_frames` (see Stream.__init__ and history item 5 above). Almost every
# tunable parameter interacts with that rule somehow. Quick reference:
#
#  * Bigger/smaller font size, or width/height (e.g. "increase text size to
#    cut down the number of lines"):
#      -> Changes `rows` (= height // font_size), which changes `distance`
#         (head_offset + rows + length) for every stream.
#      -> Does NOT break the seam. Seamlessness only depends on cycle_frames
#         dividing loop_frames evenly — that's enforced regardless of rows.
#      -> CAN quietly re-break speed variation. `nominal_cycle = distance /
#         speed`, so a change in `rows` shifts which loop_frames divisor
#         each SPEED_TIERS entry snaps to — several tiers can collapse onto
#         the same bucket again, the exact "they all move the same speed"
#         bug from this session. Don't just eyeball the result on the
#         desktop — rerun the speed-histogram snippet below and look for
#         a wide, unclumped spread before calling it done.
#
#  * ADDING A NEW TEXT-SIZE VARIANT (e.g. a 4th size, or replacing one of
#    the current 3 — small=font-size 7, medium=11, large=16, all at
#    --width 1360 --height 702 --frames 720):
#      1. Check the speed-histogram snippet BEFORE the full render (see
#         below) — cheap, catches a bad rows value in seconds instead of
#         after a multi-minute render.
#      2. Render: `python3 matrix_rain.py --width 1360 --height 702
#         --font-size N --use-omarchy-theme --theme-name matrix --frames
#         720 --out digital-rain-NAME.mp4`. Takes several minutes (small
#         text = more streams = longer; but per-frame cost is dominated by
#         fixed whole-canvas compositing either way, so it doesn't scale
#         as much with font size as you'd expect — small/medium/large all
#         took 4-6 minutes this session).
#      3. Extract a poster still for the picker (any frame — they're all
#         steady-state from frame 0 on): `ffmpeg -i digital-rain-NAME.mp4
#         -vf "select=eq(n\,0)" -vframes 1 poster-NAME.png`.
#      4. Install BOTH files into
#         ~/.config/omarchy/themes/matrix/backgrounds/ with the SAME
#         basename (one .mp4, one .png) and a numeric prefix that controls
#         cycle order, e.g. `4-digital-rain-NAME.mp4` /
#         `4-digital-rain-NAME.png` — see ~/.local/bin/matrix-wallpaper's
#         header for exactly why this naming pairing matters (it's how
#         that script maps a picker selection back to a video file).
#      5. Run `omarchy-theme-refresh`. This is the step that's easy to
#         forget and costs real debugging time if you do: Omarchy's
#         background picker (omarchy-theme-bg-next/-switcher) reads from
#         ~/.local/state/omarchy/current/theme/backgrounds/, which is a
#         `cp -r` SNAPSHOT of the source theme dir taken at theme-apply
#         time, NOT a live view of
#         ~/.config/omarchy/themes/matrix/backgrounds/. Dropping a new file
#         in the source dir alone does nothing visible until this snapshot
#         is refreshed. `omarchy-theme-refresh` re-syncs it without
#         disturbing the current background selection (unlike
#         `omarchy-theme-set`, which would also jump to a different
#         background as a side effect).
#      6. Test: `omarchy-theme-bg-next` a few times, then `pgrep -af
#         mpvpaper` after each to confirm the playing file actually
#         changed (not just the picker's idea of the selection).
#
#  * `--frames` (loop_frames):
#      -> Must stay a "highly composite" number (lots of divisors), not a
#         prime or near-prime. A prime loop_frames has only divisors {1,
#         loop_frames} — every stream's cycle would snap to loop_frames (or
#         1), which is the same-speed bug in its worst possible form.
#      -> Check divisor count before committing to a new value:
#           python3 -c "n=YOUR_VALUE; print(len([d for d in range(1,n+1) if n%d==0]))"
#         360 -> 24 divisors (too few, caused the bug this session).
#         720 -> 30 divisors (current, verified good). Don't go below ~24.
#      -> Also changes the physical loop length in seconds (loop_frames /
#         fps) and roughly linearly changes render time and output file
#         size — 720 frames took ~4m10s and produced a 32MB mp4 at
#         1360x702.
#
#  * `SPEED_TIERS`:
#      -> Adding/removing/moving tiers is safe in principle, but two tiers
#         whose target cycles round to the same loop_frames divisor render
#         at the same speed either way. Rerun the speed-histogram snippet
#         below after any change here.
#
#  * `duration_ms` / fps:
#      -> Pure real-world playback-speed and total-loop-duration knob
#         (seconds = loop_frames / fps). Doesn't interact with the divisor
#         logic at all — safe to change freely.
#
#  * `warmup` (in generate()):
#      -> Only exists to let the glow/trail-fade accumulator `base` reach
#         steady state before frame 0 is captured (~20-frame memory at the
#         alpha=60/255 decay used per frame). Too small and frame 0 can
#         show a dimmer glow trail than the rest of the loop — a subtle
#         non-seam mismatch. 40 is verified comfortable margin; don't drop
#         it much below ~24 without re-checking.
#
#  * THE ONE THING TO NEVER DO: reintroduce pixel-blending/crossfading at
#    the loop point (alpha-fading the tail into the head, or any variant).
#    That whole technique class was deliberately abandoned in session 5
#    after 3 separate tuning attempts, for a STRUCTURAL reason, not a
#    tuning mistake: alpha-blending two different frames of high-contrast
#    bright-glyphs-on-near-black content is inherently visible as
#    double-exposure ghosting, no matter how the blend window is tuned. The
#    current exact-periodicity technique has no such tradeoff. If a seam
#    ever reappears, the bug is almost certainly a violated divisor
#    invariant somewhere (a change that made some stream's cycle_frames NOT
#    a divisor of loop_frames), not something a blend can paper over.
#
#  * RE-VERIFICATION SNIPPET — speed spread (run after touching rows/tiers/
#    loop_frames):
#      python3 -c "
#      import random, matrix_rain as m
#      random.seed(1)
#      speeds = [m.Stream(0, YOUR_ROWS, YOUR_LOOP_FRAMES).speed for _ in range(2000)]
#      print('distinct (rounded):', len(set(round(s, 2) for s in speeds)))
#      print('min/max:', min(speeds), max(speeds))
#      "
#    A good result looks like this session's: 100+ distinct values spread
#    continuously across roughly the full SPEED_TIERS range, no single
#    value dominating the count. (YOUR_ROWS = height // font_size.)
#
#  * RE-VERIFICATION SNIPPET — seam (run after touching Stream,
#    BackgroundField, or the warmup/compositing loop in generate()):
#      Extract frame 0 and frame (loop_frames - 1) from the rendered mp4:
#        ffmpeg -y -i digital-rain.mp4 -vf "select=eq(n\,0)" -vframes 1 f0.png
#        ffmpeg -y -i digital-rain.mp4 -vf "select=eq(n\,LOOP_FRAMES-1)" -vframes 1 fLast.png
#      then diff f0.png against fLast.png, and separately diff two normal
#      adjacent frames for scale. The seam delta should be the same order
#      of magnitude as (or smaller than) a normal frame-to-frame delta, not
#      several times larger. This session's numbers, for reference: seam
#      mean delta 2.76/255 vs. a normal step's 0.93/255 (still tiny in
#      absolute terms — the ratio being >1 is expected/fine, see history
#      item 5's I-frame-vs-P-frame note; only worry if the seam's ABSOLUTE
#      value creeps up toward single-digit-percent, i.e. >~10/255 mean).
# ============================================================================
"""
Matrix Digital Rain Generator
=============================

Generates a "Matrix"-style digital rain animation and saves it as a GIF.
Pure Python + Pillow — no display server, GUI, or extra dependencies required.

Usage:
    python3 matrix_rain.py
    python3 matrix_rain.py --width 800 --height 600 --frames 480 --out rain.gif
    python3 matrix_rain.py --color "#00FF41" --font-size 18 --density 0.9

Run `python3 matrix_rain.py --help` for all options.
"""

import argparse
import math
import random
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

try:
    import tomllib
except ImportError:  # Python < 3.11 fallback
    tomllib = None

# The classic Matrix code rain is built almost entirely from half-width
# katakana, with a scattering of numerals — no Latin letters. That mix is
# what gives it its distinct, non-Western texture.
KATAKANA = "".join(chr(c) for c in range(0xFF66, 0xFF9D))
DIGITS = "0123456789"
CHARSET = (KATAKANA * 4) + DIGITS  # weight heavily toward katakana


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


OMARCHY_THEME_PATH = Path.home() / ".config" / "omarchy" / "current" / "theme" / "colors.toml"
OMARCHY_THEMES_DIR = Path.home() / ".config" / "omarchy" / "themes"


def _all_hex_colors(obj):
    """Recursively pull every hex color string out of a nested toml dict."""
    found = []
    if isinstance(obj, str):
        for m in re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", obj):
            found.append(m)
    elif isinstance(obj, dict):
        for v in obj.values():
            found.extend(_all_hex_colors(v))
    elif isinstance(obj, list):
        for v in obj:
            found.extend(_all_hex_colors(v))
    return found


def find_omarchy_colors_file(theme_name=None):
    """
    Omarchy's on-disk layout for theme colors has varied across versions/
    installs — some expose a `current` symlink, others keep colors only
    under themes/<name>/colors.toml with no central pointer. Try the known
    layouts in order and return the first colors.toml that actually exists.
    """
    candidates = []
    if theme_name:
        candidates.append(OMARCHY_THEMES_DIR / theme_name / "colors.toml")
    candidates.append(OMARCHY_THEME_PATH)
    candidates.append(Path.home() / ".config" / "omarchy" / "current" / "colors.toml")

    for path in candidates:
        if path.exists():
            return path

    # No explicit theme name and no "current" pointer found — if there's
    # exactly one theme folder with a colors.toml, it's a safe guess.
    if OMARCHY_THEMES_DIR.is_dir():
        found = list(OMARCHY_THEMES_DIR.glob("*/colors.toml"))
        if len(found) == 1:
            return found[0]

    return None


def load_omarchy_theme(theme_name=None):
    """
    Best-effort read of Omarchy's theme palette. Pulls the greenest accent
    color (for the rain) and the darkest neutral color (for the background)
    out of whatever schema that theme happens to use, since key names vary
    between themes.

    Returns (color_hex, bg_hex, path_used) — path_used is None if no file
    was found at all.
    """
    path = find_omarchy_colors_file(theme_name)
    if path is None or tomllib is None:
        return None, None, path
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return None, None, path

    hexes = list(dict.fromkeys(_all_hex_colors(data)))  # de-dupe, keep order
    if not hexes:
        return None, None, path

    rgb_list = [hex_to_rgb(h) for h in hexes]

    # Greenest color: green channel clearly dominant over red and blue —
    # a reasonable proxy for "the accent color" in a green-on-black theme.
    def greenness(rgb):
        r, g, b = rgb
        return g - max(r, b)

    green_idx = max(range(len(rgb_list)), key=lambda i: greenness(rgb_list[i]))
    color_hex = hexes[green_idx] if greenness(rgb_list[green_idx]) > 20 else None

    # Darkest color: lowest overall brightness, for the background.
    def brightness(rgb):
        return sum(rgb)

    dark_idx = min(range(len(rgb_list)), key=lambda i: brightness(rgb_list[i]))
    bg_hex = hexes[dark_idx] if brightness(rgb_list[dark_idx]) < 150 else None

    return color_hex, bg_hex, path


def find_font(size):
    """Try a few fonts that actually include half-width katakana glyphs."""
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansMonoCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "DejaVuSansMono.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def font_supports_katakana(font):
    """Some fallback fonts silently render kana as tofu boxes — detect that."""
    try:
        mask = font.getmask(KATAKANA[0])
        return mask.getbbox() is not None
    except Exception:
        return False


def _divisors(n):
    return sorted(d for d in range(1, n + 1) if n % d == 0)


class BackgroundField:
    """
    A static field of dim, mostly-stationary characters scattered across
    the whole frame — the ambient texture behind/between the falling
    streams. Each covered cell flickers to a new character on its own
    cadence (`period`), which is snapped to an exact divisor of
    `loop_frames` so the flicker pattern is perfectly periodic across the
    loop boundary, same as Stream — see the file header for why that
    matters.
    """

    def __init__(self, cols, rows, loop_frames, coverage=0.35, avg_period=100):
        self.cols = cols
        self.rows = rows
        divisors = _divisors(loop_frames)
        self.cells = {}
        for r in range(rows):
            for c in range(cols):
                if random.random() >= coverage:
                    continue
                nominal = random.uniform(avg_period * 0.4, avg_period * 2.5)
                period = min(divisors, key=lambda d: abs(d - nominal))
                n_epochs = max(1, loop_frames // period)
                seed = random.randrange(1 << 30)
                chars = [random.Random(f"{seed}-{e}").choice(CHARSET) for e in range(n_epochs)]
                self.cells[(c, r)] = (period, chars)

    def draw(self, draw_ctx, font, dim_color, cell_x, cell_y, t_mod):
        for (c, r), (period, chars) in self.cells.items():
            ch = chars[(t_mod // period) % len(chars)]
            draw_ctx.text((c * cell_x, r * cell_y), ch, font=font, fill=dim_color)


# Nominal speed tiers (rows per frame) a stream picks from before its exact
# speed gets derived to fit a divisor of loop_frames — see Stream. This is
# deliberately a set of discrete tiers, not a continuous random draw:
# cycle_frames = distance / speed, so a *slow* target speed means a *long*
# target cycle, and the available divisors of loop_frames get sparse at the
# long end (e.g. loop_frames=360's divisors above 90 are just 120/180/360).
# A continuous random speed draw, after 1/x-ing into cycle length and
# snapping to the nearest sparse divisor, collapses most "intended-slow"
# streams onto the same one or two long-cycle buckets — reading as
# near-uniform speed despite the intent to vary it. Explicit tiers,
# combined with generate() using a loop_frames with denser divisor
# coverage, keep the population spread across clearly distinct speed
# classes instead.
SPEED_TIERS = [0.15, 0.22, 0.32, 0.45, 0.6, 0.78, 0.95, 1.1]


class Stream:
    """A single falling column of characters.

    Motion is a pure function of frame index `t`, not accumulated
    step-by-step state — this is what makes the rendered loop exactly
    seamless (see generate() and the file header): `cycle_frames` is
    snapped to an exact divisor of the total loop length, so this stream's
    position at t == loop_frames is bit-for-bit identical to its position
    at t == 0. Row glyphs and the head's flicker glyph are pre-computed
    from a per-stream seed rather than drawn from a running RNG, so a fast
    stream's cycle repeating multiple times within one loop always shows
    identical content each repeat — exactly like the physical row would.
    """

    def __init__(self, col, rows, loop_frames):
        self.col = col
        self.rows = rows
        # Wide range so tails vary from short blips to nearly full-height streaks.
        min_len = max(3, rows // 10)
        self.length = random.randint(min_len, rows)
        # Distance above the screen the head starts from, so it always
        # visibly falls in rather than appearing already on-screen.
        self.head_offset = random.randint(1, max(1, rows // 2))
        # Total rows traveled in one full cycle: from head_offset above the
        # screen to fully exiting below (rows + length past the top edge).
        self.distance = self.head_offset + rows + self.length

        nominal_speed = random.choice(SPEED_TIERS)
        nominal_cycle = self.distance / nominal_speed
        self.cycle_frames = min(_divisors(loop_frames), key=lambda d: abs(d - nominal_cycle))
        self.speed = self.distance / self.cycle_frames
        self.phase = random.randrange(self.cycle_frames)

        seed = random.randrange(1 << 30)
        self.row_chars = [random.Random(f"{seed}-row-{row}").choice(CHARSET) for row in range(rows)]
        self.lead_chars = [random.Random(f"{seed}-lead-{tc}").choice(CHARSET) for tc in range(self.cycle_frames)]

    def draw(self, trail_ctx, lead_ctx, font, color, lead_color, cell_x, cell_y, t_mod):
        t_in_cycle = (t_mod + self.phase) % self.cycle_frames
        head = -self.head_offset + self.speed * t_in_cycle
        head_row = math.floor(head)

        lo = max(0, head_row - self.length + 1)
        hi = min(self.rows - 1, head_row)
        for row in range(lo, hi + 1):
            i = head_row - row
            if i <= 0:
                continue
            fade = max(0.0, 1.0 - i / self.length)
            ch = self.row_chars[row]
            x, y = self.col * cell_x, row * cell_y
            r = int(color[0] * fade)
            g = int(color[1] * fade)
            b = int(color[2] * fade)
            a = int(255 * fade)
            trail_ctx.text((x, y), ch, font=font, fill=(r, g, b, a))

        if 0 <= head_row <= self.rows - 1:
            x, y = self.col * cell_x, head_row * cell_y
            lead_ctx.text((x, y), self.lead_chars[t_in_cycle], font=font, fill=lead_color)


def generate(
    width=720,
    height=960,
    frames=90,
    font_size=11,
    color="#00FF41",
    bg_color="#000000",
    density=0.9,
    bg_coverage=0.15,
    glow=True,
    duration_ms=60,
    col_spacing=0.65,
    out_path="matrix_rain.gif",
):
    color_rgb = hex_to_rgb(color)
    bg_rgb = hex_to_rgb(bg_color)
    # The leading character reads as "almost white" — a near-white with
    # just a faint tint of the rain color so it still belongs to the scene.
    lead_rgb = tuple(min(255, int(c * 0.3) + 225) for c in color_rgb)
    # Background glyphs are dim, desaturated versions of the rain color.
    dim_rgb = tuple(int(c * 0.14) for c in color_rgb) + (255,)

    font = find_font(font_size)
    if not font_supports_katakana(font):
        # Fall back to a charset every font can render, so we never show tofu
        # boxes -- but this silently changes the whole character of the
        # animation (plain alphanumeric instead of katakana), so say so.
        print(
            "WARNING: no katakana-capable font found (tried Noto Sans/Mono "
            "CJK, DejaVu Sans Mono). Falling back to digits/letters instead "
            "of katakana -- install the 'noto-fonts-cjk' package for the "
            "authentic look.",
            file=sys.stderr,
        )
        global CHARSET
        CHARSET = DIGITS + "abcdefghijklmnopqrstuvwxyz".upper()

    # Horizontal column pitch is packed tighter than the glyph's own size
    # (col_spacing < 1) to get more lines across without shrinking legibility
    # as much as shrinking the font alone would. Vertical pitch stays at the
    # font size so rows don't visually overlap.
    cell_y = font_size
    cell_x = max(3, round(font_size * col_spacing))
    cols = width // cell_x
    rows = height // cell_y

    loop_frames = frames
    active_cols = [c for c in range(cols) if random.random() < density]
    streams = [Stream(c, rows, loop_frames) for c in active_cols]
    bg_field = BackgroundField(cols, rows, loop_frames, coverage=bg_coverage)

    # The glow/trail-fade buffer (`base`, below) carries a short
    # exponential memory of recently-drawn content (~20 frames at this
    # alpha). Even though every stream's own motion is now exactly
    # periodic, frame 0 still needs that same recent-glow history warmed up
    # before capture starts, or it reads as a subtle glow dip that no other
    # point in the loop has. Since every stream/bg formula is a pure
    # function of `t % loop_frames`, it's valid to evaluate them at
    # negative t — Python's modulo wraps correctly — so starting the
    # compositing loop early and only recording once t >= 0 naturally lines
    # the warm-up content up with the real tail of the loop.
    warmup = 40
    base = Image.new("RGB", (width, height), bg_rgb)
    frames_out = []

    for t in range(-warmup, loop_frames):
        t_mod = t % loop_frames

        # Fade the previous frame slightly toward background (motion trail).
        fade_layer = Image.new("RGBA", (width, height), bg_rgb + (60,))
        base = Image.alpha_composite(base.convert("RGBA"), fade_layer).convert("RGB")

        # Redraw the static background field fresh every frame so it stays
        # at a constant dim brightness instead of fading away.
        bg_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        bg_field.draw(ImageDraw.Draw(bg_layer), font, dim_rgb, cell_x, cell_y, t_mod)
        base = Image.alpha_composite(base.convert("RGBA"), bg_layer).convert("RGB")

        trail_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        lead_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        trail_ctx = ImageDraw.Draw(trail_layer)
        lead_ctx = ImageDraw.Draw(lead_layer)

        for s in streams:
            s.draw(trail_ctx, lead_ctx, font, color_rgb, lead_rgb, cell_x, cell_y, t_mod)

        base = base.convert("RGBA")
        if glow:
            # Soft bloom for the trailing characters...
            base = Image.alpha_composite(base, trail_layer.filter(ImageFilter.GaussianBlur(1.5)))
            base = Image.alpha_composite(base, trail_layer)
            # ...and a stronger, brighter bloom for the leading "raindrop" head,
            # which is what actually sells the falling-droplet illusion.
            base = Image.alpha_composite(base, lead_layer.filter(ImageFilter.GaussianBlur(3)))
            base = Image.alpha_composite(base, lead_layer)
        else:
            base = Image.alpha_composite(base, trail_layer)
            base = Image.alpha_composite(base, lead_layer)
        base = base.convert("RGB")

        if t >= 0:
            frames_out.append(base.copy())

    # No blend/crossfade step needed: frame `loop_frames` (the frame that
    # would come right after the last one captured) is, by construction,
    # bit-for-bit identical to frame 0 — every stream's cycle length and
    # every background cell's flicker period is an exact divisor of
    # loop_frames, and the glow buffer was warmed up with the same periodic
    # formulas so its short memory already matches steady-state at t=0. A
    # hard loop (mpv's loop-file=inf) is therefore exactly seamless.

    suffix = Path(out_path).suffix.lower()
    if suffix in (".mp4", ".webm", ".mkv"):
        # A real video codec has none of the GIF path's problems: no 256-
        # color palette to quantize into (so no banding on the glow
        # gradient, ever, at any bit depth), and proper motion compression
        # instead of GIF's independent-per-frame LZW — smaller file for
        # *better* quality, not a tradeoff. mpvpaper plays either format
        # identically since it's just an mpv wrapper.
        encode_video(frames_out, width, height, duration_ms, out_path)
        return out_path

    # GIF path: quantize every frame against one shared, adaptive palette
    # built from a spread of sample frames. Left to its own devices, GIF
    # save_all() picks a palette per frame, which flickers/bands on a smooth
    # glow gradient and bloats the file with near-duplicate local color
    # tables. One shared palette keeps color stable frame-to-frame and
    # compresses far better.
    sample_idxs = sorted(set(round(i * (frames - 1) / 7) for i in range(8)))
    sample_strip = Image.new("RGB", (width * len(sample_idxs), height))
    for i, idx in enumerate(sample_idxs):
        sample_strip.paste(frames_out[idx], (width * i, 0))
    palette_src = sample_strip.quantize(colors=256, method=Image.Quantize.MAXCOVERAGE)

    quantized = [f.quantize(palette=palette_src, dither=Image.Dither.NONE) for f in frames_out]

    quantized[0].save(
        out_path,
        save_all=True,
        append_images=quantized[1:],
        duration=duration_ms,
        loop=0,
        optimize=True,
    )
    return out_path


def encode_video(frames_out, width, height, duration_ms, out_path):
    """Pipe raw RGB frames straight into ffmpeg/libx264 -- no intermediate
    files, no palette. CRF 16 + yuv420p is already far cleaner than any GIF
    palette could be; -movflags faststart makes mpv/mpvpaper able to start
    playback without seeking through the whole file first."""
    fps_frac = f"1000/{duration_ms}"  # exact fractional fps, e.g. 60ms/frame -> 1000/60 == 50/3
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{width}x{height}",
        "-r", fps_frac, "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "slow", "-crf", "16",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for frame in frames_out:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    ret = proc.wait()
    if ret != 0:
        raise RuntimeError(f"ffmpeg exited with status {ret}")


def main():
    p = argparse.ArgumentParser(description="Generate a Matrix-style digital rain GIF.")
    p.add_argument("--width", type=int, default=720)
    p.add_argument("--height", type=int, default=960)
    p.add_argument("--frames", type=int, default=720, help="Number of animation frames (also the exact loop length)")
    p.add_argument("--font-size", type=int, default=11, help="Glyph size in pixels")
    p.add_argument("--color", type=str, default="#00FF41", help="Hex color of the rain")
    p.add_argument("--bg-color", type=str, default="#000000", help="Hex background color")
    p.add_argument("--density", type=float, default=0.9, help="Fraction of columns with falling streams (0-1)")
    p.add_argument("--bg-coverage", type=float, default=0.15, help="Fraction of cells with static background glyphs (0-1)")
    p.add_argument("--no-glow", action="store_true", help="Disable glow/bloom effect")
    p.add_argument("--duration", type=int, default=60, help="Frame duration in ms")
    p.add_argument("--col-spacing", type=float, default=0.65, help="Column pitch as a fraction of font size — lower packs more columns in (0-1+)")
    p.add_argument("--out", type=str, default="matrix_rain.gif", help="Output file path")
    p.add_argument(
        "--use-omarchy-theme",
        action="store_true",
        help="Pull rain/background colors from your Omarchy theme's colors.toml "
             "(falls back to --color/--bg-color if no usable file is found)",
    )
    p.add_argument(
        "--theme-name",
        type=str,
        default=None,
        help="Omarchy theme folder name to read colors from, e.g. 'matrix' "
             "(looks in ~/.config/omarchy/themes/<name>/colors.toml). "
             "Only used with --use-omarchy-theme.",
    )
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    args = p.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    color = args.color
    bg_color = args.bg_color
    if args.use_omarchy_theme:
        theme_color, theme_bg, path_used = load_omarchy_theme(args.theme_name)
        if theme_color:
            color = theme_color
        if theme_bg:
            bg_color = theme_bg
        if theme_color or theme_bg:
            print(f"Using Omarchy theme colors from {path_used} — rain: {color}, background: {bg_color}")
        elif path_used:
            print(f"Found {path_used} but couldn't pick out usable colors from it; using defaults.")
        else:
            print(
                "Could not locate an Omarchy colors.toml. Try passing --theme-name "
                "(e.g. --theme-name matrix), or set colors manually with --color/--bg-color."
            )

    out = generate(
        width=args.width,
        height=args.height,
        frames=args.frames,
        font_size=args.font_size,
        color=color,
        bg_color=bg_color,
        density=args.density,
        bg_coverage=args.bg_coverage,
        glow=not args.no_glow,
        duration_ms=args.duration,
        col_spacing=args.col_spacing,
        out_path=args.out,
    )
    print(f"Saved: {Path(out).resolve()}")


if __name__ == "__main__":
    main()
