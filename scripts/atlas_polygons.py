"""Region polygons for an atlas whose plates carry contours instead of seed dots.

The salmon atlas marks each region with vector dots and 04l builds the shaded,
numbered areas from them (`region_hulls`). The Wullimann 1996 plates draw the
regions as closed outlines, so the outline IS the area: 04x extracts one polygon
per enclosed region into `polygons.csv`, and 04l shows those instead of hulls.

This module is the contract between the two, so the extractor, the review page
and the curator cannot disagree about a file format or a numbering rule.

polygons.csv, one row per polygon, vertices as fractions of the plate image:

    plate_id, roi_number, region, status, label_conf, vertices

`vertices` is "x y;x y;..." and `status` is auto (named by the program),
reviewed (a person confirmed or set it) or unassigned (no name yet; the
curator skips these, because an ROI with no region is not a measurement).

Imported by path, like every other cross-script import here:

    _spec = importlib.util.spec_from_file_location(
        "_atlas_polygons", os.path.join(os.path.dirname(os.path.abspath(__file__)), "atlas_polygons.py"))
    AP = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(AP)
"""

import colorsys
import csv
import hashlib
import os

KEYS = ["plate_id", "roi_number", "region", "status", "label_conf", "vertices"]
STATUSES = ("auto", "reviewed", "unassigned")

# The same two widths 04l uses to run a plate's seeds down vertical strips
# (COL_BAND, COL_SPAN), so a polygon plate is numbered in the same reading order
# as a salmon plate: down each column, columns left to right.
COL_BAND, COL_SPAN = 0.08, 0.12


def encode_vertices(v):
    return ";".join("%.5f %.5f" % (x, y) for x, y in v)


def decode_vertices(text):
    out = []
    for pair in (text or "").split(";"):
        pair = pair.strip()
        if pair:
            x, y = pair.split()
            out.append([float(x), float(y)])
    return out


def read_polygons(path):
    """{plate_id: [polygon dicts]}, or {} when the file does not exist."""
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out.setdefault(r["plate_id"], []).append({
                "roi_number": int(r["roi_number"] or 0),
                "region": r["region"],
                "status": r.get("status") or "auto",
                "label_conf": float(r["label_conf"]) if r.get("label_conf") else 0.0,
                "v": decode_vertices(r["vertices"]),
            })
    return out


def write_polygons(path, by_plate):
    """Write {plate_id: [polygon dicts]} atomically-enough for a hand-run tool."""
    rows = []
    for pid in sorted(by_plate):
        for p in by_plate[pid]:
            rows.append({"plate_id": pid, "roi_number": p["roi_number"],
                         "region": p["region"], "status": p["status"],
                         "label_conf": "%.3f" % p.get("label_conf", 0.0),
                         "vertices": encode_vertices(p["v"])})
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=KEYS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def _inside(x, y, v):
    inside = False
    j = len(v) - 1
    for i in range(len(v)):
        xi, yi = v[i]
        xj, yj = v[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _edge_dist(x, y, v):
    best = 1e9
    for i in range(len(v)):
        ax, ay = v[i]
        bx, by = v[(i + 1) % len(v)]
        dx, dy = bx - ax, by - ay
        L = dx * dx + dy * dy
        t = 0.0 if L == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L))
        best = min(best, ((x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2) ** 0.5)
    return best


def interior_point(v, grid=24):
    """A point well inside the polygon, as (x, y).

    The centroid of a crescent lies outside it, and a seed outside its region
    would be shown and numbered in the wrong place. So this takes the grid point
    inside the polygon that is furthest from every edge (a coarse pole of
    inaccessibility); a polygon too small for the grid falls back to the
    vertex mean.
    """
    xs = [p[0] for p in v]
    ys = [p[1] for p in v]
    best, bp = -1.0, None
    for i in range(grid):
        for j in range(grid):
            x = min(xs) + (max(xs) - min(xs)) * (i + 0.5) / grid
            y = min(ys) + (max(ys) - min(ys)) * (j + 0.5) / grid
            if _inside(x, y, v):
                d = _edge_dist(x, y, v)
                if d > best:
                    best, bp = d, (x, y)
    if bp is None:
        bp = (sum(xs) / len(xs), sum(ys) / len(ys))
    return bp


def reading_order(points):
    """Indices of `points` ((x, y) each) in the pipeline's reading order.

    Same rule as 04l's `number_seeds`: columns found by x gap, each read top to
    bottom, columns left to right. Returned as indices so the caller keeps its
    own records.
    """
    idx = sorted(range(len(points)), key=lambda i: (points[i][0], points[i][1]))
    if not idx:
        return []
    cols, cur = [], [idx[0]]
    for i in idx[1:]:
        if (points[i][0] - points[cur[-1]][0] > COL_BAND
                or points[i][0] - points[cur[0]][0] > COL_SPAN):
            cols.append(cur)
            cur = [i]
        else:
            cur.append(i)
    cols.append(cur)
    return [i for col in cols for i in sorted(col, key=lambda k: points[k][1])]


def renumber(polys):
    """Set `roi_number` 1..n in reading order on every polygon, in place."""
    pts = [interior_point(p["v"]) for p in polys]
    for n, i in enumerate(reading_order(pts), 1):
        polys[i]["roi_number"] = n
    return polys


def region_colour(region):
    """A stable colour for a region name, so a region keeps its colour on every
    plate and across runs. Derived from the name, not its position in a list."""
    h = int(hashlib.md5(region.encode("utf-8")).hexdigest()[:8], 16)
    r, g, b = colorsys.hls_to_rgb((h % 360) / 360.0, 0.62, 0.78)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def mirror(polys, midline):
    """The polygons reflected about the vertical line x = `midline`.

    Wullimann draws one hemisphere beside the micrograph of the other, so the
    reflection of each outline about the plate's midline lands on the other
    hemisphere. Vertex order is reversed so the winding stays consistent.
    """
    out = []
    for p in polys:
        q = dict(p)
        q["v"] = [[2 * midline - x, y] for x, y in reversed(p["v"])]
        q["mirrored"] = True
        out.append(q)
    return out


def plate_view(polys, midline=None, statuses=("reviewed",)):
    """(seeds, hulls) for one plate, in the shape 04l's page data expects.

    One synthetic seed per polygon, at an interior point, so everything that
    resolves an ROI through a seed number keeps working. Only polygons whose
    status is in `statuses` are used - by default just the ones a person has
    reviewed, because the name on an auto-named polygon is a guess (a label with
    a leader line can sit inside the wrong cell) and the curator uses the name as
    a measurement key. Unassigned polygons are never used. With `midline`, each
    polygon is also reflected onto the other hemisphere.
    """
    use = [p for p in polys if p["status"] in statuses and p["status"] != "unassigned" and p["region"]]
    if midline is not None:
        use = use + mirror(use, midline)
    use = [dict(p) for p in use]
    pts = [interior_point(p["v"]) for p in use]
    order = reading_order(pts)
    seeds, hulls = [], []
    counts = {}
    for p in use:
        counts[p["region"]] = counts.get(p["region"], 0) + 1
    seen = {}
    for n, i in enumerate(order, 1):
        p = use[i]
        hexc = region_colour(p["region"])
        seen[p["region"]] = seen.get(p["region"], 0) + 1
        seeds.append({"region": p["region"], "amb": "", "unk": 0,
                      "xf": pts[i][0], "yf": pts[i][1], "hex": hexc, "n": n, "roi": n})
        hulls.append({"region": p["region"], "amb": "", "unk": 0, "hex": hexc,
                      "part": seen[p["region"]], "n_parts": counts[p["region"]],
                      "seeds": [n], "v": [[round(x, 6), round(y, 6)] for x, y in p["v"]],
                      "roi": n})
    return seeds, hulls
