/*
 * Stage 1b - retrospective flat-field estimation from raw tiles.
 *
 * The scanner applied no shading correction (SelectedShadingReferenceMode =
 * None) and never blended tiles, so every 2040 x 2040 tile carries its own
 * illumination falloff. Repeated across ~78 tiles per slide that produces a
 * periodic intensity grid which is multiplicative, spatially fixed, and
 * therefore survives averaging - it masquerades as anatomy and biases any
 * fixed-threshold detection toward tile centres.
 *
 * Method: per-pixel median across many randomly chosen tiles. Tissue sits at a
 * random position relative to the tile grid, so the median over enough tiles
 * converges on illumination alone. Computed at reduced resolution because
 * vignetting is low-frequency, then smoothed and normalised to mean 1.
 *
 * This is deliberately the simplest defensible estimator. The objective test is
 * 01b_verify_flatfield: the tile-pitch peak in the 2-D power spectrum must drop
 * to noise. If it does not, escalate to BaSiC.
 *
 * Run:
 *   ImageJ-win64.exe --ij2 --headless --console --run 01a_flatfield.groovy
 */

import groovy.json.JsonSlurper
import ij.IJ
import ij.ImagePlus
import ij.ImageStack
import ij.plugin.ZProjector
import ij.process.FloatProcessor
import ij.process.ImageProcessor
import loci.formats.FormatTools
import loci.formats.Memoizer
import loci.formats.in.DynamicMetadataOptions
import loci.formats.in.ZeissCZIReader

// ------------------------------------------------------------------ config

// Groovy cannot resolve its own script path, so run_all.sh exports LS_CONFIG.
def configPath = System.getenv("LS_CONFIG")
if (!configPath) {
    throw new IllegalStateException(
        "LS_CONFIG is not set. Run via run_all.sh, or set it to your config.json path.")
}
def config = new JsonSlurper().parse(new File(configPath))
def outRoot = config.out_root
def sourceDir = config.source_dir
def ffCfg = config.flatfield

int downTo = ffCfg.downsample_to_px as int
double smoothSigma = ffCfg.smoothing_sigma_px as double

// Files sampled per marker channel. Reader init dominates the runtime
// (~56 s/file), so take many tiles from few files rather than the reverse.
int FILES_PER_MARKER = (System.getenv("FF_FILES") ?: "10") as int
int TILES_PER_FILE = (System.getenv("FF_TILES") ?: "60") as int
long SEED = 20260811L

def flatDir = new File(outRoot, "qc/flatfield")
flatDir.mkdirs()
def memoDir = new File(outRoot, "work/bfmemo_tiles")
memoDir.mkdirs()

// ------------------------------------------------------------------ helpers

/** Minimal quote-aware CSV row splitter. */
def splitCsv = { String line ->
    def out = []
    def sb = new StringBuilder()
    boolean inQuotes = false
    for (int i = 0; i < line.length(); i++) {
        char c = line.charAt(i)
        if (c == ('"' as char)) {
            inQuotes = !inQuotes
        } else if (c == (',' as char) && !inQuotes) {
            out << sb.toString(); sb = new StringBuilder()
        } else {
            sb.append(c)
        }
    }
    out << sb.toString()
    return out
}

def readManifest = { File f ->
    def lines = f.readLines("UTF-8")
    def header = splitCsv(lines[0])
    return lines[1..-1].collect { line ->
        def cells = splitCsv(line)
        def row = [:]
        header.eachWithIndex { h, i -> row[h] = (i < cells.size() ? cells[i] : "") }
        return row
    }
}

/** Bio-Formats reader over raw (unstitched) tiles, memoised for fast re-opens. */
def openTileReader = { String path ->
    def czi = new ZeissCZIReader()
    def opts = new DynamicMetadataOptions()
    opts.setBoolean("zeissczi.autostitch", false)
    opts.setBoolean("zeissczi.attachments", false)
    czi.setMetadataOptions(opts)
    czi.setFlattenedResolutions(false)
    def reader = new Memoizer(czi, 0L, memoDir)
    reader.setId(path)
    return reader
}

/** One plane of one tile as a FloatProcessor, downsampled with averaging. */
def readTileDownsampled = { reader, int series, int channel, int target ->
    reader.setSeries(series)
    byte[] raw = reader.openBytes(reader.getIndex(0, channel, 0))
    int w = reader.getSizeX()
    int h = reader.getSizeY()
    boolean little = reader.isLittleEndian()
    int bpp = FormatTools.getBytesPerPixel(reader.getPixelType())
    if (bpp != 2) {
        throw new IllegalStateException("expected 16-bit tiles, got ${bpp * 8}-bit")
    }

    float[] pix = new float[w * h]
    for (int i = 0; i < pix.length; i++) {
        int lo = raw[2 * i] & 0xFF
        int hi = raw[2 * i + 1] & 0xFF
        pix[i] = little ? ((hi << 8) | lo) : ((lo << 8) | hi)
    }
    def fp = new FloatProcessor(w, h, pix, null)
    fp.setInterpolationMethod(ImageProcessor.BILINEAR)
    return fp.resize(target, target, true)   // true = average when downsizing
}

// ------------------------------------------------------------------ sampling

def manifest = readManifest(new File(outRoot, "manifest/manifest_files.csv"))
def unique = manifest.findAll { it.is_redundant_copy == "0" }
println "manifest: ${unique.size()} unique files"

def rng = new Random(SEED)
def byMarker = unique.groupBy { it.marker_channel }
def chosen = []
byMarker.each { marker, rows ->
    def pool = rows.findAll { new File(sourceDir, it.file).exists() }
    println "  ${marker}: ${pool.size()} of ${rows.size()} present on disk"
    Collections.shuffle(pool, rng)
    chosen.addAll(pool.take(FILES_PER_MARKER))
}
println "sampling ${chosen.size()} files, ${TILES_PER_FILE} tiles each"

// Accumulate downsampled tiles per channel name (DAPI plus each marker).
def stacks = [:]
def addSlice = { String channelName, ImageProcessor ip ->
    if (!stacks.containsKey(channelName)) {
        stacks[channelName] = new ImageStack(ip.getWidth(), ip.getHeight())
    }
    stacks[channelName].addSlice(ip)
}

// ------------------------------------------------------------------ collect

long tStart = System.currentTimeMillis()
chosen.eachWithIndex { row, fileIndex ->
    def path = new File(sourceDir, row.file).getAbsolutePath()
    long t0 = System.currentTimeMillis()
    def reader
    try {
        reader = openTileReader(path)
    } catch (Exception e) {
        println "  !! ${row.file}: cannot open (${e.message})"
        return
    }

    try {
        int nSeries = reader.getSeriesCount()
        def order = (0..<nSeries).toList()
        Collections.shuffle(order, rng)
        def picks = order.take(Math.min(TILES_PER_FILE, nSeries))

        picks.each { s ->
            addSlice("DAPI", readTileDownsampled(reader, s, 0, downTo))
            addSlice(row.marker_channel, readTileDownsampled(reader, s, 1, downTo))
        }
        println String.format(
            "  [%2d/%2d] %-18s %s  %d tiles in %.1f s",
            fileIndex + 1, chosen.size(), row.file, row.marker_channel,
            picks.size(), (System.currentTimeMillis() - t0) / 1000.0)
    } catch (Exception e) {
        println "  !! ${row.file}: ${e}"
    } finally {
        reader.close()
    }
}
println String.format("collection done in %.1f min", (System.currentTimeMillis() - tStart) / 60000.0)

// ------------------------------------------------------------------ reduce

stacks.each { channelName, stack ->
    println "\n${channelName}: ${stack.getSize()} tiles"
    if (stack.getSize() < 20) {
        println "  !! too few tiles for a stable median, skipping"
        return
    }

    def projected = ZProjector.run(new ImagePlus(channelName, stack), "median")
    def fp = projected.getProcessor().convertToFloat()

    // Vignetting is low-frequency; smoothing removes residual tissue texture.
    fp.blurGaussian(smoothSigma)

    // Normalise to mean 1 so the field is a pure multiplicative gain.
    float[] pix = (float[]) fp.getPixels()
    double sum = 0.0d
    for (float v : pix) sum += v
    double mean = sum / pix.length
    if (mean <= 0) {
        println "  !! non-positive mean, skipping"
        return
    }
    double lo = Double.MAX_VALUE, hi = -Double.MAX_VALUE
    for (int i = 0; i < pix.length; i++) {
        pix[i] = (float) (pix[i] / mean)
        if (pix[i] < lo) lo = pix[i]
        if (pix[i] > hi) hi = pix[i]
    }

    def imp = new ImagePlus("flatfield_${channelName}", fp)
    IJ.saveAs(imp, "Tiff", new File(flatDir, "flatfield_${channelName}.tif").getAbsolutePath())

    // Human-readable preview.
    def preview = fp.duplicate()
    preview.setMinAndMax(lo, hi)
    IJ.saveAs(new ImagePlus("preview", preview.convertToByte(true)), "PNG",
              new File(flatDir, "flatfield_${channelName}_preview.png").getAbsolutePath())

    println String.format(
        "  gain range %.3f to %.3f  ->  %.1f%% vignetting corner to centre",
        lo, hi, (hi / lo - 1.0) * 100.0)
    new File(flatDir, "flatfield_${channelName}.txt").text =
        "channel=${channelName}\ntiles=${stack.getSize()}\n" +
        "downsampled_to=${downTo}\nsmoothing_sigma=${smoothSigma}\n" +
        "gain_min=${lo}\ngain_max=${hi}\nvignetting_percent=${(hi / lo - 1.0) * 100.0}\n"
}

println "\nflat fields written to ${flatDir}"
println "NEXT: 01b_verify_flatfield - the tile-pitch power-spectrum peak must drop to noise."
