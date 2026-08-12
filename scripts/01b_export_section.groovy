/*
 * Export stitched sections as 16-bit TIFF at a chosen pyramid resolution.
 *
 * Used to measure the tile artifact before deciding how much correction
 * machinery is warranted, and as a general-purpose section dumper for QC.
 *
 * Environment overrides:
 *   EX_FILES   comma-separated CZI filenames        (default LS45_5a.czi)
 *   EX_SCENES  comma-separated scene indices        (default 0)
 *   EX_UMPX    target micrometres per pixel         (default 2.6)
 *   EX_OUT     output directory                     (default qc/test_sections)
 *
 * Run:
 *   ImageJ-win64.exe --ij2 --headless --console --run 01b_export_section.groovy
 */

import groovy.json.JsonSlurper
import ij.IJ
import ij.ImagePlus
import ij.process.ShortProcessor
import loci.formats.FormatTools
import loci.formats.Memoizer
import loci.formats.in.DynamicMetadataOptions
import loci.formats.in.ZeissCZIReader

// Groovy cannot resolve its own script path, so run_all.sh exports LS_CONFIG.
def configPath = System.getenv("LS_CONFIG")
if (!configPath) {
    throw new IllegalStateException(
        "LS_CONFIG is not set. Run via run_all.sh, or set it to your config.json path.")
}
def config = new JsonSlurper().parse(new File(configPath))
def sourceDir = config.source_dir
def outRoot = config.out_root
double basePx = config.pixel_size_um as double

// EX_LIST points at a two-column CSV (file,scene) so different files can
// contribute different scenes - EX_FILES x EX_SCENES only expresses a grid.
def work = [:]
def listPath = System.getenv("EX_LIST")
if (listPath && new File(listPath).exists()) {
    def lines = new File(listPath).readLines("UTF-8")
    def header = lines[0].split(",").collect { it.trim() }
    int fi = header.indexOf("file"), si = header.indexOf("scene")
    lines[1..-1].each { line ->
        def cells = line.split(",")
        if (cells.size() > Math.max(fi, si)) {
            work.get(cells[fi].trim(), []) << (cells[si].trim() as int)
        }
    }
    println "work list: ${work.size()} files, ${work.values().sum { it.size() }} scenes"
} else {
    def files = (System.getenv("EX_FILES") ?: "LS45_5a.czi").split(",").collect { it.trim() }
    def scenes = (System.getenv("EX_SCENES") ?: "0").split(",").collect { it.trim() as int }
    files.each { work[it] = scenes }
}
double targetUm = (System.getenv("EX_UMPX") ?: "2.6") as double
def outDir = new File(System.getenv("EX_OUT") ?: new File(outRoot, "qc/test_sections").getAbsolutePath())
outDir.mkdirs()

def memoDir = new File(outRoot, "work/bfmemo_stitched")
memoDir.mkdirs()

/** Stitched reader with the pyramid exposed rather than flattened. */
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

/** Pyramid level whose pixel size is closest to the requested one. */
def pickResolution = { reader, int series, double wantUm ->
    reader.setSeries(series)
    reader.setResolution(0)
    int fullW = reader.getSizeX()
    int best = 0
    double bestErr = Double.MAX_VALUE
    for (int r = 0; r < reader.getResolutionCount(); r++) {
        reader.setResolution(r)
        double umPx = basePx * fullW / (double) reader.getSizeX()
        double err = Math.abs(umPx - wantUm)
        if (err < bestErr) { bestErr = err; best = r }
    }
    return best
}

def readPlane = { reader, int channel ->
    byte[] raw = reader.openBytes(reader.getIndex(0, channel, 0))
    int w = reader.getSizeX(), h = reader.getSizeY()
    boolean little = reader.isLittleEndian()
    short[] pix = new short[w * h]
    for (int i = 0; i < pix.length; i++) {
        int lo = raw[2 * i] & 0xFF
        int hi = raw[2 * i + 1] & 0xFF
        pix[i] = (short) (little ? ((hi << 8) | lo) : ((lo << 8) | hi))
    }
    return new ShortProcessor(w, h, pix, null)
}

work.each { fileName, sceneList ->
    def path = new File(sourceDir, fileName)
    if (!path.exists()) {
        println "  !! ${fileName} not on disk yet, skipping"
        return
    }
    def reader = openStitched(path.getAbsolutePath())
    try {
        sceneList.each { int scene ->
            if (scene >= reader.getSeriesCount()) {
                println "  !! ${fileName} has no scene ${scene}"
                return
            }
            int res = pickResolution(reader, scene, targetUm)
            reader.setSeries(scene)
            reader.setResolution(res)
            reader.setResolution(0)
            int fullW = reader.getSizeX()
            reader.setResolution(res)
            double umPx = basePx * fullW / (double) reader.getSizeX()

            (0..<reader.getSizeC()).each { int c ->
                def ip = readPlane(reader, c)
                def base = fileName.replace(".czi", "")
                def name = String.format("%s_sc%02d_c%d_res%d_%.2fum.tif", base, scene, c, res, umPx)
                IJ.saveAs(new ImagePlus(name, ip), "Tiff", new File(outDir, name).getAbsolutePath())
                println String.format("  %s  %dx%d  (%.2f um/px)", name, ip.getWidth(), ip.getHeight(), umPx)
            }
        }
    } finally {
        reader.close()
    }
}
println "exported to ${outDir}"
