"""Rebuild curator state from exported CSVs.

The exports are the durable form of a curation session - `roi_plates.csv` holds
one row per decided section and `roi_landmarks.csv` one row per placed pair. If
the browser storage behind them is gone, unreachable or on an origin nothing else
can see, these files are still a complete record of what was decided, and the
curator's working state can be rebuilt from them exactly.

This is the other half of the migration story. `collect_state` gets the state out
of a browser that will talk to us; this gets it back out of the exports when the
browser will not, which - given localStorage is partitioned per origin and per
browser profile, and a `file://` page may have an opaque origin no other page can
read - is the more reliable of the two.

Run:  python -m app.import_exports C:\\path\\to\\downloads
      python -m app.import_exports <dir> --merge
      python -m app.import_exports <dir> --replace   # drop what it omits
      python -m app.import_exports "C:/.../roi_plates(1).csv" --merge
      python -m app.import_exports <dir> --dry-run

A path to a plates CSV works as well as a directory, because a second export
lands as `roi_plates(1).csv` and that is exactly when it is needed.

Without --merge the store is REPLACED, and one store holds both markers - so a
PCNA-only export would drop every pERK placement. That is refused rather than
warned about: pass --merge to keep them, or --replace if the loss is intended.

--merge keeps sections the export does not mention. A session spent on one animal
exports only that animal, so a plain import would silently drop every decision
made about the other eleven; the export wins only where the two overlap, being
the more recent statement about those sections.
"""

import csv
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import state as ST                                          # noqa: E402

ROI_KEY = "ls_roi_curator_v1"


def _blank():
    return {"plate": 0, "pairs": [], "assigned": False,
            "noroi": False, "fav": False, "rot": 0.0, "excl": False}


def rebuild(plates_csv, landmarks_csv=None, k=3.0, regions_csv=None):
    """Turn the exports back into the curator's `S` map.

    `k` is the ratio between the pixels the operator clicked in and the canonical
    256 grid the export is written in - 3 for the 768 px colour composites. The
    export divides by it on the way out, so the rebuild multiplies by it on the
    way back in. Get this wrong and every landmark lands at the wrong scale,
    which is why it is a named argument rather than a constant buried below.

    `regions_csv` is read for its BACKGROUND rows and nothing else. Background
    discs are not landmarks - they have no plate counterpart, so they are absent
    from `roi_landmarks.csv` entirely - and this function is the path that
    recovered the operator's work once already. Rebuilding without them would
    restore a session that looked complete and had quietly lost every background
    measurement in it. The region rows for real ROIs are deliberately NOT read
    back: those are derived from the landmarks, and reading both would duplicate
    every pair.
    """
    S = {}
    with open(plates_csv, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            uid = (r.get("scene_uid") or "").strip()
            if not uid:
                continue
            e = _blank()
            idx = (r.get("plate_index") or "").strip()
            if idx:
                # A recorded plate index means the plate was a decision: the
                # export only writes it when the operator chose one.
                e["plate"] = int(float(idx))
                e["assigned"] = True
            e["fav"] = r.get("favorite") == "1"
            e["excl"] = r.get("excluded") == "1"
            e["noroi"] = (r.get("status") or "") == "no_roi"
            try:
                e["rot"] = float(r.get("view_rotation_deg") or 0) or 0.0
            except ValueError:
                e["rot"] = 0.0
            S[uid] = e

    n_pairs = 0
    if landmarks_csv and os.path.exists(landmarks_csv):
        with open(landmarks_csv, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                uid = (r.get("scene_uid") or "").strip()
                if not uid:
                    continue
                e = S.setdefault(uid, _blank())
                try:
                    sx = float(r["sec_x"]) * k
                    sy = float(r["sec_y"]) * k
                    px = float(r["plate_x"])
                    py = float(r["plate_y"])
                except (KeyError, ValueError):
                    continue
                # sec_r and seed_n only exist in exports written after they were
                # added; older files simply have no radius and no seed to carry.
                seed = 0
                try:
                    seed = int(float(r.get("seed_n") or 0))
                except ValueError:
                    seed = 0
                rad = 0.0
                try:
                    rad = float(r.get("sec_r") or 0) * k
                except ValueError:
                    rad = 0.0
                pair = [sx, sy, px, py, seed, rad] if (seed or rad) else [sx, sy, px, py]
                e["pairs"].append(pair)
                n_pairs += 1

    n_bg = 0
    if regions_csv and os.path.exists(regions_csv):
        with open(regions_csv, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                # roi_kind is absent from exports written before background
                # discs existed; those files carry region rows only, and this
                # loop should find nothing in them.
                if (r.get("roi_kind") or "") != "background":
                    continue
                uid = (r.get("scene_uid") or "").strip()
                if not uid:
                    continue
                try:
                    sx = float(r["sec_x"]) * k
                    sy = float(r["sec_y"]) * k
                    rad = float(r.get("sec_r") or 0) * k
                except (KeyError, ValueError):
                    continue
                # Plate coords 0,0 and seed 0, exactly as the curator stores
                # them - the "bg" marker is what identifies it, and the fit
                # filters on that rather than on the coordinates.
                S.setdefault(uid, _blank())["pairs"].append(
                    [sx, sy, 0.0, 0.0, 0, rad, "bg"])
                n_bg += 1
    return S, n_pairs, n_bg


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    merge = "--merge" in sys.argv
    # Only needed to override the refusal below - replacing is still the
    # default, it just stops when it would drop another marker's work.
    replace = "--replace" in sys.argv
    if not args:
        print(__doc__)
        return 2
    src = args[0]

    if os.path.isdir(src):
        plates = os.path.join(src, "roi_plates.csv")
        marks = os.path.join(src, "roi_landmarks.csv")
        regions = os.path.join(src, "roi_regions.csv")
    else:
        # Given a plates file directly, look for the siblings that came with it -
        # same folder, same "(1)" suffix the browser added.
        plates = src
        marks = src.replace("roi_plates", "roi_landmarks")
        regions = src.replace("roi_plates", "roi_regions")
    if not os.path.exists(plates):
        print(f"no plates CSV at {plates}")
        return 1

    cfg = os.path.join(os.path.dirname(HERE), "config.json")
    with open(cfg, encoding="utf-8") as fh:
        out_root = json.load(fh)["out_root"]

    S, n_pairs, n_bg = rebuild(plates, marks, regions_csv=regions)
    fresh = len(S)

    if merge:
        prior_raw = ST.CurationStore(out_root).read(ROI_KEY)
        prior = json.loads(prior_raw) if prior_raw else {}
        kept = {u: v for u, v in prior.items() if u not in S}
        S = {**kept, **S}
        print(f"merging: {fresh} from the export, {len(kept)} kept of "
              f"{len(prior)} already on file")
    dec = sum(1 for v in S.values()
              if v["assigned"] or v["fav"] or v["excl"] or v["noroi"] or v["rot"])
    print(f"rebuilt {len(S)} sections from {os.path.basename(plates)}")
    print(f"  {dec} carry a decision")
    print(f"  {sum(1 for v in S.values() if v['excl'])} excluded")
    print(f"  {sum(1 for v in S.values() if v['fav'])} favourite")
    print(f"  {sum(1 for v in S.values() if v['assigned'])} with a plate")
    print(f"  {sum(1 for v in S.values() if v['rot'])} rotated")
    print(f"  {n_pairs} landmark pairs")
    # Reported separately, and reported even when zero: a silent 0 here is how
    # you find out too late that the regions CSV was not beside the plates one.
    print(f"  {n_bg} background discs"
          + ("" if os.path.exists(regions) else
             f"   (no {os.path.basename(regions)} found beside the plates file)"))

    store = ST.CurationStore(out_root)
    existing = None if merge else store.read(ROI_KEY)
    if existing:
        try:
            prior_all = json.loads(existing)
        except ValueError:
            prior_all = {}
        had = len(prior_all) if prior_all else "?"

        # REPLACING NOW DESTROYS THE OTHER MARKER'S CURATION.
        #
        # One store holds both markers - scene uids never collide, which is what
        # lets the curator page carry pERK and PCNA at once - so a PCNA-only
        # export replacing it wholesale drops every pERK placement, and the
        # reverse. Harmless while only one marker had ever been curated; the
        # store here already holds 180 pERK sections and 85 PCNA ones.
        #
        # Sections the export does not mention are the signal. A normal
        # re-import of the same marker mentions its own sections, so whatever is
        # left over belongs to another marker - or the wrong export was picked.
        # Either way it is not a default, and it is not reversible.
        orphans = sorted(u for u in (prior_all or {}) if u not in S)
        if orphans and not replace:
            print(f"\n  REFUSING: {ROI_KEY} holds {had} sections and this "
                  f"export mentions {len(S)}, so replacing it would DROP "
                  f"{len(orphans)} - e.g. {', '.join(orphans[:3])}.")
            print(f"  One store holds both markers. Curating one cannot disturb "
                  f"the other, but REPLACING the store can.")
            print(f"  --merge keeps them; --replace drops them anyway.")
            return 1
        print(f"\n  NOTE: {ROI_KEY} already holds {had} sections and will be replaced.")

    if dry:
        print("\n--dry-run: nothing written")
        return 0

    store.write(ROI_KEY, json.dumps(S))
    print(f"\nwrote {store.path(ROI_KEY)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
