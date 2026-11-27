"""Shared source discovery and bounded text cache for navigation and search."""
from collections import OrderedDict
from pathlib import Path
import os
import threading
import time

from material_core.metadata import read_metadata_fast

HEAD_LIMIT = 16 * 1024


def fingerprint(path):
    stat = path.stat()
    return stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size, stat.st_ino


class SourceCatalog:
    def __init__(self, config, max_bytes=64 * 1024 * 1024, max_heads=8192, max_metas=8192):
        self.config = config
        self.lock = threading.RLock()
        self.directories = {}
        self.paths = {".qmd": (), ".md": (), ".excalidraw": ()}
        self.expires = 0.0
        self.generation = 0
        self.texts = OrderedDict()
        self.bytes = 0
        self.max_bytes = max_bytes
        self.heads = OrderedDict()
        self.max_heads = max_heads
        self.metas = OrderedDict()
        self.max_metas = max_metas

    def sources(self, suffix):
        _, (paths,) = self.snapshot(suffix)
        return paths

    def snapshot(self, *suffixes):
        """Dateilisten und Generation nach demselben Verzeichnisabgleich."""
        with self.lock:
            changed = time.monotonic() >= self.expires
            if not changed:
                try:
                    changed = any(fingerprint(path) != stamp for path, stamp in self.directories.items())
                except OSError:
                    changed = True
            if changed:
                self._scan()
            return self.generation, tuple(list(self.paths[suffix]) for suffix in suffixes)

    def _scan(self):
        paths = {".qmd": [], ".md": [], ".excalidraw": []}
        directories = {}
        root = self.config.root
        for directory, children, filenames in os.walk(root):
            parent = Path(directory)
            # Record before listing descendants; concurrent changes cause another scan.
            try:
                directories[parent] = fingerprint(parent)
            except OSError:
                continue
            excluded = {"node_modules", "build", "h5p", "libraries"}
            if parent == root:
                # _eingang/ressourcen/wissen sind getrennte Pipelines/Repos (siehe CLAUDE.md)
                # ohne Notiz-Dateien, aber zusammen zig GB gross: ohne diesen Ausschluss
                # durchlaeuft jeder Katalog-Rescan sie unnoetig komplett mit.
                excluded.update({"archiv", "foerderempfehlungen", "_eingang", "ressourcen", "wissen"})
            children[:] = [name for name in children if not name.startswith(".") and name not in excluded
                           and self.scan_result_visible(parent / name)]
            for name in filenames:
                if name.startswith((".", "material-ui-render-")):
                    continue
                path = parent / name
                if path.suffix in paths and not (path.suffix == ".qmd" and name.endswith("-old.qmd")):
                    paths[path.suffix].append(path)
        new_paths = {suffix: tuple(sorted(items)) for suffix, items in paths.items()}
        # Generation nur bei tatsaechlicher Aenderung der Dateiliste erhoehen, nicht bei
        # jeder TTL-getriebenen Reconciliation ohne Befund: sonst erzwingt eine reine
        # Ablauf-Rueckkehr (z. B. nach einer Weile auf einer anderen Ansicht) stromabwaerts
        # (discover_sources, UnitService._stamped) eine volle Neuklassifizierung aller
        # Quellen, obwohl sich nichts geaendert hat.
        changed = new_paths != self.paths
        self.paths = new_paths
        self.directories = directories
        if changed:
            self.generation += 1
        self.expires = time.monotonic() + self.config.qmd_cache_ttl
        live = set().union(*self.paths.values())
        for path in list(self.texts):
            if path not in live:
                self._discard(path)
        for path in list(self.heads):
            if path not in live:
                self.heads.pop(path, None)
        for path in list(self.metas):
            if path not in live:
                self.metas.pop(path, None)

    def scan_result_visible(self, path):
        """Cheap visibility re-check for a path reached via `_scan()`'s os.walk.

        os.walk (followlinks=False) never recurses into a symlinked directory, so every
        directory on the way to `path` is already a canonical path free of escapes; only
        `path` itself can still be a symlink pointing outside the root (e.g. into
        foerderempfehlungen/). Callers that hold a path discovered through `sources()`
        (directly, or via a sibling file in an already-walked directory) can use this
        instead of `config.is_visible()` to skip its resolve() for the common non-symlink
        case. Not valid for arbitrary/untrusted paths that did not come from this scan.
        """
        if not path.is_symlink():
            return True
        return self.config.is_visible(path)

    def changed(self, path=None):
        with self.lock:
            if path is None:
                self.expires = 0.0
                return
            self._discard(path)
            # Known edits do not change discovery. Creation/deletion/rename does.
            known = path in self.paths.get(path.suffix, ())
            if known != path.is_file():
                self.expires = 0.0
            elif known and path.parent in self.directories:
                # Atomic replacement changes the directory stamp as well as the file.
                # Our explicit edit is already accounted for; periodic reconciliation
                # still catches unrelated concurrent external changes.
                self.directories[path.parent] = fingerprint(path.parent)

    def _discard(self, path):
        previous = self.texts.pop(path, None)
        if previous is not None:
            self.bytes -= previous[2]
        self.heads.pop(path, None)
        self.metas.pop(path, None)

    def read_head(self, path, limit=HEAD_LIMIT):
        """Nur der Dateianfang (Frontmatter liegt vorn), fingerprint-geprueft gecached.

        Spart das Einlesen und Parsen des Volltexts, wenn bereits der Kopf zeigt,
        dass die Datei keine Notiz sein kann. Dekodiert mit "replace", damit ein
        Mehrbytezeichen an der Schnittkante nicht fehlschlaegt; U+FFFD im Kopf
        veranlasst den Aufrufer zum vollstaendigen Lesen (Lesefehler bleiben so
        als Warning erhalten).
        """
        path = self.config.safe_visible_path(str(path))
        with self.lock:
            stamp = fingerprint(path)
            cached = self.heads.get(path)
            if cached and cached[0] == stamp and cached[2] == limit:
                self.heads.move_to_end(path)
                return cached[1]
            with path.open("rb") as handle:
                head = handle.read(limit).decode("utf-8", "replace")
            if fingerprint(path) != stamp:
                raise ValueError("Datei wurde während der Indexierung geändert.")
            self.heads[path] = (stamp, head, limit)
            while len(self.heads) > self.max_heads:
                self.heads.popitem(last=False)
            return head

    def metadata(self, path):
        """Geparster Frontmatter als Mapping, pro Datei-Fingerprint gecached."""
        path = self.config.safe_visible_path(str(path))
        with self.lock:
            stamp = fingerprint(path)
            cached = self.metas.get(path)
            if cached and cached[0] == stamp:
                self.metas.move_to_end(path)
                return cached[1]
            text = self.read_text(path)
            metadata = read_metadata_fast(text)
            if fingerprint(path) != stamp:
                raise ValueError("Datei wurde während der Indexierung geändert.")
            self.metas[path] = (stamp, metadata)
            while len(self.metas) > self.max_metas:
                self.metas.popitem(last=False)
            return metadata

    def read_text(self, path):
        path = self.config.safe_visible_path(str(path))
        with self.lock:
            stamp = fingerprint(path)
            cached = self.texts.get(path)
            if cached and cached[0] == stamp:
                self.texts.move_to_end(path)
                return cached[1]
            text = path.read_text(encoding="utf-8")
            if fingerprint(path) != stamp:
                raise ValueError("Datei wurde während der Indexierung geändert.")
            self._discard(path)
            size = len(text.encode("utf-8"))
            if size <= self.max_bytes:
                self.texts[path] = (stamp, text, size)
                self.bytes += size
                while self.bytes > self.max_bytes:
                    self._discard(next(iter(self.texts)))
            return text
