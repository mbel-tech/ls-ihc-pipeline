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
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts"))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import import_exports as IE                                    # noqa: E402
from _fixture import temp_study                                # noqa: E402

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


def replace_guard(d, plates):
    """main() must refuse to drop curation the export does not mention.

    THIS SUITE ONLY EVER CALLED rebuild(), which is why a docstring promising
    this refusal shipped without the code behind it. The hazard is real: one
    curation store holds both markers - scene uids never collide - so a
    PCNA-only export replacing it wholesale drops every pERK placement, and the
    live store already holds 180 pERK sections against 85 PCNA ones.
    """
    import json

    out_root = os.path.join(d, "out")
    os.makedirs(os.path.join(out_root, "curation"), exist_ok=True)
    store = IE.ST.CurationStore(out_root)
    # One section the export mentions, one it does not - the other marker's.
    store.write(IE.ROI_KEY, json.dumps({
        "LS22_s01a_sc00": {"plate": 1, "pairs": [], "assigned": True,
                           "noroi": False, "fav": False, "rot": 0, "excl": False},
        "LS22_s01b_sc00": {"plate": 2, "pairs": [], "assigned": True,
                           "noroi": False, "fav": False, "rot": 0, "excl": False},
    }))

    # main() reads out_root from config.json, so the store is redirected here
    # rather than pointed at the real one - this test must never touch
    # D:/LS-analysis/curation.
    argv, real_store = sys.argv[:], IE.ST.CurationStore

    def run(*flags):
        sys.argv = ["import_exports", plates, *flags]
        IE.ST.CurationStore = lambda _root: real_store(out_root)
        try:
            return IE.main()
        finally:
            sys.argv = argv
            IE.ST.CurationStore = real_store

    print("\nrefusing a replace that would drop another marker's work:\n")
    rc = run()
    chk("plain import REFUSES", rc, 1)
    after = json.loads(store.read(IE.ROI_KEY))
    chk("...and wrote nothing", sorted(after), "['LS22_s01a_sc00', 'LS22_s01b_sc00']")

    chk("--merge is allowed", run("--merge"), 0)
    kept = json.loads(store.read(IE.ROI_KEY))
    chk("...and keeps the unmentioned section", "LS22_s01b_sc00" in kept, True)


# Two sections of the same marker, one shown as a 768 px composite and one as
# the 256 px greyscale - the situation a flat k cannot describe.
PLATES_2 = """\
scene_uid,animal,marker,subset,section_order,plate_set,plate_id,plate_index,\
plate_has_seeds,n_landmarks,n_background,transform,status,favorite,view_rotation_deg,excluded
LS22_s01a_sc00,LS22,AF568,roi_worklist,1,plates_final,plate_009,8,1,1,0,affine,registered,1,0.0,0
LS22_s02a_sc00,LS22,AF568,roi_worklist,2,plates_final,plate_009,8,1,1,0,affine,registered,1,0.0,0
"""

LANDMARKS_2 = """\
scene_uid,animal,marker,section_order,plate_set,plate_id,pair,\
sec_x,sec_y,sec_r,plate_x,plate_y,residual_px,seed_n,seed_region
LS22_s01a_sc00,LS22,AF568,1,plates_final,plate_009,1,100.00,50.00,8.00,72.27,405.98,0.00,1,Dl
LS22_s02a_sc00,LS22,AF568,2,plates_final,plate_009,1,100.00,50.00,8.00,72.27,405.98,0.00,1,Dl
"""


def frames(d):
    """A reformatted/ tree with a composite for one section and only the
    greyscale for the other, exactly as 04o leaves it."""
    from PIL import Image
    rd = os.path.join(d, "reformatted")
    for sub, uid, w in (("sections_AF568_rgb", "LS22_s01a_sc00", 768),
                        ("sections_AF568", "LS22_s01a_sc00", 256),
                        ("sections_AF568", "LS22_s02a_sc00", 256)):
        os.makedirs(os.path.join(rd, sub), exist_ok=True)
        Image.new("L", (w, w)).save(os.path.join(rd, sub, uid + ".png"))
    return rd


def per_section_frame(d):
    """The rebuild reads each section in the frame it was CLICKED in.

    `rebuild` used to take one k for the whole import and default it to 3, so a
    section the page had shown as the 256 greyscale came back with every
    landmark three times too far out. 04l stamps `frame` per record and 04q
    already derives it from disk; this is the same rule on the import path.
    """
    print("\n\nper-section frames:\n")
    rd = frames(d)
    # Named, because the directory a marker's sections went into is a fact
    # about the STUDY, and this suite must not read the operator's. The shape
    # here is the live one, so the answers below are the live answers.
    with temp_study(acquisition={"layout": "paired",
                                 "markers": ["AF568", "AF488"]}):
        fo = IE.frame_from_disk(rd)
        chk("a composite section is a 768 frame", fo("LS22_s01a_sc00", "AF568"), 768.0)
        chk("a greyscale-only section is 256", fo("LS22_s02a_sc00", "AF568"), 256.0)
        chk("an unknown section falls back to the export's own grid",
            fo("LS22_s09z_sc00", "AF568"), 256.0)
        chk("--no-rgb ignores the composite",
            IE.frame_from_disk(rd, rgb=False)("LS22_s01a_sc00", "AF568"), 256.0)

    pl = write(d, "plates2.csv", PLATES_2)
    lm = write(d, "landmarks2.csv", LANDMARKS_2)
    S, n, _ = IE.rebuild(pl, lm, frame_of=fo)
    a = S["LS22_s01a_sc00"]
    b = S["LS22_s02a_sc00"]
    chk("both sections rebuilt", n, 2)
    chk("the composite section is scaled by 3",
        [round(v, 2) for v in a["pairs"][0][:2]], [300.0, 150.0])
    chk("...and its record says which frame that was", a["frame"], 768.0)
    chk("the greyscale section is not scaled",
        [round(v, 2) for v in b["pairs"][0][:2]], [100.0, 50.0])
    chk("...and its record says so too", b["frame"], 256.0)
    chk("its radius follows the same frame", round(b["pairs"][0][5], 2), 8.0)
    chk("...and the composite's does not", round(a["pairs"][0][5], 2), 24.0)

    # A caller that knows every section shared one frame can still say so.
    S2, _, _ = IE.rebuild(pl, lm, k=3.0)
    chk("an explicit flat k still applies to every section",
        [round(S2[u]["pairs"][0][0], 2) for u in sorted(S2)], [300.0, 300.0])
    chk("...and is stamped as a frame", S2["LS22_s02a_sc00"]["frame"], 768.0)


def other_study_frames(d):
    """The same frame question, under a study whose markers are not LS's.

    `marker_dir` was `"sections_AF568" if marker == "AF568" else "sections"` -
    the LS study's answer written out as though it were everybody's. For any
    other study every marker resolved to `sections`, the probe for the 768-px
    composite missed the directory 04o had actually written, the frame fell
    back to 256, and every landmark and background disc came back at a THIRD
    of the coordinate the operator clicked. Nothing raised: the store rebuilds,
    the page opens, and the discs are somewhere plausible.

    Mk2 is the geometry source (the SECOND declared owns the unsuffixed
    names), so this pins both halves of the rule at once - a fix that gave
    every marker a suffix would fail on Mk2.
    """
    print("\n\nframes under a study that is not LS:\n")
    from PIL import Image
    rd = os.path.join(d, "other_study", "reformatted")
    with temp_study(acquisition={"layout": "paired",
                                 "markers": ["Mk1", "Mk2"]}):
        import ls_paths as LP
        names = LP.Names(os.path.dirname(rd), ["Mk1", "Mk2"], "paired")
        for marker, uid in (("Mk1", "X_mk1"), ("Mk2", "X_mk2")):
            sub = os.path.basename(names.path("sections", marker)) + "_rgb"
            os.makedirs(os.path.join(rd, sub), exist_ok=True)
            Image.new("L", (768, 768)).save(os.path.join(rd, sub, uid + ".png"))

        chk("the directory is the one 04a wrote, per marker",
            (IE.marker_dir("Mk1"), IE.marker_dir("Mk2")),
            ("sections_Mk1", "sections"))
        fo = IE.frame_from_disk(rd)
        chk("the suffixed marker's composite is found: 768, not 256",
            fo("X_mk1", "Mk1"), 768.0)
        chk("...and the geometry source's, in the unsuffixed directory",
            fo("X_mk2", "Mk2"), 768.0)


def main():
    with tempfile.TemporaryDirectory() as d:
        pl = write(d, "roi_plates.csv", PLATES)
        lm = write(d, "roi_landmarks.csv", LANDMARKS)
        rg = write(d, "roi_regions.csv", REGIONS)

        # k=3.0 explicitly: this fixture is a 768 px composite section, and
        # the default is no longer a guess that every section was one.
        S, n_pairs, n_bg = IE.rebuild(pl, lm, k=3.0, regions_csv=rg)
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
        S2, n2, nbg2 = IE.rebuild(pl, lm, k=3.0, regions_csv=rg_old)
        chk("its landmarks still load", n2, 3)
        chk("and it contributes no background discs", nbg2, 0)
        chk("...leaving pairs untouched",
            len(S2["LS22_s01a_sc00"]["pairs"]), 3)

        print("\nno regions file at all:\n")
        S3, n3, nbg3 = IE.rebuild(pl, lm, k=3.0, regions_csv=os.path.join(d, "nope.csv"))
        chk("the rebuild still works", n3, 3)
        chk("and says it found none", nbg3, 0)

        replace_guard(d, pl)
        per_section_frame(d)
        other_study_frames(d)

    print("\n" + (f"{fails} FAILED" if fails else "ALL PASS"))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
