from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from material_ui.errors import InvalidInput


@dataclass(frozen=True)
class AppConfig:
    root: Path
    quarto: str = "quarto"
    preview_port: int = 8767
    qmd_cache_ttl: float = 15.0
    course_cache_ttl: float = 5.0
    claude_bin: str = "claude"
    codex_bin: str = "codex"
    vibe_bin: str = "vibe"
    mistral_admin_api_key: str = ""
    codex_model: str = "gpt-6.1-sol"
    # Auswahlliste der Modelle im Chat (Aliase bzw. Modellnamen der CLI); leer = keine Wahl.
    claude_models: tuple[str, ...] = ("sonnet", "opus", "haiku")
    codex_models: tuple[str, ...] = ()
    # Denkaufwand (--effort) der Claude-CLI: low, medium, high, xhigh oder max.
    claude_effort: str = "medium"
    # Codex/Vibe haben nicht abschaltbare Datei-Werkzeuge und laufen nur in einer
    # bwrap-Sandbox; True erlaubt sie bewusst auch ohne bwrap (unsicher).
    chat_allow_unsandboxed: bool = False

    def __post_init__(self):
        object.__setattr__(self, "root", self.root.resolve())

    def safe_path(self, value: str) -> Path:
        if not value:
            raise InvalidInput("Pfad fehlt.")
        candidate = (self.root / value).resolve()
        if not candidate.is_relative_to(self.root):
            raise InvalidInput("Pfad liegt ausserhalb des Projekts.")
        if candidate.is_relative_to(self.root / "foerderempfehlungen"):
            raise InvalidInput("Personenbezogener Bereich ist im Materialeditor gesperrt.")
        return candidate

    def safe_visible_path(self, value: str) -> Path:
        path = self.safe_path(value)
        if not self.is_visible(path):
            raise InvalidInput("Versteckte Pfade sind nicht erlaubt.")
        return path

    def is_visible(self, path: Path) -> bool:
        path = path.resolve()
        return (path.is_relative_to(self.root)
                and not path.is_relative_to(self.root / "foerderempfehlungen")
                and not any(part.startswith(".") for part in path.relative_to(self.root).parts))

    def relative(self, path: Path | None) -> str | None:
        return path.resolve().relative_to(self.root).as_posix() if path else None
