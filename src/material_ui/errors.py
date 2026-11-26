from __future__ import annotations


class InvalidInput(ValueError):
    """Ungueltige Client-Eingabe; der HTTP-Adapter meldet sie als 400."""


class PluginConflict(Exception):
    """Abhängigkeitskonflikt (Zyklus, unlösbare Version, Deinstallations-Schutz); HTTP 409."""


class MarketplaceUnavailable(Exception):
    """Katalog nicht erreichbar; der HTTP-Adapter meldet sie als 502."""
