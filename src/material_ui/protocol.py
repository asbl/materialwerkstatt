"""Gemeinsamer Vertrag für Material-UI und Präsentationsansicht."""
import json
from pathlib import Path

CONTRACT = json.loads((Path(__file__).parent / 'static/api-contract.json').read_text(encoding='utf-8'))
API_VERSION = CONTRACT['apiVersion']
CAPABILITIES = tuple(CONTRACT['capabilities'])
