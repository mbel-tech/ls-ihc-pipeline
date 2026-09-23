"""Run a pipeline stage in this process, on a worker thread.

The stages are command-line scripts with numeric-prefixed names, so they cannot
be imported by `import 00_manifest`. `04o_section_rgb.py` already solves this for
its own use of `04a_reformat` - load by file path via importlib - and this is the
same trick generalised. No stage is renamed or otherwise altered to suit the app.

In-process rather than subprocess, for one reason that matters: the frozen build
has no external Python to shell out to. Running the stages as imported modules is
what lets a single bundled interpreter be the whole application.

Two things the stages already do that this has to respect:

  * Several of them `raise SystemExit(message)` on bad input - `analysis_uids`
    does it for AF488, `04o` does it for a missing composite directory. That is a
    deliberate, informative failure, and it must land in the log as a failed
    stage rather than taking the window down with it.

  * They read config.json at import time into module-level constants. The import
    screen rewrites config, so a module imported before that would keep serving
    stale paths. Modules are therefore cached per config mtime and dropped when
    it changes.
"""

import contextlib
import importlib.util
import io
import json
import hashlib
import os
import sys
import threading
import time
import traceback

import stages as SG


class StageResult:
    def __init__(self, sid, ok, seconds, output, error=None):
        self.sid = sid
        self.ok = ok
        self.seconds = seconds
        self.output = output
        self.error = error


class _Tee(io.TextIOBase):
    """Collect stage output and hand each line to a callback as it appears.

    Line-buffered on purpose: the point of the log pane is watching a long stage
    progress, and a stage that prints a percentage every few seconds is useless
    if the text only lands when it finishes.
    """

    def __init__(self, on_line):
        self._on_line = on_line
        self._buf = ""
        self._all = []

    def write(self, s):
        if not s:
            return 0
        self._all.append(s)
        # A stage reporting progress prints "\r  12/454" with end="" and never
        # sends a newline until it is finished, so a carriage return has to
        # count as a line end here or the pane stays blank for the whole run.
        self._buf += s.replace("\r\n", "\n").replace("\r", "\n")
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if self._on_line:
                self._on_line(line)
        return len(s)

    def flush(self):
        if self._buf and self._on_line:
            self._on_line(self._buf)
            self._buf = ""

    def text(self):
        return "".join(self._all)


class Runner:
    """Loads and runs stages. One instance per application."""

    def __init__(self, scripts_dir, config_path):
        self.scripts_dir = scripts_dir
        self.config_path = os.path.abspath(config_path)
        self._modules = {}
        self._config_stamp = None
        self._lock = threading.Lock()
        # The stages resolve config.json relative to their own file unless
        # LS_CONFIG says otherwise. Frozen, their own file is inside _internal/
        # and config.json is beside the executable, so without this every
        # stage fails at import with a missing file.
        os.environ["LS_CONFIG"] = self.config_path

    # ---- argv -------------------------------------------------------------

    def _config_dict(self):
        try:
            with open(self.config_path, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def names(self):
        """This study's `ls_paths.Names` - markers, layout and artifact names.

        The app asks for this rather than reading `acquisition.markers` itself,
        because which markers a study HAS is layout-dependent (a multiplex
        study has no such list; its markers are the channel table's) and
        `ls_channels.marker_names` is the one place that knows. `ls_paths`
        wraps it and adds the pre-rename names, which is the other half of what
        the stage table needs.

        Not cached here: `for_config` memoises on the three facts a Names is
        built from, so re-asking after a config edit gets the new study and
        re-asking without one costs a dict lookup.
        """
        return SG.LP.for_config(self._config_dict())

    def markers(self):
        """The study's declared markers, in order. `()` if it cannot be read."""
        return tuple(self.names().markers)

    def expand_argv(self, argv):
        """Fill `{out_root}`, `{repo}`, `{scripts}` and `{markerN}` in argv.

        stages.py is static data and cannot know where the outputs live or what
        this study's markers are called; the stages that take absolute paths
        (04q's three exports, 06b's workbook) and the ten that take `--marker`
        get them here, from the same config the stage itself will read.

        The marker substitution is applied separately from the path ones and
        does NOT mark the argument as a path: `--marker {marker0}` becomes
        `--marker AF568`, and normpath on a bare word is a no-op today but
        would mangle a marker name containing a slash or a dot.
        """
        out_root = self._config_dict().get("out_root", "")
        subs = {"{out_root}": out_root,
                "{repo}": os.path.dirname(self.config_path),
                "{scripts}": self.scripts_dir}
        markers = self.markers()
        out = []
        for a in argv:
            a = SG.fill_markers(a, markers)
            hit = any(k in a for k in subs)
            for k, v in subs.items():
                a = a.replace(k, v)
            # normpath only on expanded paths: a plain argument such as "--n"
            # or "AF568" must reach the stage exactly as written.
            out.append(os.path.normpath(a) if hit else a)
        return out

    # ---- module loading ---------------------------------------------------

    def rebind(self, config_path):
        """Point every future stage at a different study."""
        self.config_path = os.path.abspath(config_path)
        os.environ["LS_CONFIG"] = self.config_path
        self._config_stamp = None
        self._forget()

    def _forget(self):
        """Drop the cached stage modules AND the config module they read.

        `ls_config` caches the parsed config and lives in `sys.modules`, which
        this class does not own. Clearing only `self._modules` would reload
        every stage and hand each one the config that was just replaced.
        """
        self._modules.clear()
        sys.modules.pop("ls_config", None)

    def _config_changed(self):
        """Whether the config file's CONTENT has changed since the last check.

        This was the modification time. Two edits inside one filesystem
        timestamp tick - which on a fast save is entirely possible - looked
        identical, so the cached stage modules were served with the previous
        config still baked into their constants. The file is a few kilobytes;
        hashing it costs nothing next to importing a stage.
        """
        try:
            with open(self.config_path, "rb") as fh:
                stamp = hashlib.sha256(fh.read()).hexdigest()
        except OSError:
            stamp = None
        if stamp != self._config_stamp:
            self._config_stamp = stamp
            return True
        return False

    def load(self, script):
        """Import a stage script by path, reusing it unless config moved.

        The module name is prefixed because `00_manifest` is not a legal
        identifier and would collide with nothing meaningful anyway; keeping the
        prefix makes tracebacks say which stage they came from.
        """
        if self._config_changed():
            self._forget()
        if script in self._modules:
            return self._modules[script]

        path = os.path.join(self.scripts_dir, script)
        if not os.path.exists(path):
            raise FileNotFoundError(f"stage script not found: {path}")

        name = "lsstage_" + os.path.splitext(script)[0]
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        # Registered before exec so a stage that imports itself, or that another
        # stage imports, resolves to the same object rather than loading twice.
        sys.modules[name] = mod
        # The stages import each other by relative path and some read files
        # beside themselves, so run them with scripts/ importable.
        added = self.scripts_dir not in sys.path
        if added:
            sys.path.insert(0, self.scripts_dir)
        try:
            spec.loader.exec_module(mod)
        finally:
            if added:
                try:
                    sys.path.remove(self.scripts_dir)
                except ValueError:
                    pass
        self._modules[script] = mod
        return mod

    # ---- running ----------------------------------------------------------

    def run(self, stage, on_line=None, extra_argv=()):
        """Run one stage to completion. Returns a StageResult; never raises.

        Serialised on a lock: the stages write to shared output directories and
        several of them rewrite the same index files, so two at once would be a
        race with the user's data on the losing side.
        """
        if stage.cli_only:
            return StageResult(stage.sid, False, 0.0, "",
                               f"{stage.title} is not run by the app: {stage.cli_only}")
        if not stage.script:
            return StageResult(stage.sid, False, 0.0, "",
                               f"{stage.title} has no script to run")

        argv = [stage.script] + self.expand_argv(list(stage.argv) + list(extra_argv))
        tee = _Tee(on_line)
        t0 = time.time()

        with self._lock:
            old_argv, old_cwd = sys.argv, os.getcwd()
            try:
                mod = self.load(stage.script)
                sys.argv = argv
                # Some stages resolve paths relative to the scripts directory,
                # which is where run_all.sh cds to before calling them.
                os.chdir(self.scripts_dir)
                with contextlib.redirect_stdout(tee), contextlib.redirect_stderr(tee):
                    if not hasattr(mod, "main"):
                        raise AttributeError(
                            f"{stage.script} has no main() - it cannot be run in-process")
                    mod.main()
                tee.flush()
                return StageResult(stage.sid, True, time.time() - t0, tee.text())

            except SystemExit as e:
                # argparse exits 0 for --help; a stage exits non-zero, or with a
                # message, to refuse work it cannot do. Both are outcomes, not
                # crashes, and the message is the useful part.
                tee.flush()
                code = e.code
                if code in (0, None):
                    return StageResult(stage.sid, True, time.time() - t0, tee.text())
                msg = code if isinstance(code, str) else f"stage exited with status {code}"
                return StageResult(stage.sid, False, time.time() - t0, tee.text(), msg)

            except BaseException as e:                      # noqa: BLE001
                tee.flush()
                detail = "".join(traceback.format_exception(type(e), e, e.__traceback__))
                return StageResult(stage.sid, False, time.time() - t0,
                                   tee.text(), f"{type(e).__name__}: {e}\n\n{detail}")

            finally:
                sys.argv = old_argv
                try:
                    os.chdir(old_cwd)
                except OSError:
                    pass
