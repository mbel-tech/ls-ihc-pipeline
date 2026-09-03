"""Every keyed output is written through ls_io, never in place.

A source scan, because these scripts need the imaging data to run. What has to
hold is that the in-place `open(path, "w")` at each output site is gone and
the atomic helper is called for that path.

Run:  python tests/test_atomic_adoption.py
"""

import os

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "scripts")

fails = 0


def chk(label, got, want):
    global fails
    ok = got == want
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + f" {got!r}"
          + ("" if ok else f"   want {want!r}"))


# script -> (fragment that must be GONE, fragment that must be PRESENT)
SITES = {
    "04a_reformat.py": ('with open(out_csv, "w"', "IO.atomic_write_csv(out_csv, rows, keys)"),
    "04j_censor_clipped.py": ('with open(out_csv, "w"', "IO.atomic_write_csv(out_csv, rows, ANALYSIS_KEYS)"),
    "04g_artifact_mask.py": ('with open(out, "w"', "IO.atomic_write_csv(out, rows, SUMMARY_KEYS)"),
    "04f_exclusion_candidates.py": ('with open(out, "w"', "IO.atomic_write_csv(out, "),
    "04h_symmetry_axis.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, out, SYM_KEYS)"),
    "04i_propagate_to_perk.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, OVERRIDE_KEYS)"),
    "04m_sections_dataset.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)"),
    "04p_section_provenance.py": ('with open(OUT_CSV, "w"', "IO.atomic_write_csv(OUT_CSV, rows, COLUMNS)"),
    "05a_roi_geometry.py": ('with open(path, "w", newline="", encoding="utf-8") as fh:\n            w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))',
                            "IO.atomic_write_csv(path, rows, list(rows[0].keys()))"),
    "06a_roi_dataset.py": ('with open(path, "w", newline="", encoding="utf-8") as fh:\n            w = csv.DictWriter(fh, fieldnames=list(data[0].keys()))',
                           "IO.atomic_write_csv(path, data, list(data[0].keys()))"),
    "06c_excel_dataset.py": ("    wb.save(path)", "with IO.atomic_save(path) as tmp:\n        wb.save(tmp)"),
    "01k_saturation_raw.py": (".save(mask_path)", "with IO.atomic_save(mask_path) as tmp:"),
}

for name, (gone, present) in SITES.items():
    with open(os.path.join(SCRIPTS, name), encoding="utf-8") as fh:
        src = fh.read()
    chk(f"{name}: in-place write gone", gone in src, False)
    chk(f"{name}: atomic write present", present in src, True)
    chk(f"{name}: imports ls_io", '"ls_io.py"' in src, True)

print("\n" + ("ALL PASS" if not fails else f"{fails} FAILED"))
raise SystemExit(1 if fails else 0)
