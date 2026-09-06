// Where an export goes and what it is called.
//
// One folder per export action, named DD.MM.YYYY_HH.MM, with the same stamp on
// every file in it. The stamp is per ACTION rather than per file: exportCsv
// writes three CSVs that are three views of one set of decisions, and a stamp
// taken per file would scatter them across two folders whenever the clock
// ticked over mid-export.

const { env, load, chk, note, done } = require("./harness");
const { blobs } = env;

const X = load(`{beginExport, expName, expStampNow, saveExport, expWrite, dl, exportCsv,
  KEY, PLATES, st, rows, select, onSlideUser,
  get expDir(){return expDir}, set expDir(v){expDir=v},
  get expSub(){return expSub}, set expSub(v){expSub=v},
  set active(v){active=v}, get active(){return active}}`);

const STAMP = /^\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}$/;
const stampOf = n => (String(n).match(/_(\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2})(?:\.|$)/) || [])[1];

chk("the stamp is DD.MM.YYYY_HH.MM", STAMP.test(X.expStampNow()), true);

// The extension stays last. 05a finds an export by globbing roi_regions*.csv,
// and a stamp appended after ".csv" would not match it - nor would the file
// open by double-click.
X.beginExport();
chk("the stamp goes before the extension",
    /^roi_regions_\d{2}\.\d{2}\.\d{4}_\d{2}\.\d{2}\.csv$/.test(X.expName("roi_regions.csv")), true);
chk("a name with no extension still gets one",
    STAMP.test(stampOf(X.expName("deck"))), true);
chk("a name with dots in it keeps all but the last",
    X.expName("a.b.csv").startsWith("a.b_"), true);

// Everything written between two beginExport() calls shares one stamp, which is
// what puts the three files of one export in one folder.
X.beginExport();
const oneAction = ["roi_plates.csv", "roi_landmarks.csv", "roi_regions.csv"].map(X.expName);
chk("three files of one export share a stamp", new Set(oneAction.map(stampOf)).size, 1);

// Without a folder the name still carries the stamp, because that is all the
// fallback has: browsers strip path separators from the download attribute, so
// the host decides the directory and reads the folder back off the name.
X.expDir = null;
X.beginExport();
chk("the fallback name is stamped too", STAMP.test(stampOf(X.expName("section_review.csv"))), true);

// dl() still produces the same CSV. It routes through saveExport now, and the
// quoting and row joining had to come through that unchanged.
blobs.length = 0;
X.dl([["h1", "h2"], ["x,y", 'q"r']], "t.csv");
chk("dl still quotes each field", blobs[0], 'h1,h2\n"x,y","q""r"');

// The chosen-folder path: the dated folder is created ONCE for an action, not
// once per file. Three concurrent writes racing to create it is exactly what
// the serialised queue in saveExport exists to prevent.
const made = [], wrote = [], fell = [];
const dirStub = name => ({
  name,
  queryPermission: async () => "granted",
  requestPermission: async () => "granted",
  getDirectoryHandle: async n => { made.push(n); return dirStub(n); },
  getFileHandle: async n => ({
    createWritable: async () => ({ write: async () => { wrote.push(n); }, close: async () => {} }),
  }),
});

// Drain first. saveExport reads the destination when the write RUNS, not when
// it is queued, so anything the checks above left in the queue would otherwise
// be counted here - and would land in the folder, since it is set below. That
// is deliberate: choosing a folder mid-export applies to the rest of it.
X.expDir = null;
X.saveExport({ size: 1 }, "drain.csv").then(() => {
  made.length = 0; wrote.length = 0; fell.length = 0;
  X.beginExport();
  X.expDir = dirStub("Exports");
  X.expSub = null;
  return Promise.all([
    X.saveExport({ size: 1 }, "roi_plates.csv"),
    X.saveExport({ size: 1 }, "roi_landmarks.csv"),
    X.saveExport({ size: 1 }, "roi_regions.csv"),
  ]);
}).then(() => {
  chk("the dated folder is created once, not once per file", made.length, 1);
  chk("...and it is named for the stamp", STAMP.test(made[0]), true);
  chk("all three files are written into it", wrote.length, 3);
  chk("...each under the action's stamp", new Set(wrote.map(stampOf)).size, 1);
  note(`folder ${made[0]}/ holds ${wrote.length} files`);

  // A folder that is gone, or a permission the browser dropped, must not lose
  // the export: it falls back to the download rather than throwing it away.
  global.document.createElement = () => ({
    set download(v) { fell.push(v); }, set href(v) {}, click() {},
  });
  X.expSub = null;
  X.expDir = { name: "Gone", queryPermission: async () => "granted",
               requestPermission: async () => "granted",
               getDirectoryHandle: async () => { throw new Error("NotFoundError"); } };
  return X.saveExport({ size: 1 }, "roi_regions.csv");
}).then(() => {
  chk("a lost folder falls back to the download, it does not lose the file",
      fell.length, 1);
  chk("...and the fallback name still carries the stamp",
      STAMP.test(stampOf(fell[0])), true);
  done();
});
