"""Verify the numeric claims in pipeline-methods.md against the data they came from.

A methods document is only as good as the last time someone checked it, and this
pipeline is still running - the measured counts grow between runs. This asserts
every load-bearing number in the document back against its source and prints
PASS/FAIL per claim, so a stale figure is found by running a script rather than by
a reader noticing.

Claims that come from a one-off measurement recorded in LOGS.md rather than from a
table that still exists (the reader benchmark, the PAP-pen intensities, the
Bio-Formats corruption count) are listed at the end as UNCHECKED, because
pretending to verify them would be worse than saying they are not verified here.

Run:  python docs/check_methods_claims.py
"""

import csv
import json
import os
import re
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(HERE, "pipeline-methods.md")

with open(os.path.join(ROOT, "config.json"), encoding="utf8") as fh:
    CONFIG = json.load(fh)
OUT = CONFIG["out_root"]

results = []


def rows(*parts):
    path = os.path.join(OUT, *parts)
    if not os.path.exists(path):
        return None
    with open(path, newline="", encoding="utf8") as fh:
        return list(csv.DictReader(fh))


def check(claim, actual, expected):
    ok = actual == expected
    results.append((ok, claim, actual, expected))


def approx(claim, actual, expected, tol):
    ok = abs(actual - expected) <= tol
    results.append((ok, claim, round(actual, 4), expected))


def main():
    # ---- acquisition and scope, from the manifest -------------------------
    files = rows("manifest", "manifest_files.csv")
    scenes = rows("manifest", "manifest_scenes.csv")
    if files and scenes:
        uniq = [r for r in files if r["is_redundant_copy"] == "0"]
        check("222 CZI files", len(uniq), 222)
        check("2,572 scanned sections", len(scenes), 2572)
        check("12 animals", len({r["animal"] for r in scenes}), 12)
        check("1,191 pERK sections",
              sum(1 for r in scenes if r["marker_channel"] == "AF568"), 1191)
        check("1,381 PCNA sections",
              sum(1 for r in scenes if r["marker_channel"] == "AF488"), 1381)
        optics = {(r["objective_mag"], r["objective_na"], r["px_um"], r["camera"])
                  for r in uniq}
        check("one optical configuration: 10x / 0.45 NA / 0.65 um / ORCA-Flash4.0",
              optics, {("10", "0.45", "0.65", "Orca Flash 4.0")})
        exp = {(r["marker_channel"], r["marker_exposure_ms"], r["dapi_exposure_ms"])
               for r in uniq}
        check("exposures 5 ms DAPI / 1000 ms AF568 / 300 ms AF488", exp,
              {("AF568", "1000.0", "5.0"), ("AF488", "300.0", "5.0")})

    # ---- config-stated acquisition geometry -------------------------------
    check("14 um section thickness", CONFIG["section_thickness_um"], 14.0)
    check("0.65 um/px native", CONFIG["pixel_size_um"], 0.65)
    check("5.20 um/px overview", CONFIG["overview_target_um_per_px"], 5.2)

    # ---- atlas -------------------------------------------------------------
    plates = rows("atlas", "plates", "plates.csv")
    final = rows("atlas", "plates_final", "plates.csv")
    seeds = rows("atlas", "plates_final", "seeds.csv")
    if plates and final and seeds:
        check("47 raw atlas plates", len(plates), 47)
        check("64 plates in the working set", len(final), 64)
        check("362 region seed points", len(seeds), 362)
        check("seeds on 31 plates", len({r["plate_id"] for r in seeds}), 31)
        check("13 named atlas regions", len({r["region"] for r in seeds}), 13)
        check("no seed left unnamed", sum(r["region"] == "UNMAPPED" for r in seeds), 0)
        check("66 seeds recovered from flattened insets",
              sum(int(r.get("from_raster") or 0) for r in seeds), 66)

    # ---- exclusion, artifact and censoring, from the provenance table ------
    prov = rows("reformatted", "section_provenance.csv")
    if prov:
        status = {}
        for r in prov:
            status[r["status"]] = status.get(r["status"], 0) + 1
        check("1,066 sections excluded", status.get("excluded"), 1066)
        check("1,506 sections reformatted",
              sum(1 for r in prov if r["reformatted"] == "1"), 1506)
        perk = [r for r in prov if r["marker"] == "AF568"]
        measurable = sum(1 for r in perk if r["status"] in ("reformatted", "measured"))
        # These two move when 04j/06f re-run on an improved clipping mask, so the
        # document dates them. The partition itself is the invariant.
        check("450 measurable pERK sections (as of 2026-09-02)", measurable, 450)
        check("268 pERK sections censored out (as of 2026-09-02)",
              sum(1 for r in perk if r["status"] == "censored_out"), 268)
        check("473 pERK sections excluded",
              sum(1 for r in perk if r["status"] == "excluded"), 473)
        check("the pERK partition sums to 1,191", len(perk), 1191)
        pcna = [r for r in prov if r["marker"] == "AF488"]
        check("788 measurable PCNA sections",
              sum(1 for r in pcna if r["status"] == "reformatted"), 788)

        n_obj = [int(r["n_artifact_objects"]) for r in prov if r["n_artifact_objects"] != ""]
        affected = [v for v in n_obj if v > 0]
        check("2,226 sections carry an in-tissue artifact", len(affected), 2226)
        approx("86.5 % of sections affected", 100 * len(affected) / len(n_obj), 86.5, 0.1)
        check("median 3 artifact objects on an affected section",
              int(st.median(affected)), 3)
        pct = sorted(float(r["artifact_pct_of_tissue"]) for r in prov
                     if r["artifact_pct_of_tissue"])
        approx("median 0.79 % of tissue masked", st.median(pct), 0.79, 0.01)
        approx("p95 2.2 % of tissue masked", pct[int(0.95 * len(pct))], 2.15, 0.05)
        approx("worst 7.4 % of tissue masked", pct[-1], 7.38, 0.05)

    # ---- the measured set --------------------------------------------------
    meas = rows("results", "roi_measurements.csv")
    spec = rows("results", "detector_specificity.csv")
    if meas:
        anat = [r for r in meas if r["roi_kind"] == "roi"]
        bg = [r for r in meas if r["roi_kind"] == "background"]
        check("2,069 regions of interest", len(meas), 2069)
        check("1,483 anatomical ROIs", len(anat), 1483)
        check("586 background discs", len(bg), 586)
        check("130 sections measured", len({r["scene_uid"] for r in meas}), 130)
        check("11 animals measured", len({r["animal"] for r in meas}), 11)
        check("Dl is the commonest region, 575 ROIs",
              sum(1 for r in anat if r["region"] == "Dl"), 575)
        check("Dm second, 489 ROIs",
              sum(1 for r in anat if r["region"] == "Dm"), 489)
        check("no censored nuclei in the measured set",
              sum(int(r["n_censored"]) for r in meas if r["n_censored"]), 0)

        total = sum(int(r["n_nuclei"]) for r in meas)
        in_roi = sum(int(r["n_nuclei"]) for r in anat)
        results.append((total >= 892025, "at least 892,025 nuclei measured", total, ">= 892025"))
        results.append((in_roi >= 619300, "at least 619,300 nuclei in anatomical ROIs",
                        in_roi, ">= 619300"))

        scored = [r for r in anat if r["n_positive"]]
        pos = sum(int(r["n_positive"]) for r in scored)
        tot = sum(int(r["n_nuclei"]) for r in scored)
        approx("pooled ROI positivity 13.2 %", 100 * pos / tot, 13.2, 0.3)

        h = [float(r["mean_nucleus_diam_um"]) for r in meas if r["mean_nucleus_diam_um"]]
        a = [float(r["abercrombie_factor"]) for r in meas if r["abercrombie_factor"]]
        approx("Abercrombie h from 7.8 um", min(h), 7.81, 0.05)
        approx("Abercrombie h to 9.4 um", max(h), 9.44, 0.05)
        approx("correction factor from 0.597", min(a), 0.5973, 0.002)
        approx("correction factor to 0.642", max(a), 0.6419, 0.002)
        # T/(T+h) must reproduce the factors from the stated 14 um thickness
        T = CONFIG["section_thickness_um"]
        worst = max(abs(f - T / (T + d)) for f, d in
                    ((float(r["abercrombie_factor"]), float(r["mean_nucleus_diam_um"]))
                     for r in meas if r["abercrombie_factor"] and r["mean_nucleus_diam_um"]))
        results.append((worst < 0.02, "factors consistent with T = 14 um",
                        round(worst, 4), "< 0.02 max deviation"))

    if spec:
        fp = [float(r["false_positive_rate"]) for r in spec if r["false_positive_rate"]]
        approx("median false-positive rate 2.10 %", 100 * st.median(fp), 2.10, 0.15)

    # ---- StarDist model parameters, read from the model itself -------------
    cfg = os.path.expanduser(
        "~/.keras/models/StarDist2D/2D_versatile_fluo/2D_versatile_fluo_extracted/config.json")
    thr = cfg.replace("config.json", "thresholds.json")
    if os.path.exists(cfg):
        mc = json.load(open(cfg, encoding="utf8"))
        check("StarDist 32 rays", mc["n_rays"], 32)
        check("StarDist U-Net depth 3", mc["unet_n_depth"], 3)
        check("StarDist 2x2 prediction grid", mc["grid"], [2, 2])
        check("StarDist single input channel", mc["n_channel_in"], 1)
        check("StarDist 256x256 training patches", mc["train_patch_size"], [256, 256])
    if os.path.exists(thr):
        mt = json.load(open(thr, encoding="utf8"))
        approx("StarDist probability threshold 0.479", mt["prob"], 0.479, 0.001)
        check("StarDist NMS threshold 0.3", mt["nms"], 0.3)

    # ---- report ------------------------------------------------------------
    width = max(len(c) for _, c, _, _ in results)
    failed = 0
    for ok, claim, actual, expected in results:
        if not ok:
            failed += 1
        print("%-4s %-*s  got %s  expected %s"
              % ("PASS" if ok else "FAIL", width, claim, actual, expected))

    print("\n%d claims checked, %d failed" % (len(results), failed))

    print("\nUNCHECKED - one-off measurements recorded in LOGS.md, not in a live table:")
    for line in ("the three-reader benchmark timings",
                 "238 sections corrupted by the Bio-Formats Memoizer",
                 "the PAP-pen intensities, 0.51 outside the tissue against 74.0 inside",
                 "the automatic level-assignment correlations",
                 "the 35 % of AF568 sections above 2 % clipped",
                 "the 1.86x background gap produced by clipping",
                 "the 0.04-0.15 px reformat inverse residual",
                 "control 2.2 % against exercise 2.0 % false-positive rate"):
        print("  - " + line)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
