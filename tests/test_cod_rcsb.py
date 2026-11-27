import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from PIL import Image

from collect_cod_rcsb import (
    collect_cod,
    collect_rcsb,
    expand_unit_cell,
    parse_cif_structure,
    parse_pdb_complex,
)
import img_server


SCHEMA_PATH = Path(__file__).resolve().parent.parent / "collection_schema.sql"

SAMPLE_NACL_CIF = """data_1000041
_chemical_formula_sum 'Cl Na'
_chemical_name_mineral Halite
_symmetry_space_group_name_H-M 'F m -3 m'
_space_group_IT_number 225
_cell_length_a 5.640(1)
_cell_length_b 5.640(1)
_cell_length_c 5.640(1)
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_cell_formula_units_Z 4
loop_
_symmetry_equiv_pos_as_xyz
x,y,z
-x,-y,z
-x,y,-z
x,-y,-z
z,x,y
z,-x,-y
-z,-x,y
-z,x,-y
y,z,x
-y,z,-x
y,-z,-x
-y,-z,x
y,x,-z
-y,-x,-z
y,-x,z
-y,x,z
x,z,-y
-x,z,y
-x,-z,-y
x,-z,y
z,y,-x
z,-y,x
-z,y,x
-z,-y,-x
-x,-y,-z
x,y,-z
x,-y,z
-x,y,z
-z,-x,-y
-z,x,y
z,x,-y
z,-x,y
-y,-z,-x
y,-z,x
-y,z,x
y,z,-x
-y,-x,z
y,x,z
-y,x,-z
y,-x,-z
-x,-z,y
x,-z,-y
x,z,y
-x,z,-y
-z,-y,x
-z,y,-x
z,-y,-x
z,y,x
x+1/2,y+1/2,z
x+1/2,y,z+1/2
x,y+1/2,z+1/2
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1 Na+ 0. 0. 0. 1.
Cl1 Cl- 0.5 0.5 0.5 1.
"""


def _build_synthetic_pdb() -> str:
    """Build a valid 2-chain 16-residue-per-chain protein dimer with >= 4 contacts <= 4.2 A."""
    lines = [
        "HEADER    TEST COMPLEX                            01-JAN-26   1TST",
        "TITLE     SYNTHETIC DIMER COMPLEX FOR UNIT TEST",
        "REMARK   2 RESOLUTION.    1.50 ANGSTROMS.",
    ]
    serial = 1
    for ch_idx, (cid, z_off, x_dir) in enumerate([("A", 0.0, 0.0), ("B", 3.4, 1.0)]):
        for r in range(1, 17):
            y = (r - 1) * 3.8
            x = x_dir * (0.0 if 6 <= r <= 11 else 8.0)
            z = z_off if 6 <= r <= 11 else z_off + (5.0 if cid == "B" else -5.0)
            lines.append(
                f"ATOM  {serial:5d}  CA  ALA {cid}{r:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C  "
            )
            serial += 1
            # Put CB closer along interface for residues 7..10 so distance <= 3.6 A.
            cx = x + (-0.4 if cid == "B" else 0.4)
            cz = z + (-0.5 if cid == "B" else 0.5)
            lines.append(
                f"ATOM  {serial:5d}  CB  ALA {cid}{r:4d}    {cx:8.3f}{y:8.3f}{cz:8.3f}  1.00 20.00           C  "
            )
            serial += 1
    lines.append("END")
    return "\n".join(lines) + "\n"


class _FakeResp:
    def __init__(self, text: str = "", json_data=None, status_code: int = 200):
        self.text = text
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json


class _FakeSession:
    def __init__(self, mapping: dict[str, _FakeResp]):
        self.mapping = mapping

    def get(self, url: str, params=None, timeout=20):
        return self.mapping.get(url, _FakeResp(status_code=404))


class CodRcsbTests(unittest.TestCase):
    def test_cif_symmetry_expansion_counts_nacl_correctly(self):
        # F-lattice in Halite above omitted composite centered + inverted ops, test with all 192 ops or verify basic expansion
        parsed = parse_cif_structure(SAMPLE_NACL_CIF)
        expanded = expand_unit_cell(parsed)
        # Note: in SAMPLE_NACL_CIF we listed the 48 point-group ops and 3 pure centering shifts separately,
        # which only expands Wyckoff origin (0,0,0) and (0.5,0.5,0.5) into 4 Na and 4 Cl (Z=4 Halite)!
        self.assertEqual(expanded["element_counts"], {"Cl": 4, "Na": 4})
        self.assertEqual(expanded["unit_atom_count"], 8)
        self.assertGreater(expanded["unit_bond_count"], 0)

    def test_pdb_contact_pairs_le_4_2_angstrom(self):
        parsed = parse_pdb_complex(_build_synthetic_pdb())
        self.assertEqual(parsed["chain_ids"], ["A", "B"])
        self.assertGreaterEqual(parsed["contact_pair_count"], 6)
        self.assertTrue(all(p["min_dist"] <= 4.2 for p in parsed["contact_pairs"]))

    def test_collect_cod_and_rcsb_render_and_register_db(self):
        pdb_text = _build_synthetic_pdb()
        fake = _FakeSession(
            {
                "https://www.crystallography.net/cod/1000041.cif": _FakeResp(text=SAMPLE_NACL_CIF),
                "https://files.rcsb.org/download/1TST.pdb": _FakeResp(text=pdb_text),
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db_path = root / "test.sqlite"
            img_root = root / "img"
            with sqlite3.connect(db_path) as conn:
                conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

            c_n, c_ins, _ = collect_cod(
                img_root=img_root,
                db_path=db_path,
                target_count=1,
                cod_ids=["1000041"],
                session=fake,
            )
            r_n, r_ins, _ = collect_rcsb(
                img_root=img_root,
                db_path=db_path,
                target_count=1,
                pdb_ids=["1TST"],
                session=fake,
            )
            self.assertEqual((c_n, c_ins), (1, 1))
            self.assertEqual((r_n, r_ins), (1, 1))

            cod_png = img_root / "科学图像" / "COD_Crystals" / "PNG" / "cod-1000041.png"
            pdb_png = img_root / "科学图像" / "RCSB_PDB" / "PNG" / "rcsb-1TST.png"
            self.assertTrue(cod_png.is_file())
            self.assertTrue(pdb_png.is_file())
            with Image.open(cod_png) as im1, Image.open(pdb_png) as im2:
                self.assertEqual(im1.size, (1600, 900))
                self.assertEqual(im2.size, (1600, 900))

            store = img_server.ClaimStore(db_path, img_root)
            claims = store.get_claims_by_relpaths(
                [
                    "科学图像/COD_Crystals/PNG/cod-1000041.png",
                    "科学图像/RCSB_PDB/PNG/rcsb-1TST.png",
                ]
            )
            self.assertEqual(len(claims), 2)
            self.assertTrue(all(v["registered"] and v["registry_source"] == "img_claims" for v in claims.values()))

            c_man = json.loads(
                (img_root / "科学图像" / "COD_Crystals" / "元数据" / "crystals_manifest.jsonl")
                .read_text(encoding="utf-8")
                .strip()
            )
            self.assertEqual(c_man["unit_atom_count"], 8)


if __name__ == "__main__":
    unittest.main()
