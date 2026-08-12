/*
 * Stage 1 - export a browsable overview of every section, plus per-section QC.
 *
 * Reads the pyramid level nearest 5.2 um/px, so a whole-brain view of each
 * section costs almost nothing: the scanner already stored it.
 *
 * Display ranges are computed ONCE from a random sample and then frozen across
 * the entire dataset. Per-image auto-contrast would make every section look
 * equally bright and destroy the cross-animal comparison that is the whole
 * point of the exercise.
 *
 * Resumable: sections whose composite already exists are skipped, so this can
 * be re-run as extraction continues without redoing finished work.
 *
 * Outputs:
 *   overviews/<animal>/<marker>/<scene_uid>_{DAPI,MARK,RGB}.png
 *   qc/display_ranges.json    frozen per-channel intensity range
 *   qc/focus.csv              focus, tissue area, saturation per section
 *
 * Environment overrides:
 *   OV_SAMPLE   sections sampled for the display range   (default 120)
 *   OV_LIMIT    stop after this many sections            (default 0 = all)
 *   OV_FORCE    1 to re-export sections that already exist
 *
 * Run:
 *   ImageJ-win64.exe --ij2 --headless --console --run 01_overviews.groovy
 */

import groovy.json.JsonOutput
import groovy.json.JsonSlurper
import ij.IJ
import ij.ImagePlus
import ij.process.ByteProcessor
import ij.process.ColorProcessor
import ij.process.ImageProcessor
import ij.process.ShortProcessor
import loci.formats.Memoizer
import loci.formats.in.DynamicMetadataOptions
import loci.formats.in.ZeissCZIReader

// ------------------------------------------------------------------ config

def config = new JsonSlurper().parse(new File("D:/LS-analysis/config.json"))
def sourceDir = config.source_dir
def outRoot = config.out_root
double basePx = config.pixel_size_um as double
double targetUm = config.overview_target_um_per_px as double

int SAMPLE_N = (System.getenv("OV_SAMPLE") ?: "120") as int
int LIMIT = (System.getenv("OV_LIMIT") ?: "0") as int
boolean FORCE = (System.getenv("OV_FORCE") ?: "0") == "1"
long SEED = 20260811L

// Percentiles that define the frozen display range, taken over tissue pixels.
// Pulled in from 0.1/99.9 because a handful of clipped pixels inside the mask
// would otherwise drag the top of the range back to 65535.
double LO_PCT = 1.0, HI_PCT = 99.5

def overviewDir = new File(outRoot, "overviews")
def qcDir = new File(outRoot, "qc")
def memoDir = new File(outRoot, "work/bfmemo_stitched")
[overviewDir, qcDir, memoDir].each { it.mkdirs() }
def rangesFile = new File(qcDir, "display_ranges.json")

// ------------------------------------------------------------------ helpers

def splitCsv = { String line ->
    def out = []; def sb = new StringBuilder(); boolean q = false
    for (int i = 0; i < line.length(); i++) {
        char c = line.charAt(i)
        if (c == ('"' as char)) q = !q
        else if (c == (',' as char) && !q) { out << sb.toString(); sb = new StringBuilder() }
        else sb.append(c)
    }
    out << sb.toString(); return out
}

def readCsv = { File f ->
    def lines = f.readLines("UTF-8")
    def header = splitCsv(lines[0])
    return lines[1..-1].collect { line ->
        def cells = splitCsv(line); def row = [:]
        header.eachWithIndex { h, i -> row[h] = (i < cells.size() ? cells[i] : "") }
        row
    }
}

def openStitched = { String path ->
    def czi = new ZeissCZIReader()
    def opts = new DynamicMetadataOptions()
    opts.setBoolean("zeissczi.autostitch", true)
    opts.setBoolean("zeissczi.attachments", false)
    czi.setMetadataOptions(opts)
    czi.setFlattenedResolutions(false)
    def reader = new Memoizer(czi, 0L, memoDir)
    reader.setId(path)
    return reader
}

def pickResolution = { reader, int series, double wantUm ->
    reader.setSeries(series); reader.setResolution(0)
    int fullW = reader.getSizeX()
    int best = 0; double bestErr = Double.MAX_VALUE
    for (int r = 0; r < reader.getResolutionCount(); r++) {
        reader.setResolution(r)
        double err = Math.abs(basePx * fullW / (double) reader.getSizeX() - wantUm)
        if (err < bestErr) { bestErr = err; best = r }
    }
    reader.setResolution(best)
    return [best, basePx * fullW / (double) reader.getSizeX()]
}

// ---- tile-field correction -------------------------------------------------
// Exact geometry from 01e_tile_geometry.py. Tile starts sit on exact multiples
// of the pitch from the scene origin (verified), so the fold phase is zero and
// no alignment search is needed.
int PITCH_PX = 1836
int FIELD_DIVISOR = 12
int FIELD_N = PITCH_PX / FIELD_DIVISOR

def tileFields = [:]
["0", "1"].each { c ->
    def f = new File(outRoot, "qc/flatfield/tilefield_c${c}.tif")
    if (f.exists()) {
        def imp = IJ.openImage(f.getAbsolutePath())
        if (imp != null) {
            tileFields[c as int] = imp.getProcessor().convertToFloat()
            println "loaded tile field for channel ${c} (${imp.getWidth()}x${imp.getHeight()})"
        }
    }
}
if (!tileFields) {
    println "no tile fields found - exporting UNCORRECTED (run 01f_tilefield.py build first)"
}

def foldIndex = { int length, double downsample ->
    int[] idx = new int[length]
    for (int i = 0; i < length; i++) {
        double native_ = i * downsample
        double m = native_ % PITCH_PX
        int v = (int) Math.round(m / FIELD_DIVISOR)
        idx[i] = ((v % FIELD_N) + FIELD_N) % FIELD_N
    }
    return idx
}

def applyTileField = { ShortProcessor sp, fieldFp, double downsample ->
    if (fieldFp == null) return sp
    int w = sp.getWidth(), h = sp.getHeight()
    int[] xi = foldIndex(w, downsample)
    int[] yi = foldIndex(h, downsample)
    short[] pix = (short[]) sp.getPixels()
    for (int y = 0; y < h; y++) {
        int row = y * w
        int fy = yi[y]
        for (int x = 0; x < w; x++) {
            double gain = fieldFp.getf(xi[x], fy)
            if (gain > 0.05) {
                int v = (int) Math.round((pix[row + x] & 0xFFFF) / gain)
                pix[row + x] = (short) Math.min(65535, Math.max(0, v))
            }
        }
    }
    return sp
}

def QC_KEYS = ["scene_uid", "file", "animal", "slide", "variant", "marker_channel",
               "scene_index", "section_order", "width", "height", "um_px", "resolution",
               "tissue_threshold", "tissue_fraction", "tissue_area_mm2", "tissue_mean",
               "focus_score", "saturated_fraction", "tilefield_applied"]

/** Write focus.csv atomically, so an interrupted write cannot truncate it. */
def writeQc = { File target, List rows ->
    if (!rows) return
    def sb = new StringBuilder(QC_KEYS.join(",")).append("\n")
    rows.each { row -> sb.append(QC_KEYS.collect { row[it] ?: "" }.join(",")).append("\n") }
    def tmp = new File(target.getParentFile(), target.getName() + ".tmp")
    tmp.text = sb.toString()
    target.delete()
    tmp.renameTo(target)
}

def readPlane = { reader, int channel ->
    byte[] raw = reader.openBytes(reader.getIndex(0, channel, 0))
    int w = reader.getSizeX(), h = reader.getSizeY()
    boolean little = reader.isLittleEndian()
    short[] pix = new short[w * h]
    for (int i = 0; i < pix.length; i++) {
        int lo = raw[2 * i] & 0xFF, hi = raw[2 * i + 1] & 0xFF
        pix[i] = (short) (little ? ((hi << 8) | lo) : ((lo << 8) | hi))
    }
    return new ShortProcessor(w, h, pix, null)
}

/** Otsu split in log space.
 *
 * These channels are wildly skewed - DAPI has a median near 500 against a
 * 99.9th percentile near 30000 - and plain Otsu maximises between-class
 * variance by chasing the bright tail, returning a threshold above almost
 * every pixel. Logs make the two populations comparably wide.
 */
def logOtsu = { ShortProcessor sp ->
    short[] pix = (short[]) sp.getPixels()
    int NB = 512
    double maxLog = Math.log1p(65535.0d)
    long[] hist = new long[NB]
    long total = 0
    for (short s : pix) {
        int v = s & 0xFFFF
        if (v <= 0) continue
        int b = (int) (Math.log1p((double) v) / maxLog * (NB - 1))
        hist[b]++; total++
    }
    if (total < 100) return 0

    double sumAll = 0
    for (int i = 0; i < NB; i++) sumAll += i * (double) hist[i]
    double sumB = 0, wB = 0, best = -1; int bestBin = 0
    for (int i = 0; i < NB; i++) {
        wB += hist[i]; if (wB == 0) continue
        double wF = total - wB; if (wF == 0) break
        sumB += i * (double) hist[i]
        double mB = sumB / wB, mF = (sumAll - sumB) / wF
        double between = wB * wF * (mB - mF) * (mB - mF)
        if (between > best) { best = between; bestBin = i }
    }
    return (int) Math.round(Math.expm1(bestBin / (double) (NB - 1) * maxLog))
}

def percentileFromHist = { long[] hist, double pct ->
    long total = 0; for (long c : hist) total += c
    if (total == 0) return 0
    long want = (long) Math.ceil(total * pct / 100.0d)
    long run = 0
    for (int i = 0; i < hist.length; i++) {
        run += hist[i]
        if (run >= want) return i
    }
    return hist.length - 1
}

// ------------------------------------------------------------------ inventory

def scenes = readCsv(new File(outRoot, "manifest/manifest_scenes.csv"))
def present = [:]
scenes.each { r ->
    if (!present.containsKey(r.file)) {
        present[r.file] = new File(sourceDir, r.file).exists()
    }
}
def usable = scenes.findAll { present[it.file] }
println "manifest: ${scenes.size()} sections, ${usable.size()} with the CZI on disk"

def byFile = usable.groupBy { it.file }
println "files to process: ${byFile.size()}"

// ------------------------------------------------------------------ pass A: display range

def ranges = [:]
if (rangesFile.exists() && !FORCE) {
    ranges = new JsonSlurper().parse(rangesFile)
    println "display ranges loaded from ${rangesFile.name}: ${ranges}"
} else {
    println "\nsampling ${SAMPLE_N} sections to fix the display range ..."
    def pool = new ArrayList(usable)
    Collections.shuffle(pool, new Random(SEED))
    def sample = pool.take(Math.min(SAMPLE_N, pool.size()))
    def sampleByFile = sample.groupBy { it.file }

    def hists = [:]
    int done = 0
    sampleByFile.each { fileName, rows ->
        def reader
        try { reader = openStitched(new File(sourceDir, fileName).getAbsolutePath()) }
        catch (Exception e) { println "  !! ${fileName}: ${e.message}"; return }
        try {
            rows.each { r ->
                int scene = r.scene_index as int
                if (scene >= reader.getSeriesCount()) return
                def (resS, umPxS) = pickResolution(reader, scene, targetUm)
                double dsS = (umPxS as double) / basePx
                // Histogram TISSUE ONLY, on the corrected data so the frozen
                // range matches what gets exported.
                //
                // Sampling the whole frame let the AF568 background - which on
                // many sections is brighter than the brain itself - set the
                // 99.9th percentile to 65535. The display range then spanned
                // the full 16 bits and real tissue rendered at about 20/255.
                // The background is not the thing we are trying to see.
                def dapiS = applyTileField(readPlane(reader, 0), tileFields[0], dsS)
                def markS = applyTileField(readPlane(reader, 1), tileFields[1], dsS)
                int thrS = logOtsu(dapiS)
                short[] dP = (short[]) dapiS.getPixels()
                short[] mP = (short[]) markS.getPixels()

                hists.putIfAbsent("DAPI", new long[65536])
                hists.putIfAbsent(r.marker_channel, new long[65536])
                long[] hD = hists["DAPI"], hM = hists[r.marker_channel]
                for (int i = 0; i < dP.length; i++) {
                    if ((dP[i] & 0xFFFF) <= thrS) continue
                    hD[dP[i] & 0xFFFF]++
                    hM[mP[i] & 0xFFFF]++
                }
                done++
            }
        } catch (Exception e) { println "  !! ${fileName}: ${e}" }
        finally { reader.close() }
        print "\r  sampled ${done}/${sample.size()} sections"
    }
    println ""
    hists.each { name, h ->
        ranges[name] = [lo: percentileFromHist(h, LO_PCT), hi: percentileFromHist(h, HI_PCT)]
        println "  ${name}: display range ${ranges[name].lo} .. ${ranges[name].hi}"
    }
    rangesFile.text = JsonOutput.prettyPrint(JsonOutput.toJson(ranges))
}

// ------------------------------------------------------------------ pass B: export

def qcFile = new File(qcDir, "focus.csv")
def qcRows = []
if (qcFile.exists() && !FORCE) {
    readCsv(qcFile).each { qcRows << it }
    println "resuming: ${qcRows.size()} sections already in focus.csv"
}
def alreadyDone = qcRows.collect { it.scene_uid } as Set

int exported = 0, skipped = 0, failed = 0
long tStart = System.currentTimeMillis()

for (entry in byFile) {
    def fileName = entry.key
    def rows = entry.value
    if (LIMIT > 0 && exported >= LIMIT) break

    def todo = FORCE ? rows : rows.findAll { !alreadyDone.contains(it.scene_uid) }
    if (!todo) { skipped += rows.size(); continue }

    def reader
    try { reader = openStitched(new File(sourceDir, fileName).getAbsolutePath()) }
    catch (Exception e) { println "  !! ${fileName}: cannot open (${e.message})"; failed += todo.size(); continue }

    try {
        def marker = rows[0].marker_channel
        def dir = new File(overviewDir, "${rows[0].animal}/${marker}")
        dir.mkdirs()
        def rLo = ranges["DAPI"].lo as double, rHi = ranges["DAPI"].hi as double
        def mLo = ranges[marker].lo as double, mHi = ranges[marker].hi as double

        todo.each { r ->
            if (LIMIT > 0 && exported >= LIMIT) return
            int scene = r.scene_index as int
            if (scene >= reader.getSeriesCount()) { failed++; return }

            def (res, umPx) = pickResolution(reader, scene, targetUm)
            double ds = (umPx as double) / basePx
            def dapi = applyTileField(readPlane(reader, 0), tileFields[0], ds)
            def mark = applyTileField(readPlane(reader, 1), tileFields[1], ds)
            int w = dapi.getWidth(), h = dapi.getHeight()

            // Tissue from DAPI, and the QC numbers that flag bad sections.
            int thr = logOtsu(dapi)
            short[] dPix = (short[]) dapi.getPixels()
            short[] mPix = (short[]) mark.getPixels()
            long tissueCount = 0, satCount = 0
            double tissueSum = 0
            for (int i = 0; i < dPix.length; i++) {
                int v = dPix[i] & 0xFFFF
                if (v > thr) { tissueCount++; tissueSum += v }
                if ((mPix[i] & 0xFFFF) >= 65535) satCount++
            }
            double tissueFrac = tissueCount / (double) dPix.length
            double tissueMean = tissueCount > 0 ? tissueSum / tissueCount : 0

            // Focus: Sobel energy inside tissue, normalised by brightness so a
            // dim section is not mistaken for a blurred one.
            def edges = dapi.duplicate()
            edges.filter(ImageProcessor.FIND_EDGES)
            short[] ePix = (short[]) edges.getPixels()
            double edgeSum = 0
            for (int i = 0; i < ePix.length; i++) {
                if ((dPix[i] & 0xFFFF) > thr) edgeSum += (ePix[i] & 0xFFFF)
            }
            double focus = (tissueCount > 0 && tissueMean > 0) ? (edgeSum / tissueCount) / tissueMean : 0

            def dByte = dapi.duplicate(); dByte.setMinAndMax(rLo, rHi)
            def mByte = mark.duplicate(); mByte.setMinAndMax(mLo, mHi)
            def d8 = (ByteProcessor) dByte.convertToByte(true)
            def m8 = (ByteProcessor) mByte.convertToByte(true)

            // Blue nuclei, yellow marker - the most separable pairing, and it
            // survives the common forms of colour blindness.
            def rgb = new ColorProcessor(w, h)
            byte[] db = (byte[]) d8.getPixels()
            byte[] mb = (byte[]) m8.getPixels()
            int[] px = (int[]) rgb.getPixels()
            for (int i = 0; i < px.length; i++) {
                int mv = mb[i] & 0xFF, dv = db[i] & 0xFF
                px[i] = (mv << 16) | (mv << 8) | dv
            }

            def uid = r.scene_uid
            IJ.saveAs(new ImagePlus(uid, d8), "PNG", new File(dir, "${uid}_DAPI.png").getAbsolutePath())
            IJ.saveAs(new ImagePlus(uid, m8), "PNG", new File(dir, "${uid}_MARK.png").getAbsolutePath())
            IJ.saveAs(new ImagePlus(uid, rgb), "PNG", new File(dir, "${uid}_RGB.png").getAbsolutePath())

            qcRows << [
                scene_uid: uid, file: fileName, animal: r.animal, slide: r.slide,
                variant: r.variant, marker_channel: marker, scene_index: r.scene_index,
                section_order: r.section_order,
                width: w, height: h, um_px: String.format("%.2f", umPx), resolution: res,
                tissue_threshold: thr,
                tissue_fraction: String.format("%.4f", tissueFrac),
                tissue_area_mm2: String.format("%.3f", tissueCount * umPx * umPx / 1.0e6),
                tissue_mean: String.format("%.1f", tissueMean),
                focus_score: String.format("%.4f", focus),
                saturated_fraction: String.format("%.6f", satCount / (double) mPix.length),
                tilefield_applied: (tileFields ? 1 : 0),
            ]
            exported++
        }
    } catch (Exception e) {
        println "  !! ${fileName}: ${e}"
        failed++
    } finally {
        reader.close()
    }

    // Checkpoint after every file. This job runs for hours against an external
    // USB drive that has already dropped writes once, and focus.csv is what
    // makes a restart resume instead of redo - writing it only at the end
    // meant a crash at hour five threw away all five.
    writeQc(qcFile, qcRows)

    double mins = (System.currentTimeMillis() - tStart) / 60000.0
    print "\r  exported ${exported}  failed ${failed}  (${String.format('%.1f', mins)} min)"
}
println ""

writeQc(qcFile, qcRows)
println "wrote ${qcFile} (${qcRows.size()} sections)"

println "\nexported ${exported}, skipped ${skipped}, failed ${failed}"
println "NEXT: 01d_contactsheets.py to build the per-animal montages."
