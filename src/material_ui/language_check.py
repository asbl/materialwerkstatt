"""Optional local LanguageTool integration; never sends documents to a public service."""
import os
import re
from urllib.parse import urlsplit

import httpx

from material_ui.errors import InvalidInput


def check_language(text):
    endpoint = os.environ.get("MATERIAL_LANGUAGETOOL_URL", "").rstrip("/")
    if not endpoint:
        return {"issues": [], "status": "Grammatik: lokales LanguageTool nicht eingerichtet"}
    url = urlsplit(endpoint)
    if url.scheme != "http" or url.hostname not in {"localhost", "127.0.0.1", "::1"} or url.username or url.password or url.query or url.fragment:
        raise InvalidInput("LanguageTool benötigt eine lokale HTTP-Adresse (localhost).")
    # Preserve offsets while excluding frontmatter, code, URLs and HTML comments.
    pattern = r"\A---\r?\n.*?\r?\n---(?:\r?\n|$)|```[^\n]*\n.*?(?:```|\Z)|~~~[^\n]*\n.*?(?:~~~|\Z)|`[^`\n]+`|<!--.*?(?:-->|\Z)|https?://[^\s)]+"
    prose = re.sub(pattern, lambda m: ''.join('\n' if c == '\n' else ' ' * (2 if ord(c) > 0xffff else 1) for c in m[0]), text, flags=re.S)
    try:
        response = httpx.post(endpoint + "/v2/check", data={"text": prose, "language": "de-DE"}, timeout=4, trust_env=False)
        response.raise_for_status()
        matches = response.json()["matches"]
        issues = []
        # LanguageTool offsets use UTF-16 code units, matching browser strings.
        encoded = text.encode('utf-16-le')
        for match in matches:
            start = len(encoded[:match['offset'] * 2].decode('utf-16-le', errors='ignore'))
            end = len(encoded[:(match['offset'] + match['length']) * 2].decode('utf-16-le', errors='ignore'))
            line = text.count('\n', 0, start) + 1
            column = start - text.rfind('\n', 0, start)
            replacements = ', '.join(item['value'] for item in match.get('replacements', [])[:4])
            issues.append({"level": "info", "code": "language-" + match.get('rule', {}).get('id', 'hint'),
                           "title": "Sprachprüfung", "detail": match['message'] + (" Vorschläge: " + replacements if replacements else ''),
                           "line": line, "column": column, "length": max(1, end - start)})
        return {"issues": issues, "status": "Grammatik und Rechtschreibung: lokales LanguageTool"}
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {"issues": [], "status": "Grammatik: lokales LanguageTool nicht erreichbar oder ungültige Antwort"}
