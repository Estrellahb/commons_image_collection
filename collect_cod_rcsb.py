#!/usr/bin/env python3
"""Fetch real COD CIF crystals and RCSB PDB complexes, compute GT, and render 3D PNGs."""

from __future__ import annotations

import argparse
import ast
from collections import Counter
from io import BytesIO
import json
import math
import operator
from pathlib import Path
import re
import time
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont
import requests

from local_registry import atomic_write_bytes, register_local_claims


DEFAULT_IMG_ROOT = Path(__file__).resolve().parent / "img"
DEFAULT_DB_PATH = Path(__file__).resolve().parent / "采集数据.sqlite"

COD_BASE_URL = "https://www.crystallography.net/cod"
RCSB_SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
RCSB_PDB_BASE_URL = "https://files.rcsb.org/download"

MAX_IMAGE_BYTES = 3_000_000
RENDER_WIDTH = 1600
RENDER_HEIGHT = 900
SSAA_SCALE = 2

# Curated verified ordered COD IDs across crystal systems + fallback element searches.
CURATED_COD_IDS: list[str] = [
    "1000022",  # Perovskite CaTiO3 (orthorhombic Pbnm)
    "1000017",  # Corundum Al2O3 (trigonal R-3c:H)
    "1000041",  # Halite NaCl (cubic Fm-3m)
    "1000007",  # Diopside CaMgSi2O6 (monoclinic C2/c)
    "1008006",  # Fe2SiS4 olivine (orthorhombic Pnma)
    "1008007",  # Fe2GeS4 (orthorhombic Pnma)
    "1000332",  # BaTiOF4 (orthorhombic Pbcm)
    "1000341",  # Ba2TiOF6 (monoclinic Cc)
    "1001090",  # BiFeO3 (trigonal R3c:H)
    "1004019",  # (NH4)2MoS4 (orthorhombic Pnma)
    "1000052",  # Huntite Mg3Ca(CO3)4 (trigonal R32:H)
    "1001451",  # LiFeP2O7 (monoclinic P21)
    "1000028",  # Sodalite Na8Al6Si6O24Cl2 (cubic P-43n)
    "1001203",  # CaCu3Ti4O12
    "1008077",  # CaTi2O4
    "1000423",  # Cs2ZrSi6O15
    "1010541",  # Beryl Al2Be3Si6O18
    "1011072",  # Euclase AlBeHSiO5
    "1010940",  # Chalcopyrite CuFeS2
    "1010318",  # CuFeS2 tetragonal variant
    "1001031",  # Fallback ordered check
]

FALLBACK_COD_QUERIES: list[dict[str, str]] = [
    {"el1": "Ca", "el2": "Ti", "el3": "O", "nel": "3", "format": "json"},
    {"el1": "Zr", "el2": "Si", "el3": "O", "nel": "3", "format": "json"},
    {"el1": "Be", "el2": "Si", "el3": "O", "nel": "3", "format": "json"},
    {"el1": "Cu", "el2": "Fe", "el3": "S", "nel": "3", "format": "json"},
    {"el1": "Fe", "el2": "S", "nel": "2", "format": "json"},
]

# CPK / VESTA-inspired RGB colors and covalent radii (Angstrom) for crystals.
ELEMENT_STYLE: dict[str, tuple[tuple[int, int, int], float, float]] = {
    # Symbol: (RGB, display_radius_A, covalent_radius_A)
    "H": ((225, 229, 235), 0.28, 0.31),
    "Li": ((168, 85, 247), 0.48, 1.28),
    "Be": ((132, 204, 22), 0.44, 0.96),
    "B": ((244, 114, 182), 0.42, 0.84),
    "C": ((55, 65, 81), 0.38, 0.76),
    "N": ((37, 99, 235), 0.38, 0.71),
    "O": ((220, 38, 38), 0.42, 0.66),
    "F": ((34, 197, 94), 0.40, 0.57),
    "Na": ((147, 51, 234), 0.54, 1.66),
    "Mg": ((22, 163, 74), 0.52, 1.41),
    "Al": ((100, 116, 139), 0.50, 1.21),
    "Si": ((217, 119, 6), 0.48, 1.11),
    "P": ((234, 88, 12), 0.46, 1.07),
    "S": ((234, 179, 8), 0.48, 1.05),
    "Cl": ((16, 185, 129), 0.50, 1.02),
    "K": ((126, 34, 206), 0.60, 2.03),
    "Ca": ((13, 148, 136), 0.58, 1.76),
    "Ti": ((71, 85, 105), 0.52, 1.60),
    "V": ((107, 114, 128), 0.52, 1.53),
    "Cr": ((59, 130, 246), 0.52, 1.39),
    "Mn": ((168, 85, 247), 0.52, 1.39),
    "Fe": ((180, 83, 9), 0.52, 1.32),
    "Co": ((219, 39, 119), 0.52, 1.26),
    "Ni": ((22, 163, 74), 0.52, 1.24),
    "Cu": ((194, 65, 12), 0.52, 1.32),
    "Zn": ((99, 102, 241), 0.52, 1.22),
    "Ge": ((14, 116, 144), 0.50, 1.20),
    "Sr": ((5, 150, 105), 0.62, 1.95),
    "Zr": ((14, 165, 233), 0.58, 1.75),
    "Nb": ((6, 182, 212), 0.56, 1.64),
    "Mo": ((20, 184, 166), 0.56, 1.54),
    "Cs": ((139, 92, 246), 0.66, 2.44),
    "Ba": ((21, 128, 61), 0.64, 2.15),
    "Tl": ((124, 58, 237), 0.58, 1.45),
    "Pb": ((75, 85, 99), 0.62, 1.46),
    "Bi": ((147, 51, 234), 0.60, 1.48),
}
NONMETALS = {"H", "B", "C", "N", "O", "F", "P", "S", "Cl", "Se", "Br", "I"}

# Okabe-Ito colorblind-safe palette for PDB chains (excluding gold highlight).
CHAIN_COLORS: list[tuple[int, int, int]] = [
    (0, 114, 178),    # Blue
    (213, 94, 0),     # Vermilion
    (0, 158, 115),    # Bluish green
    (204, 121, 167),  # Reddish purple
]
INTERFACE_HIGHLIGHT_RGB = (245, 158, 11)  # Gold/Amber for <= 4.2 A contact residues

AA3_TO_1 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "U", "PYL": "O",
}

_SAFE_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_SAFE_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = (
        ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"]
        if bold
        else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"]
    )
    for path in candidates:
        if Path(path).is_file():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


class ZBufferCanvas:
    """Vectorized NumPy 3D Z-buffer for crisp shaded spheres & cylinders with 2x SSAA."""

    def __init__(self, width: int, height: int, bg_rgb: tuple[int, int, int] = (248, 250, 252)):
        self.width = width
        self.height = height
        self.color = np.empty((height, width, 3), dtype=np.uint8)
        self.color[:, :] = bg_rgb
        self.zbuf = np.full((height, width), -1e9, dtype=np.float32)
        light = np.array([-0.38, -0.46, 0.80], dtype=np.float32)
        self.light = light / np.linalg.norm(light)
        half = self.light + np.array([0.0, 0.0, 1.0], dtype=np.float32)
        self.half = half / np.linalg.norm(half)

    def draw_sphere(
        self,
        cx: float,
        cy: float,
        cz: float,
        radius: float,
        rgb: tuple[int, int, int],
        rim_rgb: tuple[int, int, int] | None = None,
    ) -> None:
        if radius < 1.0:
            return
        x0 = max(0, int(math.floor(cx - radius - 1)))
        x1 = min(self.width, int(math.ceil(cx + radius + 1)))
        y0 = max(0, int(math.floor(cy - radius - 1)))
        y1 = min(self.height, int(math.ceil(cy + radius + 1)))
        if x1 <= x0 or y1 <= y0:
            return

        xs = np.arange(x0, x1, dtype=np.float32)[None, :] - np.float32(cx)
        ys = np.arange(y0, y1, dtype=np.float32)[:, None] - np.float32(cy)
        r2 = xs * xs + ys * ys
        rad2 = np.float32(radius * radius)
        inside = r2 <= rad2
        if not np.any(inside):
            return

        inv_r = np.float32(1.0 / radius)
        nx = xs * inv_r
        ny = ys * inv_r
        nz = np.sqrt(np.maximum(0.0, 1.0 - (r2 / rad2)))
        z_surf = np.float32(cz) + nz * np.float32(radius)

        zb_sub = self.zbuf[y0:y1, x0:x1]
        vis = inside & (z_surf > zb_sub)
        if not np.any(vis):
            return
        zb_sub[vis] = z_surf[vis]

        ndotl = np.maximum(0.0, nx * self.light[0] + ny * self.light[1] + nz * self.light[2])
        ndoth = np.maximum(0.0, nx * self.half[0] + ny * self.half[1] + nz * self.half[2])
        spec = np.power(ndoth, 28) * 0.42
        diffuse = 0.28 + 0.72 * ndotl

        base = np.array(rgb, dtype=np.float32)
        if rim_rgb is not None:
            rim_mask = vis & (nz < 0.42)
        else:
            rim_mask = None

        shaded = np.clip(
            base[None, None, :] * diffuse[:, :, None] + spec[:, :, None] * 255.0,
            0,
            255,
        ).astype(np.uint8)
        # Subtle dark silhouette contour for separation among overlapping spheres.
        contour = nz < 0.22
        shaded[contour] = (shaded[contour].astype(np.float32) * 0.65).astype(np.uint8)
        if rim_mask is not None and np.any(rim_mask):
            shaded[rim_mask] = np.array(rim_rgb, dtype=np.uint8)

        c_sub = self.color[y0:y1, x0:x1]
        c_sub[vis] = shaded[vis]

    def draw_cylinder(
        self,
        p0: tuple[float, float, float],
        p1: tuple[float, float, float],
        radius: float,
        rgb: tuple[int, int, int],
    ) -> None:
        x0, y0, z0 = p0
        x1, y1, z1 = p1
        dx, dy = x1 - x0, y1 - y0
        len2d = math.hypot(dx, dy)
        if len2d < 1e-4 or radius < 0.8:
            return
        bx0 = max(0, int(math.floor(min(x0, x1) - radius - 1)))
        bx1 = min(self.width, int(math.ceil(max(x0, x1) + radius + 1)))
        by0 = max(0, int(math.floor(min(y0, y1) - radius - 1)))
        by1 = min(self.height, int(math.ceil(max(y0, y1) + radius + 1)))
        if bx1 <= bx0 or by1 <= by0:
            return

        gx = np.arange(bx0, bx1, dtype=np.float32)[None, :]
        gy = np.arange(by0, by1, dtype=np.float32)[:, None]
        vx, vy = np.float32(dx), np.float32(dy)
        denom = np.float32(dx * dx + dy * dy)
        t = ((gx - np.float32(x0)) * vx + (gy - np.float32(y0)) * vy) / denom
        inside_seg = (t >= 0.0) & (t <= 1.0)
        if not np.any(inside_seg):
            return

        px = np.float32(x0) + t * vx
        py = np.float32(y0) + t * vy
        perp_x = -vy / np.float32(len2d)
        perp_y = vx / np.float32(len2d)
        signed_d = (gx - px) * perp_x + (gy - py) * perp_y
        inside = inside_seg & (np.abs(signed_d) <= np.float32(radius))
        if not np.any(inside):
            return

        nx_loc = np.clip(signed_d / np.float32(radius), -1.0, 1.0)
        nz = np.sqrt(np.maximum(0.0, 1.0 - nx_loc * nx_loc))
        nx = nx_loc * perp_x
        ny = nx_loc * perp_y
        z_surf = np.float32(z0) + t * np.float32(z1 - z0) + nz * np.float32(radius)

        zb_sub = self.zbuf[by0:by1, bx0:bx1]
        vis = inside & (z_surf > zb_sub)
        if not np.any(vis):
            return
        zb_sub[vis] = z_surf[vis]

        ndotl = np.maximum(0.0, nx * self.light[0] + ny * self.light[1] + nz * self.light[2])
        shade = (0.35 + 0.65 * ndotl)[:, :, None]
        base = np.array(rgb, dtype=np.float32)[None, None, :]
        shaded = np.clip(base * shade, 0, 255).astype(np.uint8)
        c_sub = self.color[by0:by1, bx0:bx1]
        c_sub[vis] = shaded[vis]

    def to_pil(self) -> Image.Image:
        return Image.fromarray(self.color, mode="RGB")


def _encode_png(img: Image.Image, max_bytes: int = MAX_IMAGE_BYTES) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    data = buf.getvalue()
    if len(data) <= max_bytes:
        return data
    quant = img.convert("P", palette=Image.Palette.ADAPTIVE, colors=256)
    buf2 = BytesIO()
    quant.save(buf2, format="PNG", optimize=True)
    data2 = buf2.getvalue()
    if len(data2) <= max_bytes:
        return data2
    raise ValueError(f"Rendered PNG exceeds {max_bytes} bytes ({len(data2)})")


# ---------------------------------------------------------------------------
# CIF parsing, symmetry expansion, crystal bond calculation & rendering
# ---------------------------------------------------------------------------


def parse_cif_number(raw: str) -> float | None:
    """Parse a CIF float, fraction ('1/3'), or value with uncertainty ('5.380(1)')."""
    text = raw.strip().strip("'\"")
    if not text or text in (".", "?"):
        return None
    text = re.sub(r"\([^)]*\)$", "", text).strip()
    if "/" in text:
        parts = text.split("/", 1)
        return float(parts[0]) / float(parts[1])
    return float(text)


def normalize_element_symbol(raw_symbol: str, raw_label: str = "") -> str:
    """Extract clean chemical element symbol from CIF _atom_site_type_symbol / label."""
    for candidate in (raw_symbol, raw_label):
        token = candidate.strip().strip("'\"")
        match = re.match(r"^([A-Za-z]{1,2})", token)
        if match:
            sym = match.group(1)
            return sym[0].upper() + sym[1:].lower()
    return ""


def _tokenize_cif_lines(text: str) -> list[str]:
    """Tokenize a CIF data block respecting quotes, comments, and ;...; blocks."""
    tokens: list[str] = []
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if line.startswith(";"):
            block_lines = [line[1:]]
            i += 1
            while i < n and not lines[i].startswith(";"):
                block_lines.append(lines[i])
                i += 1
            tokens.append("\n".join(block_lines))
            i += 1
            continue
        pos = 0
        m = len(line)
        while pos < m:
            ch = line[pos]
            if ch.isspace():
                pos += 1
                continue
            if ch == "#":
                break
            if ch in ("'", '"'):
                quote = ch
                pos += 1
                start = pos
                while pos < m and not (
                    line[pos] == quote and (pos + 1 == m or line[pos + 1].isspace())
                ):
                    pos += 1
                tokens.append(line[start:pos])
                pos += 1
            else:
                start = pos
                while pos < m and not line[pos].isspace():
                    pos += 1
                tokens.append(line[start:pos])
        i += 1
    return tokens


def parse_cif_structure(cif_text: str) -> dict[str, Any]:
    """Parse scalars and loops from the primary CIF data block."""
    tokens = _tokenize_cif_lines(cif_text)
    scalars: dict[str, str] = {}
    loops: list[tuple[list[str], list[list[str]]]] = []

    i = 0
    n = len(tokens)
    while i < n:
        tok = tokens[i]
        low = tok.lower()
        if low.startswith("data_"):
            if scalars or loops:
                break
            scalars["_data_block"] = tok[5:]
            i += 1
            continue
        if low == "loop_":
            i += 1
            cols: list[str] = []
            while i < n and tokens[i].startswith("_"):
                cols.append(tokens[i].lower())
                i += 1
            rows: list[list[str]] = []
            if cols:
                while i < n and not tokens[i].startswith("_") and tokens[i].lower() not in ("loop_",) and not tokens[i].lower().startswith("data_"):
                    if i + len(cols) > n:
                        break
                    rows.append(tokens[i : i + len(cols)])
                    i += len(cols)
                loops.append((cols, rows))
            continue
        if tok.startswith("_"):
            if i + 1 < n:
                scalars[low] = tokens[i + 1]
                i += 2
            else:
                i += 1
            continue
        i += 1

    symops: list[str] = []
    sites: list[dict[str, Any]] = []
    for cols, rows in loops:
        for sym_col in ("_space_group_symop_operation_xyz", "_symmetry_equiv_pos_as_xyz"):
            if sym_col in cols:
                idx = cols.index(sym_col)
                symops.extend(r[idx].strip() for r in rows if r[idx].strip())
        if "_atom_site_fract_x" in cols and "_atom_site_fract_y" in cols and "_atom_site_fract_z" in cols:
            ix = cols.index("_atom_site_fract_x")
            iy = cols.index("_atom_site_fract_y")
            iz = cols.index("_atom_site_fract_z")
            ilabel = cols.index("_atom_site_label") if "_atom_site_label" in cols else -1
            isym = cols.index("_atom_site_type_symbol") if "_atom_site_type_symbol" in cols else -1
            iocc = cols.index("_atom_site_occupancy") if "_atom_site_occupancy" in cols else -1
            for r in rows:
                fx = parse_cif_number(r[ix])
                fy = parse_cif_number(r[iy])
                fz = parse_cif_number(r[iz])
                if fx is None or fy is None or fz is None:
                    continue
                occ = parse_cif_number(r[iocc]) if iocc >= 0 else 1.0
                occ = 1.0 if occ is None else occ
                sym = normalize_element_symbol(
                    r[isym] if isym >= 0 else "",
                    r[ilabel] if ilabel >= 0 else "",
                )
                label = r[ilabel] if ilabel >= 0 else sym
                if sym:
                    sites.append(
                        {
                            "label": label,
                            "element": sym,
                            "fract": (fx, fy, fz),
                            "occupancy": occ,
                        }
                    )

    a = parse_cif_number(scalars.get("_cell_length_a", ""))
    b = parse_cif_number(scalars.get("_cell_length_b", ""))
    c = parse_cif_number(scalars.get("_cell_length_c", ""))
    alpha = parse_cif_number(scalars.get("_cell_angle_alpha", "90")) or 90.0
    beta = parse_cif_number(scalars.get("_cell_angle_beta", "90")) or 90.0
    gamma = parse_cif_number(scalars.get("_cell_angle_gamma", "90")) or 90.0
    if not (a and b and c):
        raise ValueError("Missing unit cell lengths")

    if not symops:
        symops = ["x,y,z"]

    hm_sg = (
        scalars.get("_symmetry_space_group_name_h-m")
        or scalars.get("_space_group_name_h-m_alt")
        or scalars.get("_cod_original_sg_symbol_h-m")
        or ""
    ).strip()
    it_num = parse_cif_number(
        scalars.get("_space_group_it_number") or scalars.get("_symmetry_int_tables_number") or ""
    )
    z_val = parse_cif_number(scalars.get("_cell_formula_units_z", ""))
    vol_reported = parse_cif_number(scalars.get("_cell_volume", ""))

    return {
        "cell": (a, b, c, alpha, beta, gamma),
        "space_group_hm": hm_sg,
        "space_group_number": int(round(it_num)) if it_num else None,
        "z_formula": int(round(z_val)) if z_val else None,
        "volume_reported": vol_reported,
        "formula_sum": (scalars.get("_chemical_formula_sum") or "").strip(),
        "mineral_name": (
            scalars.get("_chemical_name_mineral") or scalars.get("_chemical_name_systematic") or ""
        ).strip(),
        "symops": symops,
        "sites": sites,
    }


def _eval_symop_ast(node: ast.AST, env: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _eval_symop_ast(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Name) and node.id in env:
        return env[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY:
        return _SAFE_UNARY[type(node.op)](_eval_symop_ast(node.operand, env))
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINOPS:
        return _SAFE_BINOPS[type(node.op)](
            _eval_symop_ast(node.left, env), _eval_symop_ast(node.right, env)
        )
    raise ValueError(f"Unsupported AST in symop: {ast.dump(node)}")


def apply_symop(expr_xyz: str, fx: float, fy: float, fz: float) -> tuple[float, float, float]:
    """Evaluate a CIF symmetry operation string like '1/2-x, 1/2+y, -z' safely."""
    parts = [p.strip() for p in expr_xyz.lower().split(",")]
    if len(parts) != 3:
        raise ValueError(f"Invalid symop: {expr_xyz!r}")
    env = {"x": fx, "y": fy, "z": fz}
    coords = tuple(_eval_symop_ast(ast.parse(p, mode="eval"), env) % 1.0 for p in parts)
    return coords[0], coords[1], coords[2]


def fractional_to_cartesian_matrix(
    a: float, b: float, c: float, alpha_deg: float, beta_deg: float, gamma_deg: float
) -> tuple[np.ndarray, float]:
    """Return 3x3 column matrix M (cart = M @ frac) and unit-cell volume (Angstrom^3)."""
    ar = math.radians(alpha_deg)
    br = math.radians(beta_deg)
    gr = math.radians(gamma_deg)
    ca, cb, cg = math.cos(ar), math.cos(br), math.cos(gr)
    sg = math.sin(gr)
    v_a = np.array([a, 0.0, 0.0], dtype=np.float64)
    v_b = np.array([b * cg, b * sg, 0.0], dtype=np.float64)
    cx = c * cb
    cy = c * (ca - cb * cg) / sg
    cz2 = max(1e-9, c * c - cx * cx - cy * cy)
    v_c = np.array([cx, cy, math.sqrt(cz2)], dtype=np.float64)
    mat = np.column_stack([v_a, v_b, v_c])
    vol = float(abs(np.linalg.det(mat)))
    return mat, vol


def expand_unit_cell(parsed: dict[str, Any]) -> dict[str, Any]:
    """Expand CIF asymmetric unit via symmetry ops and compute exact bonds."""
    sites = parsed["sites"]
    if not sites:
        raise ValueError("No atom sites in CIF")
    if any(not (0.99 <= s["occupancy"] <= 1.01) for s in sites):
        raise ValueError("Partial occupancy / disordered structure skipped")

    mat, vol_calc = fractional_to_cartesian_matrix(*parsed["cell"])
    symops = parsed["symops"]

    unit_atoms: list[dict[str, Any]] = []
    # Deduplicate using minimum-image Cartesian distance (< 0.15 A) to handle edges cleanly.
    tol_cart = 0.15
    for site in sites:
        fx0, fy0, fz0 = site["fract"]
        for op in symops:
            fx, fy, fz = apply_symop(op, fx0, fy0, fz0)
            fx = 0.0 if abs(fx) < 1e-6 or abs(fx - 1.0) < 1e-6 else fx
            fy = 0.0 if abs(fy) < 1e-6 or abs(fy - 1.0) < 1e-6 else fy
            fz = 0.0 if abs(fz) < 1e-6 or abs(fz - 1.0) < 1e-6 else fz

            dup = False
            for ex in unit_atoms:
                df = np.array([fx - ex["fract"][0], fy - ex["fract"][1], fz - ex["fract"][2]])
                df -= np.round(df)
                if float(np.linalg.norm(mat @ df)) < tol_cart:
                    dup = True
                    break
            if not dup:
                cart = mat @ np.array([fx, fy, fz])
                unit_atoms.append(
                    {
                        "element": site["element"],
                        "label": site["label"],
                        "fract": [round(float(fx), 6), round(float(fy), 6), round(float(fz), 6)],
                        "cart": [float(cart[0]), float(cart[1]), float(cart[2])],
                    }
                )

    if not (4 <= len(unit_atoms) <= 160):
        raise ValueError(f"Unit cell atom count {len(unit_atoms)} out of clean range [4, 160]")

    # Generate [0, 1]^3 boundary image atoms strictly for visual completeness on faces/edges.
    boundary_atoms: list[dict[str, Any]] = []
    shifts = (-1, 0, 1)
    b_tol = 0.025
    for idx, atom in enumerate(unit_atoms):
        fx, fy, fz = atom["fract"]
        for sx in shifts:
            nx = fx + sx
            if not (-b_tol <= nx <= 1.0 + b_tol):
                continue
            for sy in shifts:
                ny = fy + sy
                if not (-b_tol <= ny <= 1.0 + b_tol):
                    continue
                for sz in shifts:
                    nz = fz + sz
                    if not (-b_tol <= nz <= 1.0 + b_tol):
                        continue
                    cart = mat @ np.array([nx, ny, nz])
                    boundary_atoms.append(
                        {
                            "unit_idx": idx,
                            "element": atom["element"],
                            "fract": [float(nx), float(ny), float(nz)],
                            "cart": cart,
                        }
                    )

    # Bond detection within [0,1]^3 display atoms + periodic unique bonds in [0,1)^3.
    def _bond_cutoff(e1: str, e2: str) -> float | None:
        r1 = ELEMENT_STYLE.get(e1, ((128, 128, 128), 0.5, 1.4))[2]
        r2 = ELEMENT_STYLE.get(e2, ((128, 128, 128), 0.5, 1.4))[2]
        nm1, nm2 = e1 in NONMETALS, e2 in NONMETALS
        if nm1 and nm2:
            # Skip unbonded O-O / F-F / Cl-Cl unless O-O peroxide (< 1.65 A) or C/N/P/S/H bonds.
            if e1 == "H" and e2 == "H":
                return None
            return min(2.15, 1.25 * (r1 + r2))
        if not nm1 and not nm2:
            # Avoid noisy cation-cation bonds inside ionic oxides/halides/silicates.
            return None
        metal = e1 if not nm1 else e2
        base_cut = 1.25 * (r1 + r2)
        if metal in ("Ca", "Ba", "Sr", "Pb", "Na", "K", "Bi", "Tl"):
            return max(base_cut, 2.95)
        return max(min(base_cut, 2.75), 2.20)

    display_bonds: list[tuple[int, int]] = []
    n_b = len(boundary_atoms)
    for i in range(n_b):
        ai = boundary_atoms[i]
        for j in range(i + 1, n_b):
            aj = boundary_atoms[j]
            cutoff = _bond_cutoff(ai["element"], aj["element"])
            if cutoff is None:
                continue
            dist = float(np.linalg.norm(ai["cart"] - aj["cart"]))
            if 0.65 <= dist <= cutoff:
                display_bonds.append((i, j))

    # Exact unique periodic bonds in unit cell [0, 1)^3 (each undirected bond counted once).
    unit_bond_count = 0
    seen_periodic_pairs: set[tuple[int, int, int, int, int]] = set()
    n_u = len(unit_atoms)
    u_fracs = [np.array(a["fract"], dtype=np.float64) for a in unit_atoms]
    for i in range(n_u):
        ei = unit_atoms[i]["element"]
        for j in range(i, n_u):
            ej = unit_atoms[j]["element"]
            cutoff = _bond_cutoff(ei, ej)
            if cutoff is None:
                continue
            for sx in (-1, 0, 1):
                for sy in (-1, 0, 1):
                    for sz in (-1, 0, 1):
                        if i == j and (sx, sy, sz) == (0, 0, 0):
                            continue
                        svec = np.array([sx, sy, sz], dtype=np.int32)
                        diff_c = mat @ (u_fracs[j] + svec - u_fracs[i])
                        dist = float(np.linalg.norm(diff_c))
                        if 0.65 <= dist <= cutoff:
                            # Canonicalize undirected periodic edge between (i, 0) and (j, s).
                            fwd = (i, j, sx, sy, sz)
                            rev = (j, i, -sx, -sy, -sz)
                            key = min(fwd, rev)
                            if key not in seen_periodic_pairs:
                                seen_periodic_pairs.add(key)
                                unit_bond_count += 1

    elem_counts = dict(sorted(Counter(a["element"] for a in unit_atoms).items()))
    return {
        "cell_matrix": mat,
        "volume_calc": round(vol_calc, 2),
        "unit_atoms": unit_atoms,
        "element_counts": elem_counts,
        "unit_atom_count": len(unit_atoms),
        "unit_bond_count": unit_bond_count,
        "boundary_atoms": boundary_atoms,
        "display_bonds": display_bonds,
    }


def _rotation_matrix(yaw_deg: float, pitch_deg: float) -> np.ndarray:
    cy, sy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    cp, sp = math.cos(math.radians(pitch_deg)), math.sin(math.radians(pitch_deg))
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]], dtype=np.float64)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cp, -sp], [0.0, sp, cp]], dtype=np.float64)
    return rx @ ry


def _draw_crystal_panel(
    expanded: dict[str, Any],
    rot: np.ndarray,
    panel_w: int,
    panel_h: int,
) -> tuple[Image.Image, float]:
    """Render one 2x SSAA Z-buffered panel of the unit cell & return (PIL, px_per_A_at_1x)."""
    w_hi, h_hi = panel_w * SSAA_SCALE, panel_h * SSAA_SCALE
    canvas = ZBufferCanvas(w_hi, h_hi, bg_rgb=(248, 250, 252))
    mat = expanded["cell_matrix"]

    corners_f = np.array(
        [[x, y, z] for x in (0.0, 1.0) for y in (0.0, 1.0) for z in (0.0, 1.0)],
        dtype=np.float64,
    )
    center_c = mat @ np.array([0.5, 0.5, 0.5])
    corners_r = (corners_f @ mat.T - center_c) @ rot.T

    span_xy = max(
        float(corners_r[:, 0].max() - corners_r[:, 0].min()),
        float(corners_r[:, 1].max() - corners_r[:, 1].min()),
        4.0,
    )
    margin = 0.14
    scale_hi = min(w_hi, h_hi) * (1.0 - 2 * margin) / span_xy
    cx_hi, cy_hi = w_hi * 0.5, h_hi * 0.5

    def _proj(pt: np.ndarray) -> tuple[float, float, float]:
        r = (pt - center_c) @ rot.T
        return (cx_hi + float(r[0]) * scale_hi, cy_hi - float(r[1]) * scale_hi, float(r[2]) * scale_hi)

    # Unit cell edges as slim shaded cylinders (with RGB on a/b/c origin vectors).
    corner_pts = [
        (cx_hi + float(c[0]) * scale_hi, cy_hi - float(c[1]) * scale_hi, float(c[2]) * scale_hi)
        for c in corners_r
    ]
    edge_pairs = [
        (0, 4, (220, 38, 38)),   # a axis
        (0, 2, (22, 163, 74)),   # b axis
        (0, 1, (37, 99, 235)),   # c axis
        (1, 3, (148, 163, 184)), (1, 5, (148, 163, 184)),
        (2, 3, (148, 163, 184)), (2, 6, (148, 163, 184)),
        (3, 7, (148, 163, 184)), (4, 5, (148, 163, 184)),
        (4, 6, (148, 163, 184)), (5, 7, (148, 163, 184)),
        (6, 7, (148, 163, 184)),
    ]
    wire_r = max(1.6, 0.025 * scale_hi)
    for i0, i1, col in edge_pairs:
        canvas.draw_cylinder(corner_pts[i0], corner_pts[i1], wire_r, col)

    b_atoms = expanded["boundary_atoms"]
    proj_atoms = [_proj(a["cart"]) for a in b_atoms]

    bond_r = max(2.8, 0.095 * scale_hi)
    for i, j in expanded["display_bonds"]:
        canvas.draw_cylinder(proj_atoms[i], proj_atoms[j], bond_r, (148, 163, 184))

    for atom, p in zip(b_atoms, proj_atoms):
        rgb, rad_a, _ = ELEMENT_STYLE.get(atom["element"], ((100, 116, 139), 0.50, 1.4))
        rad_px = max(5.0, rad_a * scale_hi)
        canvas.draw_sphere(p[0], p[1], p[2], rad_px, rgb)

    img = canvas.to_pil().resize((panel_w, panel_h), Image.Resampling.LANCZOS)
    return img, scale_hi / SSAA_SCALE


def render_crystal_figure(cod_id: str, parsed: dict[str, Any], expanded: dict[str, Any]) -> bytes:
    """Compose a 1600x900 dual-projection crystal figure with legend & scale bar."""
    out = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), (248, 250, 252))
    draw = ImageDraw.Draw(out)
    f_title = _load_font(26, bold=True)
    f_sub = _load_font(18, bold=False)
    f_cap = _load_font(18, bold=True)
    f_small = _load_font(15, bold=False)

    panel_w, panel_h = 740, 670
    # Slight [001] tilt avoids vertically eclipsing stacked atoms, paired with 3D oblique view.
    panel_a, px_per_a = _draw_crystal_panel(expanded, _rotation_matrix(8.0, 10.0), panel_w, panel_h)
    panel_b, px_per_b = _draw_crystal_panel(expanded, _rotation_matrix(36.0, 24.0), panel_w, panel_h)

    out.paste(panel_a, (40, 100))
    out.paste(panel_b, (820, 100))
    draw.rectangle((39, 99, 780, 770), outline=(203, 213, 225), width=2)
    draw.rectangle((819, 99, 1560, 770), outline=(203, 213, 225), width=2)

    formula = parsed["formula_sum"].strip("- ").strip() or "".join(expanded["element_counts"].keys())
    mineral = parsed["mineral_name"]
    header = f"COD {cod_id}  ·  {formula}" + (f" ({mineral})" if mineral else "")
    a, b, c, al, be, ga = parsed["cell"]
    sub = (
        f"a = {a:.3f} A,  b = {b:.3f} A,  c = {c:.3f} A   |   "
        f"alpha = {al:.1f} deg,  beta = {be:.1f} deg,  gamma = {ga:.1f} deg"
    )
    draw.text((40, 22), header, fill=(15, 23, 42), font=f_title)
    draw.text((40, 58), sub, fill=(71, 85, 105), font=f_sub)

    draw.text((54, 112), "View A: Near-[001] Projection", fill=(30, 41, 59), font=f_cap)
    draw.text((834, 112), "View B: Oblique 3D Unit Cell (R:a  G:b  B:c)", fill=(30, 41, 59), font=f_cap)

    # Scale bar (2 A) in bottom-right of Panel A.
    bar_px = max(24, int(round(2.0 * px_per_a)))
    bx1, by = 750, 742
    bx0 = bx1 - bar_px
    draw.line((bx0, by, bx1, by), fill=(15, 23, 42), width=4)
    draw.line((bx0, by - 5, bx0, by + 5), fill=(15, 23, 42), width=2)
    draw.line((bx1, by - 5, bx1, by + 5), fill=(15, 23, 42), width=2)
    draw.text((bx0, by - 24), "2.0 A", fill=(15, 23, 42), font=f_small)

    # Legend bar at bottom (strictly elements + color swatches, zero atom/bond counts).
    lx, ly = 42, 792
    draw.text((lx, ly + 4), "Elements:", fill=(30, 41, 59), font=f_cap)
    lx += 110
    for elem in sorted(expanded["element_counts"]):
        rgb = ELEMENT_STYLE.get(elem, ((100, 116, 139), 0.5, 1.4))[0]
        draw.ellipse((lx, ly + 4, lx + 20, ly + 24), fill=rgb, outline=(51, 65, 85), width=1)
        draw.text((lx + 28, ly + 3), elem, fill=(15, 23, 42), font=f_cap)
        lx += 95

    footer = "Data Render · COD (CC0) | [0,1]^3 Periodic Boundary Unit Cell Visualization"
    draw.text((40, 845), footer, fill=(100, 116, 139), font=f_small)
    return _encode_png(out)


# ---------------------------------------------------------------------------
# RCSB PDB parsing, <= 4.2 A contact detection, and 3D CA interface render
# ---------------------------------------------------------------------------


def parse_pdb_complex(pdb_text: str) -> dict[str, Any]:
    """Parse Model 1 protein chains, sequences, CA backbone, and <= 4.2 A contacts."""
    header_res: float | None = None
    title_parts: list[str] = []
    chains: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}

    for line in pdb_text.splitlines():
        if line.startswith("ENDMDL"):
            break
        if line.startswith("TITLE"):
            title_parts.append(line[10:].strip())
        elif line.startswith("REMARK   2 RESOLUTION."):
            m = re.search(r"([0-9]+(?:\.[0-9]+)?)\s+ANGSTROM", line)
            if m:
                header_res = float(m.group(1))
        elif line.startswith("ATOM  "):
            atom_name = line[12:16].strip()
            alt_loc = line[16]
            if alt_loc not in (" ", "A"):
                continue
            res_name = line[17:20].strip()
            chain_id = line[21].strip() or "A"
            res_seq = line[22:26].strip()
            i_code = line[26].strip()
            elem = line[76:78].strip().upper()
            if elem == "H" or (not elem and atom_name.startswith("H")):
                continue
            if res_name in ("HOH", "WAT", "DOD"):
                continue
            x = float(line[30:38])
            y = float(line[38:46])
            z = float(line[46:54])

            ch = chains.setdefault(chain_id, {})
            rkey = (res_seq, i_code)
            res = ch.get(rkey)
            if res is None:
                res = {
                    "chain": chain_id,
                    "res_seq": int(res_seq),
                    "i_code": i_code,
                    "res_id": f"{res_seq}{i_code}",
                    "res_name": res_name,
                    "aa1": AA3_TO_1.get(res_name, "X"),
                    "ca": None,
                    "heavy_coords": [],
                }
                ch[rkey] = res
            coord = np.array([x, y, z], dtype=np.float64)
            res["heavy_coords"].append(coord)
            if atom_name == "CA":
                res["ca"] = coord

    ordered_chains: dict[str, list[dict[str, Any]]] = {}
    for cid in sorted(chains):
        residues = sorted(chains[cid].values(), key=lambda r: (r["res_seq"], r["i_code"]))
        # Only keep polymer protein chains with CA atoms.
        ca_residues = [r for r in residues if r["ca"] is not None]
        if len(ca_residues) >= 15:
            for r in ca_residues:
                r["heavy_arr"] = np.vstack(r["heavy_coords"])
            ordered_chains[cid] = ca_residues

    if not (2 <= len(ordered_chains) <= 4):
        raise ValueError(f"Expected 2-4 protein chains with CA atoms, found {len(ordered_chains)}")

    chain_ids = sorted(ordered_chains)
    contact_pairs: list[dict[str, Any]] = []
    interface_residues: set[tuple[str, str]] = set()

    for idx_a in range(len(chain_ids)):
        ca_id = chain_ids[idx_a]
        for idx_b in range(idx_a + 1, len(chain_ids)):
            cb_id = chain_ids[idx_b]
            for ra in ordered_chains[ca_id]:
                ha = ra["heavy_arr"]
                for rb in ordered_chains[cb_id]:
                    hb = rb["heavy_arr"]
                    if float(np.linalg.norm(ra["ca"] - rb["ca"])) > 18.0:
                        continue
                    diff = ha[:, None, :] - hb[None, :, :]
                    min_d = float(np.sqrt(np.min(np.sum(diff * diff, axis=2))))
                    if min_d <= 4.2:
                        contact_pairs.append(
                            {
                                "chain_a": ca_id,
                                "res_a": f"{ra['res_name']}{ra['res_id']}",
                                "chain_b": cb_id,
                                "res_b": f"{rb['res_name']}{rb['res_id']}",
                                "min_dist": round(min_d, 3),
                            }
                        )
                        interface_residues.add((ca_id, ra["res_id"]))
                        interface_residues.add((cb_id, rb["res_id"]))

    if len(contact_pairs) < 4:
        raise ValueError(f"Too few <= 4.2 A inter-chain contacts ({len(contact_pairs)})")

    chain_sequences = {
        cid: "".join(r["aa1"] for r in res_list) for cid, res_list in ordered_chains.items()
    }
    return {
        "title": " ".join(title_parts),
        "resolution": header_res,
        "chains": ordered_chains,
        "chain_ids": chain_ids,
        "chain_sequences": chain_sequences,
        "chain_lengths": {cid: len(res_list) for cid, res_list in ordered_chains.items()},
        "total_residues": sum(len(v) for v in ordered_chains.values()),
        "contact_pairs": contact_pairs,
        "contact_pair_count": len(contact_pairs),
        "interface_residues": interface_residues,
        "interface_residue_count": len(interface_residues),
    }


def _draw_pdb_panel(
    parsed: dict[str, Any],
    pca_basis: np.ndarray,
    center: np.ndarray,
    yaw_deg: float,
    panel_w: int,
    panel_h: int,
) -> tuple[Image.Image, float]:
    """Render one 2x SSAA Z-buffered panel of protein chains & contact interface."""
    w_hi, h_hi = panel_w * SSAA_SCALE, panel_h * SSAA_SCALE
    canvas = ZBufferCanvas(w_hi, h_hi, bg_rgb=(248, 250, 252))
    rot = _rotation_matrix(yaw_deg, 10.0) @ pca_basis

    all_cas = np.vstack(
        [r["ca"] for cid in parsed["chain_ids"] for r in parsed["chains"][cid]]
    )
    pts_rot = (all_cas - center) @ rot.T
    span_xy = max(
        float(pts_rot[:, 0].max() - pts_rot[:, 0].min()),
        float(pts_rot[:, 1].max() - pts_rot[:, 1].min()),
        12.0,
    )
    scale_hi = min(w_hi, h_hi) * 0.78 / span_xy
    cx_hi, cy_hi = w_hi * 0.5, h_hi * 0.5

    def _proj(ca: np.ndarray) -> tuple[float, float, float]:
        r = (ca - center) @ rot.T
        return (cx_hi + float(r[0]) * scale_hi, cy_hi - float(r[1]) * scale_hi, float(r[2]) * scale_hi)

    backbone_r = max(2.2, 0.36 * scale_hi)
    bead_r = max(3.6, 0.62 * scale_hi)
    iface_r = max(4.6, 0.82 * scale_hi)
    iface_set = parsed["interface_residues"]

    proj_map: dict[tuple[str, str], tuple[float, float, float]] = {}
    for c_idx, cid in enumerate(parsed["chain_ids"]):
        rgb = CHAIN_COLORS[c_idx % len(CHAIN_COLORS)]
        res_list = parsed["chains"][cid]
        coords_p = [_proj(r["ca"]) for r in res_list]
        for r, p in zip(res_list, coords_p):
            proj_map[(cid, f"{r['res_name']}{r['res_id']}")] = p
        for i in range(len(res_list) - 1):
            if float(np.linalg.norm(res_list[i + 1]["ca"] - res_list[i]["ca"])) <= 4.6:
                canvas.draw_cylinder(coords_p[i], coords_p[i + 1], backbone_r, rgb)
        for r, p in zip(res_list, coords_p):
            if (cid, r["res_id"]) in iface_set:
                canvas.draw_sphere(p[0], p[1], p[2], iface_r, rgb, rim_rgb=INTERFACE_HIGHLIGHT_RGB)
            else:
                canvas.draw_sphere(p[0], p[1], p[2], bead_r, rgb)

    # Thin gold bridge cylinders linking contacting CA positions across chains.
    bridge_r = max(1.3, 0.16 * scale_hi)
    for pair in parsed["contact_pairs"][:60]:
        pa = proj_map.get((pair["chain_a"], pair["res_a"]))
        pb = proj_map.get((pair["chain_b"], pair["res_b"]))
        if pa is not None and pb is not None:
            canvas.draw_cylinder(pa, pb, bridge_r, INTERFACE_HIGHLIGHT_RGB)

    img = canvas.to_pil().resize((panel_w, panel_h), Image.Resampling.LANCZOS)
    return img, scale_hi / SSAA_SCALE


def render_pdb_figure(pdb_id: str, parsed: dict[str, Any]) -> bytes:
    """Compose a 1600x900 dual-orthogonal-view PDB protein complex PNG."""
    all_cas = np.vstack(
        [r["ca"] for cid in parsed["chain_ids"] for r in parsed["chains"][cid]]
    )
    center = np.mean(all_cas, axis=0)
    _, _, vt = np.linalg.svd(all_cas - center, full_matrices=False)
    # Enforce right-handed PCA basis so widest axis lies horizontally in View A.
    if np.linalg.det(vt) < 0:
        vt[2] *= -1.0

    out = Image.new("RGB", (RENDER_WIDTH, RENDER_HEIGHT), (248, 250, 252))
    draw = ImageDraw.Draw(out)
    f_title = _load_font(26, bold=True)
    f_sub = _load_font(18, bold=False)
    f_cap = _load_font(18, bold=True)
    f_small = _load_font(15, bold=False)

    panel_w, panel_h = 740, 670
    panel_a, px_per_a = _draw_pdb_panel(parsed, vt, center, 0.0, panel_w, panel_h)
    panel_b, _ = _draw_pdb_panel(parsed, vt, center, 90.0, panel_w, panel_h)

    out.paste(panel_a, (40, 100))
    out.paste(panel_b, (820, 100))
    draw.rectangle((39, 99, 780, 770), outline=(203, 213, 225), width=2)
    draw.rectangle((819, 99, 1560, 770), outline=(203, 213, 225), width=2)

    res_str = f"{parsed['resolution']:.2f} A" if parsed["resolution"] else "X-ray"
    short_title = parsed["title"][:68] + ("..." if len(parsed["title"]) > 68 else "")
    draw.text((40, 22), f"RCSB PDB {pdb_id}  ·  {res_str} Resolution", fill=(15, 23, 42), font=f_title)
    draw.text((40, 58), short_title, fill=(71, 85, 105), font=f_sub)

    draw.text((54, 112), "View A: Principal Interface (0 deg)", fill=(30, 41, 59), font=f_cap)
    draw.text((834, 112), "View B: Orthogonal (+90 deg Y-Rotation)", fill=(30, 41, 59), font=f_cap)

    # 10 A scale bar in bottom-right of Panel A.
    bar_px = max(24, int(round(10.0 * px_per_a)))
    bx1, by = 750, 742
    bx0 = bx1 - bar_px
    draw.line((bx0, by, bx1, by), fill=(15, 23, 42), width=4)
    draw.line((bx0, by - 5, bx0, by + 5), fill=(15, 23, 42), width=2)
    draw.line((bx1, by - 5, bx1, by + 5), fill=(15, 23, 42), width=2)
    draw.text((bx0, by - 24), "10 A", fill=(15, 23, 42), font=f_small)

    # Bottom chain legend (zero contact counts or residue counts printed).
    lx, ly = 42, 792
    draw.text((lx, ly + 4), "Chains:", fill=(30, 41, 59), font=f_cap)
    lx += 95
    for c_idx, cid in enumerate(parsed["chain_ids"]):
        rgb = CHAIN_COLORS[c_idx % len(CHAIN_COLORS)]
        draw.ellipse((lx, ly + 4, lx + 20, ly + 24), fill=rgb, outline=(51, 65, 85), width=1)
        draw.text((lx + 28, ly + 3), f"Chain {cid}", fill=(15, 23, 42), font=f_cap)
        lx += 125

    draw.ellipse((lx, ly + 4, lx + 20, ly + 24), fill=INTERFACE_HIGHLIGHT_RGB, outline=(51, 65, 85), width=1)
    draw.text((lx + 28, ly + 3), "Interface contact residues (heavy atom <= 4.2 A)", fill=(15, 23, 42), font=f_cap)

    footer = "Data Render · RCSB PDB (CC0) | Model 1 CA Trace & Inter-Chain Heavy-Atom Interface"
    draw.text((40, 845), footer, fill=(100, 116, 139), font=f_small)
    return _encode_png(out)


# ---------------------------------------------------------------------------
# Collection runners for COD Crystals & RCSB PDB
# ---------------------------------------------------------------------------


def discover_rcsb_ids(session: requests.Session, limit: int = 60) -> list[str]:
    """Query RCSB Search API v2 for compact 2-4 chain high-resolution X-ray proteins."""
    query = {
        "query": {
            "type": "group",
            "logical_operator": "and",
            "nodes": [
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "exptl.method",
                        "operator": "exact_match",
                        "value": "X-RAY DIFFRACTION",
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.resolution_combined",
                        "operator": "less_or_equal",
                        "value": 1.8,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.polymer_entity_count_protein",
                        "operator": "greater_or_equal",
                        "value": 2,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.polymer_entity_count_nucleic_acid",
                        "operator": "equals",
                        "value": 0,
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.deposited_polymer_entity_instance_count",
                        "operator": "range",
                        "value": {"from": 2, "to": 4},
                    },
                },
                {
                    "type": "terminal",
                    "service": "text",
                    "parameters": {
                        "attribute": "rcsb_entry_info.deposited_polymer_monomer_count",
                        "operator": "range",
                        "value": {"from": 70, "to": 220},
                    },
                },
            ],
        },
        "return_type": "entry",
        "request_options": {"paginate": {"start": 0, "rows": limit}},
    }
    resp = session.post(RCSB_SEARCH_URL, json=query, timeout=25)
    if resp.status_code == 204 or not resp.text.strip():
        return []
    resp.raise_for_status()
    data = resp.json()
    return [str(item["identifier"]) for item in data.get("result_set") or [] if item.get("identifier")]


def write_cod_attribution(meta_dir: Path, saved_count: int) -> None:
    text = (
        "COD (Crystallography Open Database) 真实晶体单胞结构可视化数据集\n"
        f"样本数量: {saved_count}\n"
        "来源接口: https://www.crystallography.net/cod/{cod_id}.cif\n"
        "许可协议: CC0 1.0 Public Domain Dedication（COD 数据集公有领域声明）\n"
        "渲染与标注说明: 从原始 CIF 展开完整空间群对称操作与 [0,1)^3 单胞原子/周期边界键，"
        "使用 NumPy Z-buffer + Pillow 2x 超采样绘制 [001] 倾角与 3D 斜视图；"
        "图像严格标注 Data Render · COD (CC0) 且不泄露原子数或键数答案。\n"
    )
    atomic_write_bytes(meta_dir / "来源与许可.txt", text.encode("utf-8"))


def write_rcsb_attribution(meta_dir: Path, saved_count: int) -> None:
    text = (
        "RCSB PDB 高分辨率多链蛋白复合物界面结构可视化数据集\n"
        f"样本数量: {saved_count}\n"
        "来源接口: https://search.rcsb.org/rcsbsearch/v2/query 与 "
        "https://files.rcsb.org/download/{pdb_id}.pdb\n"
        "许可协议: CC0 1.0 Public Domain Dedication（PDB Archive 公有领域声明）\n"
        "渲染与标注说明: 基于 Model 1 解析各蛋白链残基序列并精确计算链间重原子 <= 4.2 A 接触对，"
        "使用 NumPy Z-buffer + Pillow 2x 超采样绘制主界面 0° 与正交 +90° 双视角图；"
        "图像严格标注 Data Render · RCSB PDB (CC0) 且不泄露接触对数答案。\n"
    )
    atomic_write_bytes(meta_dir / "来源与许可.txt", text.encode("utf-8"))


def collect_cod(
    img_root: Path = DEFAULT_IMG_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    target_count: int = 20,
    cod_ids: list[str] | None = None,
    session: requests.Session | None = None,
    force_tags: bool = False,
) -> tuple[int, int, int]:
    """Download CIFs, expand crystal symmetry, render PNGs, and register img_claims."""
    out_dir = img_root / "科学图像" / "COD_Crystals"
    png_dir = out_dir / "PNG"
    meta_dir = out_dir / "元数据"
    cif_dir = meta_dir / "cif"
    png_dir.mkdir(parents=True, exist_ok=True)
    cif_dir.mkdir(parents=True, exist_ok=True)

    http = session or requests.Session()
    candidate_ids = list(CURATED_COD_IDS if cod_ids is None else cod_ids)
    if cod_ids is None and len(candidate_ids) < target_count + 8:
        seen = set(candidate_ids)
        for q in FALLBACK_COD_QUERIES:
            try:
                rows = http.get(f"{COD_BASE_URL}/result", params=q, timeout=20).json()
                for r in rows[:6]:
                    cid = str(r.get("file") or "")
                    if cid and cid not in seen:
                        seen.add(cid)
                        candidate_ids.append(cid)
            except Exception:
                continue

    manifest_records: list[dict[str, Any]] = []
    registry_records: list[dict[str, Any]] = []
    seen_formula_sg: set[tuple[str, str]] = set()
    for cid in candidate_ids:
        if len(manifest_records) >= target_count:
            break
        try:
            resp = http.get(f"{COD_BASE_URL}/{cid}.cif", timeout=25)
            resp.raise_for_status()
            cif_text = resp.text
            parsed = parse_cif_structure(cif_text)
            formula_key = (
                parsed["formula_sum"].strip("- ").strip(),
                parsed["space_group_hm"].strip(),
            )
            if formula_key[0] and formula_key in seen_formula_sg:
                print(f"[SKIP] COD {cid}: duplicate formula+SG {formula_key}")
                continue
            expanded = expand_unit_cell(parsed)
            png_bytes = render_crystal_figure(cid, parsed, expanded)
        except Exception as exc:
            print(f"[SKIP] COD {cid}: {exc}")
            continue

        if formula_key[0]:
            seen_formula_sg.add(formula_key)

        atomic_write_bytes(cif_dir / f"cod-{cid}.cif", cif_text.encode("utf-8"))
        out_png = png_dir / f"cod-{cid}.png"
        atomic_write_bytes(out_png, png_bytes)

        rel = f"科学图像/COD_Crystals/PNG/cod-{cid}.png"
        unit_n = expanded["unit_atom_count"]
        bonds_n = expanded["unit_bond_count"]
        diff = "hard" if unit_n >= 16 or len(expanded["element_counts"]) >= 3 else "medium"
        annotations = {
            "question_types": "domain_decoding,counting,spatial_transform,localization_measurement",
            "difficulty": diff,
            "difficulty_tags": "view_transform,cross_region_alignment,multi_hop_visual"
            + (",high_density" if unit_n >= 24 else ""),
            "tag_notes": (
                f"COD {cid} ({parsed['formula_sum']}), SG={parsed['space_group_hm']}, "
                f"unit_atoms={unit_n}, unit_bonds={bonds_n}; CC0 Data Render"
            ),
            "authored_status": "",
            "authored_ref": "",
        }
        rec = {
            "cod_id": cid,
            "cif_url": f"{COD_BASE_URL}/{cid}.cif",
            "license": "CC0",
            "formula_sum": parsed["formula_sum"],
            "mineral_name": parsed["mineral_name"],
            "space_group_hm": parsed["space_group_hm"],
            "space_group_number": parsed["space_group_number"],
            "z_formula": parsed["z_formula"],
            "cell": list(parsed["cell"]),
            "volume_calc": expanded["volume_calc"],
            "unit_atom_count": unit_n,
            "element_counts": expanded["element_counts"],
            "unit_bond_count": bonds_n,
            "file_size_bytes": len(png_bytes),
            "img_relpath": rel,
            "annotations": annotations,
        }
        manifest_records.append(rec)
        registry_records.append(rec)
        print(
            f"[OK] COD cod-{cid} ({parsed['formula_sum']}): atoms={unit_n}, "
            f"bonds={bonds_n}, {len(png_bytes) // 1024}KB diff={diff}"
        )
        time.sleep(0.05)

    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in manifest_records)
    if lines:
        lines += "\n"
    atomic_write_bytes(meta_dir / "crystals_manifest.jsonl", lines.encode("utf-8"))
    write_cod_attribution(meta_dir, len(manifest_records))
    ins, upd = register_local_claims(db_path, registry_records, force_tags=force_tags)
    return len(manifest_records), ins, upd


def collect_rcsb(
    img_root: Path = DEFAULT_IMG_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    target_count: int = 20,
    pdb_ids: list[str] | None = None,
    session: requests.Session | None = None,
    force_tags: bool = False,
) -> tuple[int, int, int]:
    """Download PDB complexes, compute <= 4.2 A contacts, render PNGs, and register img_claims."""
    out_dir = img_root / "科学图像" / "RCSB_PDB"
    png_dir = out_dir / "PNG"
    meta_dir = out_dir / "元数据"
    pdb_dir = meta_dir / "pdb"
    png_dir.mkdir(parents=True, exist_ok=True)
    pdb_dir.mkdir(parents=True, exist_ok=True)

    http = session or requests.Session()
    candidate_ids = discover_rcsb_ids(http, limit=max(45, target_count * 3)) if pdb_ids is None else list(pdb_ids)

    manifest_records: list[dict[str, Any]] = []
    registry_records: list[dict[str, Any]] = []
    for pid in candidate_ids:
        if len(manifest_records) >= target_count:
            break
        try:
            resp = http.get(f"{RCSB_PDB_BASE_URL}/{pid}.pdb", timeout=25)
            resp.raise_for_status()
            pdb_text = resp.text
            parsed = parse_pdb_complex(pdb_text)
            png_bytes = render_pdb_figure(pid, parsed)
        except Exception as exc:
            print(f"[SKIP] PDB {pid}: {exc}")
            continue

        atomic_write_bytes(pdb_dir / f"rcsb-{pid}.pdb", pdb_text.encode("utf-8"))
        out_png = png_dir / f"rcsb-{pid}.png"
        atomic_write_bytes(out_png, png_bytes)

        rel = f"科学图像/RCSB_PDB/PNG/rcsb-{pid}.png"
        c_cnt = parsed["contact_pair_count"]
        diff = "hard" if c_cnt >= 12 or len(parsed["chain_ids"]) >= 3 else "medium"
        annotations = {
            "question_types": "domain_decoding,spatial_transform,localization_measurement,counting",
            "difficulty": diff,
            "difficulty_tags": "view_transform,cross_region_alignment,occlusion_overlap,multi_hop_visual",
            "tag_notes": (
                f"RCSB {pid} chains={','.join(parsed['chain_ids'])}, res={parsed['resolution']}A, "
                f"contacts_le_4.2A={c_cnt}; CC0 Data Render"
            ),
            "authored_status": "",
            "authored_ref": "",
        }
        rec = {
            "pdb_id": pid,
            "pdb_url": f"{RCSB_PDB_BASE_URL}/{pid}.pdb",
            "license": "CC0",
            "title": parsed["title"],
            "resolution": parsed["resolution"],
            "chain_ids": parsed["chain_ids"],
            "chain_lengths": parsed["chain_lengths"],
            "chain_sequences": parsed["chain_sequences"],
            "total_residues": parsed["total_residues"],
            "contact_cutoff_angstrom": 4.2,
            "contact_pair_count": c_cnt,
            "interface_residue_count": parsed["interface_residue_count"],
            "contact_pairs": parsed["contact_pairs"],
            "file_size_bytes": len(png_bytes),
            "img_relpath": rel,
            "annotations": annotations,
        }
        manifest_records.append(rec)
        registry_records.append(rec)
        print(
            f"[OK] PDB rcsb-{pid} (chains={''.join(parsed['chain_ids'])}, res={parsed['resolution']}A): "
            f"contacts={c_cnt}, {len(png_bytes) // 1024}KB diff={diff}"
        )
        time.sleep(0.05)

    lines = "\n".join(json.dumps(r, ensure_ascii=False) for r in manifest_records)
    if lines:
        lines += "\n"
    atomic_write_bytes(meta_dir / "complexes_manifest.jsonl", lines.encode("utf-8"))
    write_rcsb_attribution(meta_dir, len(manifest_records))
    ins, upd = register_local_claims(db_path, registry_records, force_tags=force_tags)
    return len(manifest_records), ins, upd


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect and render COD crystals and RCSB PDB complexes.")
    p.add_argument("--img-root", type=Path, default=DEFAULT_IMG_ROOT)
    p.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    p.add_argument("--cod-count", type=int, default=20)
    p.add_argument("--rcsb-count", type=int, default=20)
    p.add_argument("--force-tags", action="store_true")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    c_n, c_ins, c_upd = collect_cod(
        img_root=args.img_root,
        db_path=args.db_path,
        target_count=args.cod_count,
        force_tags=args.force_tags,
    )
    r_n, r_ins, r_upd = collect_rcsb(
        img_root=args.img_root,
        db_path=args.db_path,
        target_count=args.rcsb_count,
        force_tags=args.force_tags,
    )
    print(f"COD Summary: saved={c_n} db_inserted={c_ins} db_updated={c_upd}")
    print(f"RCSB Summary: saved={r_n} db_inserted={r_ins} db_updated={r_upd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
