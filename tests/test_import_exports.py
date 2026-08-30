"""Round-tripping curator exports back into curator state.

`import_exports.rebuild` is the path that recovered the operator's work after
the browser copy of it turned out to be unreachable. Anything it silently drops
is work that looks recovered and is gone, so what it does NOT carry matters as
much as what it does.

Background discs are the specific hazard: they have no plate counterpart, so
they never appear in `roi_landmarks.csv`, and a rebuild that reads only the
landmarks file restores a session that looks complete with every background
measurement missing from it.

The CSV text below is the real thing - headers and rows captured verbatim from
the curator's own exportCsv() running in a browser - rather than a guess at the
format.

Run:  python tests/test_import_exports.py
"""

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "app"))

import import_exports as IE                                    # noqa: E402

PLATES = """\
scene_uid,animal,marker,subset,section_order,plate_set,plate_id,plate_index,\
plate_has_seeds,n_landmarks,n_background,transform,status,favorite,view_rotation_deg,excluded
LS22_s01a_sc00,LS22,AF568,roi_worklist,1,plates_final,plate_009,8,1,3,2,affine,registered,1,0.0,0
"""

LANDMARKS = """\
scene_uid,animal,marker,section_order,plate_set,plate_id,pair,\
sec_x,sec_y,sec_r,plate_x,plate_y,residual_px,seed_n,seed_region
LS22_s01a_sc00,LS22,AF568,1,plates_final,plate_009,1,73.65,90.00,8.00,72.27,405.98,0.00,1,Dl
LS22_s01a_sc00,LS22,AF568,1,plates_final,plate_009,2,146.12,109.00,8.00,111.84,496.11,0.00,2,Dl
LS22_s01a_sc00,LS22,AF568,1,plates_final,plate_009,3,109.88,173.60,8.00,176.88,576.16,0.00,3,Dl
"""

REGIONS = """\
scene_uid,animal,marker,plate_set,plate_id,roi_kind,region,region_ambiguous,ambiguity_group,\
region_uncertain_in_atlas,sec_x,sec_y,sec_r,seed_n,n_landmarks,transform,mean_residual_px
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,background,__background__,0,,0,207.71,43.40,8.00,,3,,
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,background,__background__,0,,0,222.21,165.01,8.00,,3,,
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,roi,Dl,0,,0,73.65,90.00,8.00,1,3,affine,0.00
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,roi,Dl,0,,0,146.12,109.00,8.00,2,3,affine,0.00
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,roi,Dl,0,,0,109.88,173.60,8.00,3,3,affine,0.00
"""

# What an export written before background discs existed looks like: no
# roi_kind column at all.
REGIONS_OLD = """\
scene_uid,animal,marker,plate_set,plate_id,region,region_ambiguous,ambiguity_group,\
region_uncertain_in_atlas,sec_x,sec_y,sec_r,seed_n,n_landmarks,transform,mean_residual_px
LS22_s01a_sc00,LS22,AF568,plates_final,plate_009,Dl,0,,0,73.65,90.00,8.00,1,3,affine,0.00
"""

fails = 0


def chk(label, got, want):
    global fails
    ok = str(got) == str(want)
    if not ok:
        fails += 1
    print(("ok   " if ok else "FAIL ") + label.ljust(54) + " " + str(got)
          + ("" if ok else "   want " + str(want)))


def write(d, name, text):
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    return p


def main():
    with tempfile.TemporaryDirectory() as d:
        pl = write(d, "roi_plates.csv", PLATES)
        lm = write(d, "roi_landmarks.csv", LANDMARKS)
        rg = write(d, "roi_regions.csv", REGIONS)

        S, n_pairs, n_bg = IE.rebuild(pl, lm, regions_csv=rg)
        e = S["LS22_s01a_sc00"]
        pairs = e["pairs"]
        bg = [p for p in pairs if len(p) > 6 and p[6] == "bg"]
        roi = [p for p in pairs if not (len(p) > 6 and p[6] == "bg")]

        print("\nrebuilding a section with 3 landmarks and 2 background discs:\n")
        chk("the section came back", len(S), 1)
        chk("3 landmarks", n_pairs, 3)
        chk("2 background discs", n_bg, 2)
        chk("...and both are in its pairs", len(bg), 2)
        chk("landmarks are not duplicated by the regions file", len(roi), 3)
        chk("the plate decision survived", e["assigned"], True)
        chk("the favourite survived", e["fav"], True)

        # k=3: the export divides by it, the rebuild multiplies by it back.
        chk("a background disc is at its exported position x3",
            [round(bg[0][0], 2), round(bg[0][1], 2)], [623.13, 130.2])
        chk("...carries its radius", round(bg[0][5], 2), 24.0)
        chk("...names no plate point", [bg[0][2], bg[0][3]], [0.0, 0.0])
        chk("...and no seed", bg[0][4], 0)

        print("\nthe curator's own rule for what enters the fit:\n")
        # transform() filters on p[6], so this is the property that keeps a
        # background disc out of the spline.
        chk("every background pair is 7 long", all(len(p) == 7 for p in bg), True)
        chk("no landmark is", all(len(p) < 7 for p in roi), True)

        print("\nan export written before background discs existed:\n")
        rg_old = write(d, "roi_regions_old.csv", REGIONS_OLD)
        S2, n2, nbg2 = IE.rebuild(pl, lm, regions_csv=rg_old)
        chk("its landmarks still load", n2, 3)
        chk("and it contributes no background discs", nbg2, 0)
        chk("...leaving pairs untouched",
            len(S2["LS22_s01a_sc00"]["pairs"]), 3)

        print("\nno regions file at all:\n")
        S3, n3, nbg3 = IE.rebuild(pl, lm, regions_csv=os.path.join(d, "nope.csv"))
        chk("the rebuild still works", n3, 3)
        chk("and says it found none", nbg3, 0)

    print("\n" + (f"{fails} FAILED" if fails else "ALL PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
