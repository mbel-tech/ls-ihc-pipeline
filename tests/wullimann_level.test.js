// 04k with Wullimann plates: the interpolation runs on the real section number.
//
// Wullimann's sections are not evenly spaced (steps of 8 to 21), so assigning a
// level by position in the plate list - what salmon does - puts a mid-series
// section on the wrong plate. This builds a 04k page against a throwaway
// out_root (3 anchors' worth of plates with uneven levels) and checks that the
// plate chosen is the nearest by LEVEL.
//
// Self-building, unlike the other suites: the fixture is made here, so it needs
// no atlas and no operator data.

const fs = require("fs");
const os = require("os");
const path = require("path");
const { execFileSync } = require("child_process");

const repo = path.dirname(__dirname);
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), "wl-"));
const levels = [23, 31, 50, 60, 71, 85, 92, 98, 107, 114, 121, 125, 127, 131, 136];

fs.mkdirSync(path.join(tmp, "reformatted"), { recursive: true });
fs.mkdirSync(path.join(tmp, "atlas", "plates_wullimann"), { recursive: true });
fs.writeFileSync(path.join(tmp, "config.json"),
  JSON.stringify({ out_root: tmp, atlas_source: "wullimann1996" }));
fs.writeFileSync(path.join(tmp, "reformatted", "reformat_index.csv"),
  "id,kind,animal,section_order\n" +
  [1, 2, 3, 4, 5].map(i => `s${i},section,A1,${i}`).join("\n") + "\n");
let csv = "plate_id,image_file,regions,section_level\n";
for (const l of levels) {
  const id = "wplate_" + String(l).padStart(3, "0");
  csv += `${id},${id}.png,Dm|Dl,${l}\n`;
  fs.writeFileSync(path.join(tmp, "atlas", "plates_wullimann", id + ".png"), "");
}
fs.writeFileSync(path.join(tmp, "atlas", "plates_wullimann", "plates.csv"), csv);

const html = path.join(tmp, "level.html");
let ran = false;
for (const py of [process.env.PY, "python3", "python"].filter(Boolean)) {
  try {
    execFileSync(py, [path.join(repo, "scripts", "04k_level_curator.py"), "--out", html],
      { env: { ...process.env, LS_CONFIG: path.join(tmp, "config.json") }, stdio: "pipe" });
    ran = true;
    break;
  } catch (e) { /* try the next interpreter */ }
}
if (!ran) { console.error("could not build the 04k page"); process.exit(2); }

const page = fs.readFileSync(html, "utf8");
const scripts = [...page.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]);
fs.mkdirSync(path.join(__dirname, "build"), { recursive: true });
fs.writeFileSync(path.join(__dirname, "build", "wullimann_level.js"),
  scripts.reduce((a, b) => (b.length > a.length ? b : a), ""));
fs.rmSync(tmp, { recursive: true, force: true });

const { env, load, chk, done } = require("./harness");
const X = load("{PLATES, DATA, anchors, assign, rows}", "wullimann_level");

env.els["animal"].value = X.DATA[0].animal;
const list = X.rows();
chk("the page carries the section number as the level", X.PLATES.map(p => p.level).join(","), levels.join(","));
X.anchors[list[0].uid] = 0;
X.anchors[list[4].uid] = 14;
const asg = X.assign(list);
chk("anchors land on their plates", asg[0].plate + "," + asg[4].plate, "0,14");
// halfway between level 23 and 136 is 79.5: nearest is 85 (index 5), not the
// middle of the list (index 7, level 98), which is what position-based
// interpolation would pick
chk("middle section takes the nearest level", asg[2].plate, 5);
chk("and that plate is level 85", X.PLATES[asg[2].plate].level, 85);
done();
