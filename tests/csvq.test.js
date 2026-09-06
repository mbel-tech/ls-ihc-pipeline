// Every 04l export goes through one quoting rule.

const { env, load, chk, note, done } = require("./harness");
const { els, store, blobs } = env;

const X = load(`{KEY, PLATES, st, rows, select, onSlideUser, exportCsv, exportReview, csvq, dl,
  set active(v){active=v}, get active(){return active}}`);

chk("plain stays plain", X.csvq("Dm"), "Dm");
chk("a comma is quoted", X.csvq("a,b"), '"a,b"');
chk("a quote is doubled", X.csvq('say "hi"'), '"say ""hi"""');
chk("null is empty", X.csvq(null), "");

blobs.length = 0;
X.dl([["h1", "h2"], ["x,y", 'q"r'], [1, ""]], "t.csv");
chk("dl quotes each field", blobs[0], 'h1,h2\n"x,y","q""r"\n1,');

// A region label with a comma reaches roi_regions.csv intact.
const pi = X.PLATES.findIndex(P => P.labelled), P = X.PLATES[pi];
els["animal"].value = "LS105";
const uid = X.rows()[0].uid; X.select(uid, true); X.active = uid; X.onSlideUser(pi);
P.seeds[0].region = "Dm, medial"; P.seeds[0].amb = "";
const s = X.st(uid);
s.pairs.push([10, 10, 20, 20, 1, 5], [30, 30, 40, 40, 2, 5], [50, 50, 60, 60, 3, 5]);
blobs.length = 0; X.exportCsv();
const rg = blobs[2].split("\n"), hdr = rg[0].split(",");
chk("the region is quoted", rg.slice(1).some(l => l.includes('"Dm, medial"')), true);
// Fields, counting only the commas that are not inside quotes. A regex split
// gets the trailing empty field wrong, and every row here ends with two.
const cols = l => {
  let n = 1, q = false;
  for (const c of l) { if (c === '"') q = !q; else if (c === "," && !q) n++; }
  return n;
};
chk("...so every row has the header's column count", rg.slice(1).every(l => cols(l) === hdr.length), true);

// exportReview: one level of quoting, not two.
s.rev = {act: "drop", why: 'torn, "badly"', status: "measured"};
blobs.length = 0; X.exportReview();
chk("the review reason is quoted exactly once",
    blobs[0].split("\n")[1].includes('"torn, ""badly"""'), true);
chk("...not wrapped twice", blobs[0].includes('"""torn'), false);

done();
