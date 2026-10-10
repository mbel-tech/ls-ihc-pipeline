// 04x review page: naming, deleting, drawing and what reaches the export.
//
// Self-building like wullimann_level.test.js: a throwaway plate set with two
// polygons on one plate, a page built from it by `04x --review`, then the page's
// own functions driven under the stub DOM.

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const repo = path.dirname(__dirname);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wr-"));
fs.writeFileSync(path.join(tmp, "plates.csv"),
  "plate_id,page,image_file,px_w,px_h,n_seeds,regions,section_level,midline_frac\n" +
  "wplate_071,6,wplate_071.png,400,300,0,Dl|Dm|V,71,0.5\n");
fs.writeFileSync(path.join(tmp, "wplate_071.png"), "");
fs.writeFileSync(path.join(tmp, "polygons.csv"),
  "plate_id,roi_number,region,status,label_conf,vertices\n" +
  "wplate_071,1,Dm,auto,0.900,0.05 0.05;0.45 0.05;0.45 0.45;0.05 0.45\n" +
  "wplate_071,2,,unassigned,0.000,0.10 0.60;0.30 0.60;0.30 0.90;0.10 0.90\n");
const legends = path.join(tmp, "legends.csv");
fs.writeFileSync(legends, "cross_section,pdf_page,abbreviation,definition\n" +
  "71,6,Dl,lateral zone of D\n71,6,Dm,medial zone of D\n71,6,V,ventral telencephalic area\n");

let ran = false;
for (const py of [process.env.PY, "python3", "python"].filter(Boolean)) {
  try {
    execFileSync(py, [path.join(repo, "scripts", "04x_wullimann_polygons.py"),
      "--plate-dir", tmp, "--review", "--legends", legends], { stdio: "pipe" });
    ran = true;
    break;
  } catch (e) { /* next interpreter */ }
}
if (!ran) { console.error("could not build the review page"); process.exit(2); }
const page = fs.readFileSync(path.join(tmp, "polygon_review.html"), "utf8");
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
fs.mkdirSync(path.join(__dirname, "build"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "build", "wullimann_review.js"),
  scripts.reduce((a, b) => (b.length > a.length ? b : a), ""));
fs.rmSync(tmp, { recursive: true, force: true });

const { env, load, chk, done } = require("./harness");
const X = load(`{PLATES, state, polysOf, hit, setName, confirmSel, unassignSel, removeSel,
  addPoly, exportRows, set sel(v){sel=v}, get sel(){return sel}, KEY}`, "wullimann_review");

const P = X.PLATES[0];
chk("legend carries the definitions", P.legend.map(g => g.ab + "=" + g.def).join("|"),
    "Dl=lateral zone of D|Dm=medial zone of D|V=ventral telencephalic area");
chk("polygons come in as the extractor left them",
    X.polysOf(P).map(q => q.region + ":" + q.status).join(","), "Dm:auto,:unassigned");

chk("a click inside a polygon finds it", X.hit(P, 0.2, 0.2), 0);
chk("a click outside every polygon finds none", X.hit(P, 0.8, 0.8), -1);

X.sel = 1; X.setName("Dl");
chk("naming a polygon reviews it", X.polysOf(P)[1].region + ":" + X.polysOf(P)[1].status, "Dl:reviewed");
X.sel = 0; X.confirmSel();
chk("confirming an auto name reviews it", X.polysOf(P)[0].status, "reviewed");
X.sel = 0; X.unassignSel();
chk("unnaming clears the name and the review",
    X.polysOf(P)[0].region + "|" + X.polysOf(P)[0].status, "|unassigned");
X.setName("V");
chk("a name can be set again", X.polysOf(P)[0].region, "V");

X.addPoly([[0.5, 0.5], [0.7, 0.5], [0.7, 0.7]]);
chk("a drawn polygon is added unassigned", X.polysOf(P).slice(-1)[0].status, "unassigned");
chk("and selected", X.sel, 2);
X.removeSel();
chk("delete removes the selected polygon", X.polysOf(P).length, 2);
chk("and clears the selection", X.sel, -1);

const lines = X.exportRows().trim().split("\n");
chk("export header", lines[0], "plate_id,roi_number,region,status,label_conf,vertices");
chk("one row per polygon", lines.length - 1, 2);
chk("rows carry name and status", lines.slice(1).map(l => l.split(",").slice(2, 4).join(":")).join("|"),
    "V:reviewed|Dl:reviewed");
chk("choices autosave", Object.keys(JSON.parse(env.store[X.KEY])).join(), "wplate_071");
done();
