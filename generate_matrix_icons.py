#!/usr/bin/env python3
# ============================================================================
# generate_matrix_icons.py — build the "BeautyLine-Matrix" icon theme.
#
# Takes the `beautyline` icon theme (an AUR package of outline-style icons —
# https://gitlab.com/garuda-linux/themes-and-settings/artwork/beautyline,
# installed system-wide at /usr/share/icons/BeautyLine) and builds
# "BeautyLine-Matrix", covering everything a file manager can show:
#
#  - places/{16,48}: the ~19 folder icons you actually see by default
#    (folder, folder-open, user-home, user-desktop, inode-directory, and the
#    default-folder-<xdg-dir> set) get a FULL recolor — gradient replaced
#    end to end with a dark-green-at-top-to-black-at-bottom fill. These are
#    BeautyLine's own icons, uniformly in a single-path gradient-fill style,
#    so a full stop-color replacement is safe and simple.
#
#  - everything else — places/{16,48}'s ~200 remaining decorative/legacy-
#    alias folder variants (folder-blue, folder-git, gnome-fs-directory,
#    network-server, user-trash, bookmarks, ...), all of devices/scalable
#    (drives, phones, cameras — whatever shows up when media is connected),
#    and all of mimetypes/scalable (every file-type icon) — gets a
#    DIFFERENT, more conservative treatment. Requested as "leave the colors
#    intact, just fade to black at the bottom": instead of touching each
#    icon's own (often multi-shape, sometimes non-gradient, sometimes
#    inherited from a completely different artist with nested transform
#    groups) fill, this overlays a separate black-to-transparent gradient
#    rectangle, clipped to the union of the icon's own shapes so the fade
#    never bleeds outside the artwork. The clip has to be built from
#    flattened shape geometry (each shape's cumulative transform baked into
#    a single `transform` attribute) rather than nested <g> — <clipPath>
#    only accepts shape elements as direct children per the SVG spec, so
#    nested groups inside it are silently dropped by librsvg (produces an
#    empty, invisible clip) if you don't flatten them first. Roughly a
#    third of the real (non-symlinked) icons in each category are exactly
#    this inherited nested-group case, not BeautyLine's own flat style,
#    which is why this needed the general flattening approach rather than a
#    simple regex stop-color swap.
#
#  Deliberately NOT covered: status/scalable (wifi/bluetooth signal-strength
#  icons — checked, nothing file-explorer-related in there) and apps/
#  (application launcher icons, not shown by a file manager as such) are
#  left as pure BeautyLine via `Inherits=`, since neither is part of "the
#  file explorer."
#
# Symlinks: most icon names in each category (mimetypes especially — every
# archive format pointing at one shared "package" icon, e.g.) are symlink
# aliases of one real file, not independent art. Real files are processed
# once each; symlinks whose target resolves to another file inside the same
# category are recreated pointing at our processed copy. A handful of
# symlinks point somewhere we don't cover at all (another icon theme
# entirely, or an icon category we intentionally skip) — those are left
# alone (not recreated) so `Inherits=BeautyLine,hicolor,Adwaita,breeze`
# resolves them from the original, same as any icon we don't touch.
#
# Why regenerate rather than ship the SVGs pre-rendered: BeautyLine itself
# isn't in the official Arch repos (AUR only), and its SVGs are GPL-licensed
# — redistributing modified copies is fine, but regenerating from the
# installed package on the user's own machine avoids bundling someone else's
# icon set's raw assets in this repo at all. install.sh runs this after
# confirming `beautyline` is installed.
#
# Output: ~/.local/share/icons/BeautyLine-Matrix/{index.theme,places/*,devices/*,mimetypes/*}
#
# Colors: by default reads `darker_background` from colors.toml for the
# black end (same --use-omarchy-theme / --theme-name pattern matrix_rain.py
# uses). The green end is DOWNLOAD_FOLDER_GREEN (#67FF80) below — not
# theme-derived, a specific color pulled from BeautyLine's own stock
# "Downloads" folder icon after the user compared it against an earlier
# accent-derived green and preferred it. Override either end with
# --top/--bottom (the black-fade overlay on everything else is always plain
# black, by request, regardless of --top/--bottom).
#
# Applying the theme: writing these files isn't enough on its own — the
# icon theme is only "live" after (1) `gtk-update-icon-cache -f -t <dir>`
# and (2) `gsettings set org.gnome.desktop.interface icon-theme
# BeautyLine-Matrix` (which is what icons.theme + omarchy-theme-set-gnome
# already do on every `omarchy theme set`). That gsettings key is the one
# real "default icon theme" mechanism every installed file manager here
# reads (confirmed: only Nautilus is installed, and it's a GTK4 app that
# reads this key directly) — there's no separate per-file-manager setting
# to replicate, and hand-writing a redundant gtk-3.0/settings.ini override
# would just go stale the next time a different theme is selected, since
# nothing in Omarchy's own theme-switch pipeline manages that file.
# ============================================================================
import argparse
import os
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore

SRC = Path("/usr/share/icons/BeautyLine")
DEFAULT_DST = Path.home() / ".local" / "share" / "icons" / "BeautyLine-Matrix"

# The "default" folder set a user actually sees without picking a decorative
# variant -- these get the full green-to-black recolor. Everything else in
# places/ gets the same conservative black-fade-overlay treatment as
# mimetypes/devices.
FOLDER_CORE_BASENAMES = {
    "folder", "folder-open",
    "default-folder", "default-folder-open",
    "inode-directory",
    "user-home", "user-desktop",
    "default-folder-documents", "default-folder-download",
    "default-folder-pictures", "default-folder-music",
    "default-folder-video", "default-folder-publicshare",
    "default-folder-templates", "default-folder-temp",
    "default-folder-projects", "default-folder-bookmark",
    "default-folder-saved-search", "default-folder-image-people",
}


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


# The folder-fade top color: matches BeautyLine's own stock "Downloads"
# folder icon (places/{16,48}/folder-download(s).svg's brighter gradient
# stop, #67FF80) rather than a color derived from colors.toml -- the user
# compared it directly against the accent-derived green this used before
# and preferred it. Not theme-derived on purpose: it's a specific asset
# color, not a formula.
DOWNLOAD_FOLDER_GREEN = "#67FF80"


def colors_from_theme(theme_name):
    path = Path.home() / ".config" / "omarchy" / "themes" / theme_name / "colors.toml"
    if not path.exists():
        return None
    data = tomllib.loads(path.read_text())
    darker_bg = data.get("darker_background")
    if not darker_bg:
        return None
    bottom = darker_bg
    top = DOWNLOAD_FOLDER_GREEN
    return top, bottom


# --- Full recolor (folder-core) --------------------------------------------

def recolor_folder_svg(text, height, top_rgb, bottom_rgb):
    def lerp_color(t):
        t = max(0.0, min(1.0, t))
        return rgb_to_hex(tuple(top_rgb[i] + (bottom_rgb[i] - top_rgb[i]) * t for i in range(3)))

    def fix_gradient_tag(m):
        return re.sub(
            r'x1="[^"]*"\s*y1="[^"]*"\s*x2="[^"]*"\s*y2="[^"]*"',
            f'x1="{height / 2}" y1="0" x2="{height / 2}" y2="{height}"',
            m.group(0),
        )

    text = re.sub(r"<linearGradient\b[^>]*>", fix_gradient_tag, text)

    def fix_stop(m):
        tag = m.group(0)
        off_m = re.search(r'offset="([^"]*)"', tag)
        if off_m:
            raw = off_m.group(1)
            t = float(raw.rstrip("%")) / 100.0 if raw.endswith("%") else float(raw)
        else:
            t = 0.0
        color = lerp_color(t)
        if 'stop-color="' in tag:
            tag = re.sub(r'stop-color="[^"]*"', f'stop-color="{color}"', tag)
        else:
            tag = tag.replace("<stop", f'<stop stop-color="{color}"', 1)
        return tag

    return re.sub(r"<stop\b[^>]*/?>", fix_stop, text)


# --- Black-fade overlay (everything else) -----------------------------------

SHAPE_TAGS = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}
GEOM_ATTRS = {
    "path": ["d"],
    "rect": ["x", "y", "width", "height", "rx", "ry"],
    "circle": ["cx", "cy", "r"],
    "ellipse": ["cx", "cy", "rx", "ry"],
    "polygon": ["points"],
    "polyline": ["points"],
    "line": ["x1", "y1", "x2", "y2"],
}
IDENT = (1, 0, 0, 1, 0, 0)


def mat_mul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (
        a1 * a2 + c1 * b2,
        b1 * a2 + d1 * b2,
        a1 * c2 + c1 * d2,
        b1 * c2 + d1 * d2,
        a1 * e2 + c1 * f2 + e1,
        b1 * e2 + d1 * f2 + f1,
    )


def parse_svg_transform(s):
    if not s:
        return IDENT
    m = IDENT
    for fn, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s):
        nums = [float(x) for x in re.findall(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", args)]
        if fn == "matrix" and len(nums) == 6:
            t = tuple(nums)
        elif fn == "translate":
            t = (1, 0, 0, 1, nums[0], nums[1] if len(nums) > 1 else 0)
        elif fn == "scale":
            sx = nums[0]
            sy = nums[1] if len(nums) > 1 else sx
            t = (sx, 0, 0, sy, 0, 0)
        elif fn == "rotate" and len(nums) == 1:
            import math
            a = math.radians(nums[0])
            t = (math.cos(a), math.sin(a), -math.sin(a), math.cos(a), 0, 0)
        else:
            t = IDENT
        m = mat_mul(m, t)
    return m


def collect_shapes(el, parent_matrix, out):
    my_matrix = mat_mul(parent_matrix, parse_svg_transform(el.get("transform")))
    name = el.tag.split("}")[-1]
    if name in SHAPE_TAGS:
        clone = ET.Element(f"{{{SVG_NS}}}{name}")
        for attr in GEOM_ATTRS[name]:
            if el.get(attr) is not None:
                clone.set(attr, el.get(attr))
        if my_matrix != IDENT:
            a, b, c, d, e, f = my_matrix
            clone.set("transform", f"matrix({a},{b},{c},{d},{e},{f})")
        fill_rule = el.get("fill-rule")
        if not fill_rule:
            style_m = re.search(r"fill-rule:\s*([a-z]+)", el.get("style", "") or "")
            fill_rule = style_m.group(1) if style_m else None
        if fill_rule:
            clone.set("clip-rule", fill_rule)
        out.append(clone)
    for child in el:
        collect_shapes(child, my_matrix, out)


def svg_size(root):
    vb = root.get("viewBox")
    if vb:
        parts = vb.split()
        return float(parts[2]), float(parts[3])
    return float(root.get("width", 48)), float(root.get("height", 48))


def fade_svg_file(src_path, dst_path):
    """Overlay a black-fade-at-the-bottom clip; original colors untouched."""
    tree = ET.parse(src_path)
    root = tree.getroot()
    width, height = svg_size(root)

    shapes = []
    for child in root:
        collect_shapes(child, IDENT, shapes)
    if not shapes:
        shutil.copy(src_path, dst_path)
        return

    defs = root.find(f"{{{SVG_NS}}}defs")
    if defs is None:
        defs = ET.Element(f"{{{SVG_NS}}}defs")
        root.insert(0, defs)

    clip = ET.SubElement(defs, f"{{{SVG_NS}}}clipPath")
    clip.set("id", "mx-fade-clip")
    for s in shapes:
        clip.append(s)

    grad = ET.SubElement(defs, f"{{{SVG_NS}}}linearGradient")
    grad.set("id", "mx-fade-grad")
    grad.set("x1", str(width / 2)); grad.set("y1", "0")
    grad.set("x2", str(width / 2)); grad.set("y2", str(height))
    grad.set("gradientUnits", "userSpaceOnUse")
    s0 = ET.SubElement(grad, f"{{{SVG_NS}}}stop")
    s0.set("offset", "0"); s0.set("stop-color", "#000000"); s0.set("stop-opacity", "0")
    s1 = ET.SubElement(grad, f"{{{SVG_NS}}}stop")
    s1.set("offset", "1"); s1.set("stop-color", "#000000"); s1.set("stop-opacity", "1")

    rect = ET.SubElement(root, f"{{{SVG_NS}}}rect")
    rect.set("x", "0"); rect.set("y", "0")
    rect.set("width", str(width)); rect.set("height", str(height))
    rect.set("fill", "url(#mx-fade-grad)")
    rect.set("clip-path", "url(#mx-fade-clip)")

    tree.write(dst_path, xml_declaration=True, encoding="UTF-8")


def recreate_symlinks(scope_src, scope_dst, extra_search_dirs=()):
    """Recreate symlinks whose target resolves inside scope_src (or one of
    extra_search_dirs, each an (src_dir, dst_dir) pair already generated)
    -- anything else is left alone so Inherits= resolves it from the
    original theme/location instead."""
    search = [(scope_src, scope_dst)] + list(extra_search_dirs)
    recreated = 0
    for link in scope_src.rglob("*.svg"):
        if not link.is_symlink():
            continue
        target = Path(os.readlink(link))
        resolved = target if target.is_absolute() else (link.parent / target).resolve()
        rel_link = link.relative_to(scope_src)
        placed = False
        for s_src, s_dst in search:
            try:
                rel_target = resolved.relative_to(s_src.resolve())
            except ValueError:
                continue
            candidate = s_dst / rel_target
            if candidate.exists() or candidate.is_symlink():
                out_link = scope_dst / rel_link
                out_link.parent.mkdir(parents=True, exist_ok=True)
                rel_path = os.path.relpath(candidate, out_link.parent)
                if out_link.exists() or out_link.is_symlink():
                    out_link.unlink()
                out_link.symlink_to(rel_path)
                recreated += 1
                placed = True
                break
        if not placed:
            continue
    return recreated


def generate_fade_category(name, dst):
    """apps-style flat category: <SRC>/<name> -> <dst>/<name>, black-fade
    overlay on every real file, symlinks recreated where the target is
    inside the same category."""
    src_dir = SRC / name
    if not src_dir.exists():
        return 0, 0
    out_dir = dst / name
    out_dir.mkdir(parents=True, exist_ok=True)

    real_files = sorted(
        f for f in src_dir.rglob("*.svg")
        if not f.is_symlink() and f.is_file()
    )
    ok = 0
    for f in real_files:
        rel = f.relative_to(src_dir)
        out_path = out_dir / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fade_svg_file(f, out_path)
            ok += 1
        except Exception as e:
            print(f"  Skipping {f} ({e}) — copied unmodified.", file=sys.stderr)
            shutil.copy(f, out_path)

    links = recreate_symlinks(src_dir, out_dir)
    return ok, links


def generate_places(dst, top_rgb, bottom_rgb):
    out_root = dst / "places"
    ok_core = ok_fade = 0
    for size in ("16", "48"):
        src_dir = SRC / "places" / size
        if not src_dir.exists():
            continue
        out_dir = out_root / size
        out_dir.mkdir(parents=True)
        real_files = sorted(
            f for f in src_dir.iterdir()
            if f.suffix == ".svg" and not f.is_symlink() and f.is_file()
        )
        for f in real_files:
            out_path = out_dir / f.name
            if f.stem in FOLDER_CORE_BASENAMES:
                m = re.search(r'viewBox="0 0 (\S+) (\S+)"', f.read_text())
                height = float(m.group(2)) if m else float(size)
                out_path.write_text(recolor_folder_svg(f.read_text(), height, top_rgb, bottom_rgb))
                ok_core += 1
            else:
                try:
                    fade_svg_file(f, out_path)
                    ok_fade += 1
                except Exception as e:
                    print(f"  Skipping {f} ({e}) — copied unmodified.", file=sys.stderr)
                    shutil.copy(f, out_path)

    links = recreate_symlinks(SRC / "places", out_root)
    return ok_core, ok_fade, links


def write_index_theme(dst):
    (dst / "index.theme").write_text(
        "[Icon Theme]\n"
        "Name=BeautyLine-Matrix\n"
        "Comment=BeautyLine with Matrix-green folders and black-fade file/device icons\n"
        "Inherits=BeautyLine,hicolor,Adwaita,breeze\n"
        "Directories=places/16,places/48,devices/scalable,mimetypes/scalable\n\n"
        "[places/16]\n"
        "Size=16\n"
        "Context=Places\n"
        "MinSize=8\n"
        "MaxSize=48\n"
        "Type=Scalable\n\n"
        "[places/48]\n"
        "Size=48\n"
        "Context=Places\n"
        "MinSize=48\n"
        "MaxSize=512\n"
        "Type=Scalable\n\n"
        "[devices/scalable]\n"
        "Context=Devices\n"
        "Size=22\n"
        "MinSize=8\n"
        "MaxSize=192\n"
        "Type=Scalable\n\n"
        "[mimetypes/scalable]\n"
        "Context=MimeTypes\n"
        "Size=96\n"
        "MinSize=8\n"
        "MaxSize=512\n"
        "Type=Scalable\n"
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--top", default=None, help="Hex color for the top of the folder fade (default: from theme, else dark green)")
    p.add_argument("--bottom", default=None, help="Hex color for the bottom of the folder fade (default: from theme, else black)")
    p.add_argument("--theme-name", default="matrix", help="Omarchy theme folder to pull colors from")
    p.add_argument("--dst", default=str(DEFAULT_DST), help="Output icon theme directory")
    args = p.parse_args()

    if not SRC.exists():
        sys.exit(f"BeautyLine isn't installed ({SRC} not found) — install it first (AUR: beautyline).")

    top, bottom = args.top, args.bottom
    if top is None or bottom is None:
        derived = colors_from_theme(args.theme_name)
        top = top or (derived[0] if derived else DOWNLOAD_FOLDER_GREEN)
        bottom = bottom or (derived[1] if derived else "#020302")

    top_rgb, bottom_rgb = hex_to_rgb(top), hex_to_rgb(bottom)
    dst = Path(args.dst)
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    write_index_theme(dst)

    core, places_fade, places_links = generate_places(dst, top_rgb, bottom_rgb)
    print(f"places: {core} recolored folders, {places_fade} black-faded, {places_links} symlinks (fade {top} -> {bottom})")

    dev_ok, dev_links = generate_fade_category("devices/scalable", dst)
    print(f"devices: {dev_ok} black-faded, {dev_links} symlinks")

    mime_ok, mime_links = generate_fade_category("mimetypes/scalable", dst)
    print(f"mimetypes: {mime_ok} black-faded, {mime_links} symlinks")


if __name__ == "__main__":
    main()
