"""Five small fixes, each pinned by the unit that used to be wrong.

  * 06e passed no results directory to the R scripts, so they drew from the
    hard-coded default whatever config.json said.
  * 01d flagged SAT on the tile-field-corrected saturation, which undercounts
    clipping by about 2x; the raw column is the honest one.
  * 04g copied only the corrected saturation into artifact_summary*.csv.
  * 04k hard-coded atlas/plates while config names plates_final, and the two
    sets reuse plate ids for different images.
  * 04b carried its own hard-coded copy of the extraction-set path. It still
    reads that set on purpose (it is measured evidence, not moved to the
    configured set - see 04a's scope note), but now says so through
    ls_atlas.EXTRACTED instead of repeating the literal.

Every stage reads config.json at import, so a temporary config is written and
named through LS_CONFIG before any script is loaded, as in
tests/test_config_resolver.py. No main() is called.

Run:  python tests/test_small_fixes.py
"""

import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SCRIPTS = os.path.join(REPO, "scripts")

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(60) + " " + repr(got)
          + ("" if ok else "   want " + repr(want)))


def load(script, name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS, script))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


with tempfile.TemporaryDirectory() as tmp:
    with open(os.path.join(REPO, "config.example.json"), encoding="utf-8") as fh:
        cfg = json.load(fh)
    out_root = os.path.join(tmp, "out")
    os.makedirs(out_root)
    cfg["source_dir"] = tmp
    cfg["out_root"] = out_root
    cfg["atlas_pdf"] = os.path.join(tmp, "atlas.pdf")
    cfg["atlas_plate_set"] = {"dir": "plates_final"}
    cfg_path = os.path.join(tmp, "config.json")
    with open(cfg_path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)
    os.environ["LS_CONFIG"] = cfg_path
    sys.path.insert(0, SCRIPTS)

    # ------------------------------------------------ 1. R gets the results dir
    print("\n06e: the R scripts are told where results/ is\n")
    G6E = load("06e_refresh_loop.py", "t_g6e")
    cmd = G6E.r_command("Rscript.exe", "analysis/plot_by_sample.R", "X:/res")
    chk("argv[0] is Rscript", cmd[0], "Rscript.exe")
    chk("argv[1] is the script", cmd[1], "analysis/plot_by_sample.R")
    chk("results dir is the last argv element", cmd[-1], "X:/res")
    chk("exactly three elements", len(cmd), 3)

    # ------------------------------------------------ 2. SAT flag uses raw column
    print("\n01d: the SAT flag reads saturated_fraction_raw when present\n")
    G1D = load("01d_contactsheets.py", "t_g1d")
    both = {"tissue_fraction": 1.0, "focus_score": 1e9,
            "saturated_fraction": 0.0, "saturated_fraction_raw": 0.9}
    old = {"tissue_fraction": 1.0, "focus_score": 1e9,
           "saturated_fraction": 0.9}
    chk("raw drives the flag when both present", G1D.flag(both, 0.0), "SAT")
    chk("raw value returned by saturation()", G1D.saturation(both), 0.9)
    chk("old column alone still flags", G1D.flag(old, 0.0), "SAT")
    chk("old value returned when raw absent", G1D.saturation(old), 0.9)
    chk("empty raw string falls back",
        G1D.saturation({"saturated_fraction": "0.3", "saturated_fraction_raw": ""}), 0.3)
    chk("raw string is parsed",
        G1D.saturation({"saturated_fraction": "0.3", "saturated_fraction_raw": "0.7"}), 0.7)
    chk("nothing parsable -> 0.0",
        G1D.saturation({"saturated_fraction": "", "saturated_fraction_raw": ""}), 0.0)

    # ------------------------------------------------ 3. summary carries both
    print("\n04g: artifact_summary rows carry both saturation columns\n")
    G4G = load("04g_artifact_mask.py", "t_g4g")
    row = G4G.summary_row("uid1", {"animal": "LS1", "section_order": "3", "excluded": 0},
                          [], 2.0, {"uid1": 0.1}, {"uid1": 0.2})
    chk("saturated_fraction kept", row["saturated_fraction"], 0.1)
    chk("saturated_fraction_raw added", row["saturated_fraction_raw"], 0.2)
    chk("missing uid -> empty strings",
        G4G.summary_row("nope", {"animal": "LS1", "section_order": "3"}, [], 2.0, {}, {})
        ["saturated_fraction_raw"], "")
    chk("measurable_mm2 unchanged", row["measurable_mm2"], 2.0)

    # ------------------------------------------------ 4. plate set from config
    print("\n04k: plate set comes from config, not a hard-coded path\n")
    G4K = load("04k_level_curator.py", "t_g4k")
    chk("PLATE_SET read from config", G4K.PLATE_SET, "plates_final")
    chk("PLATES_CSV under that set", G4K.PLATES_CSV,
        os.path.join(out_root, "atlas", "plates_final", "plates.csv"))
    chk("page export has a plate_set column", '"plate_set"' in G4K.PAGE, True)
    chk("page carries the set for the export", "__PLATESET__" in G4K.PAGE, True)

    # ------------------------------------------------ 5. plate set resolved in one place
    print("\n04b: the extraction set is kept, and named rather than hard-coded\n")
    B = load("04b_atlas_match.py", "t_b")
    chk("04b keeps the set it was measured against",
        os.path.basename(B.PLATE_DIR), "plates")
    with open(os.path.join(REPO, "scripts", "04b_atlas_match.py"),
              encoding="utf-8") as fh:
        b_src = fh.read()
    chk("...and says so through AT.EXTRACTED rather than a literal",
        "AT.EXTRACTED" in b_src, True)
    chk("...not by repeating the literal \"plates\" in the PLATE_DIR line",
        'os.path.join(OUT_ROOT, "atlas", "plates")' in b_src, False)

print()
if fails:
    print(f"{fails} FAILED")
    sys.exit(1)
print("all ok")
