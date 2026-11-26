"""Reine Frontend-Module des Chat-Plugins (Markdown, Diff, Werkzeugergebnisse, Verlauf) in Node."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "material_ui" / "plugins" / "chat"
ASSETS = PLUGIN / "assets"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node.js ist nicht installiert")


def run_node(script: str, **modules: str) -> None:
    urls = {name: json.dumps((ASSETS / f"{name}.js").as_uri()) for name in modules}
    prelude = "".join(f"import * as {alias} from {urls[module]};\n" for module, alias in modules.items())
    result = subprocess.run([NODE, "--input-type=module", "-e", "import assert from 'node:assert/strict';\n" + prelude + script],
                            capture_output=True, text=True)
    if result.returncode:
        pytest.fail("Node-Skript fehlgeschlagen:\n" + "\n".join(line for line in result.stderr.splitlines() if not line.startswith("    at "))[:1500])


def test_manifest_lists_all_chat_modules():
    data = json.loads((PLUGIN / "plugin.json").read_text(encoding="utf-8"))
    listed = {data["jsEntry"], *data["modules"]}
    assert {f"assets/{path.name}" for path in ASSETS.glob("*.js")} == listed


def test_relative_imports_resolve_to_existing_exports():
    export = re.compile(r"^export\s+(?:async\s+)?(?:function|const|let)\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
    for path in ASSETS.glob("*.js"):
        for names, target in re.findall(r'^import\s*\{([^}]*)\}\s*from\s*"(\./[^"]+)";', path.read_text(encoding="utf-8"), re.MULTILINE):
            module = ASSETS / target[2:]
            assert module.is_file(), f"{path.name}: {target} fehlt"
            wanted = {name.strip() for name in names.split(",") if name.strip()}
            assert wanted <= set(export.findall(module.read_text(encoding="utf-8"))), f"{path.name}: {sorted(wanted)}"


# -- Markdown -------------------------------------------------------------------------------------


@needs_node
def test_markdown_blocks_and_inline():
    run_node('''
const kinds = (text) => md.parseMarkdown(text).map((block) => block.type);
assert.deepEqual(kinds("# Titel\\n\\nAbsatz\\nzweite Zeile\\n\\n- a\\n- b\\n\\n1. x\\n2. y\\n\\n> Zitat\\n\\n---\\n\\n```py\\nprint(1)\\n```"),
  ["heading", "paragraph", "list", "list", "quote", "rule", "code"]);
const list = md.parseMarkdown("3. drei\\n4. vier")[0];
assert.equal(list.ordered, true); assert.equal(list.start, 3); assert.equal(list.items.length, 2);
const inline = md.parseInline("**fett** *kursiv* `x*y` [Doku](https://example.org/a)");
assert.deepEqual(inline.filter((n) => n.type !== "text").map((n) => n.type), ["strong", "em", "code", "link"]);
assert.equal(inline.find((n) => n.type === "code").text, "x*y");
''', markdown="md")


@needs_node
def test_markdown_keeps_math_and_identifiers_and_rejects_unsafe_links():
    run_node('''
const plain = (text) => md.parseInline(text).map((n) => n.type);
assert.deepEqual(plain("2*3*4 = 24"), ["text"]);
assert.deepEqual(plain("snake_case_name und a_b"), ["text"]);
assert.deepEqual(plain("[x](javascript:alert(1))"), ["text"]);
assert.deepEqual(plain("[x](data:text/html,<b>)"), ["text"]);
assert.deepEqual(plain("[x](https://example.org)"), ["link"]);
assert.equal(md.isSafeUrl("http://example.org"), true);
assert.equal(md.isSafeUrl("ftp://example.org"), false);
assert.equal(md.isSafeUrl("https://example.org/\\"onclick=1"), false);
assert.equal(md.parseInline("\\\\*roh\\\\*")[0].text, "*roh*");
''', markdown="md")


@needs_node
def test_markdown_never_produces_html_and_handles_unfinished_input():
    run_node('''
const blocks = md.parseMarkdown("<script>alert(1)</script> und <img src=x onerror=alert(1)>");
assert.equal(blocks.length, 1); assert.equal(blocks[0].type, "paragraph");
assert.equal(blocks[0].children[0].type, "text");
assert.ok(blocks[0].children[0].text.includes("<script>"));  // bleibt Text
const open = md.parseMarkdown("```js\\nlet a = 1;\\n\\nnoch offen");
assert.equal(open.length, 1); assert.equal(open[0].text, "let a = 1;\\n\\nnoch offen");
for (const text of ["", null, undefined, "**", "`", "[", "[a](", "- ", "1. ", "```", "> ", "#"]) md.parseMarkdown(text);
const big = "- punkt\\n".repeat(5000); assert.equal(md.parseMarkdown(big)[0].items.length, 5000);
''', markdown="md")


# -- Diff -----------------------------------------------------------------------------------------


@needs_node
def test_line_diff_and_collapse():
    run_node('''
const show = (ops) => ops.map((o) => ({ctx: " ", add: "+", del: "-", skip: "~"}[o.type] + (o.text ?? o.count))).join("|");
assert.equal(show(d.lineDiff("a\\nb\\nc", "a\\nB\\nc")), " a|-b|+B| c");
assert.equal(show(d.lineDiff("a", "a")), " a");
assert.equal(show(d.lineDiff("", "neu")), "-|+neu");
assert.equal(show(d.lineDiff("a\\nb", "a\\nb\\nc")), " a| b|+c");
const long = Array.from({length: 20}, (_, i) => "z" + i).join("\\n");
const ops = d.lineDiff(long, long.replace("z10", "ZEHN"));
const folded = d.collapseContext(ops, 2);
assert.equal(show(folded), "~8| z8| z9|-z10|+ZEHN| z11| z12|~7");
assert.equal(d.collapseContext(d.lineDiff("a", "a"), 2).length, 1);
const huge = Array.from({length: 500}, (_, i) => "x" + i).join("\\n");
const replaced = d.lineDiff(huge, huge + "\\n" + "y".repeat(3) + Array.from({length: 450}, (_, i) => "n" + i).join("\\n"));
assert.ok(replaced.some((o) => o.type === "add"));
''', diff="d")


# -- Werkzeugergebnisse -------------------------------------------------------------------------------


@needs_node
def test_tool_names_labels_and_internal_tools():
    run_node('''
assert.equal(t.baseToolName("mcp__wissen__search_wissen"), "search_wissen");
assert.equal(t.baseToolName("mcp_wissen.read_file"), "read_file");
assert.equal(t.baseToolName("search_unterricht"), "search_unterricht");
assert.equal(t.toolLabel("mcp__wissen__search_wissen"), "Wissensbasis durchsuchen");
assert.equal(t.isBuiltinTool("shell"), true);
assert.equal(t.isBuiltinTool("file_system.bash"), true);
assert.equal(t.isBuiltinTool("mcp__wissen__read_file"), false);
assert.equal(t.toolLabel("shell"), "Shell (Sandbox)");
assert.equal(t.isInternalTool("search_tool_functions"), true);
assert.equal(t.isInternalTool("shell"), false);
''', **{"tool-results": "t"})


@needs_node
def test_tool_errors_are_detected_in_all_result_shapes():
    run_node('''
assert.equal(t.isToolError({ is_error: true, tool_output: "x" }), true);
assert.equal(t.isToolError({ tool_output: { content: [{ type: "text", text: "Error executing tool search_wissen: Kein Index" }] } }), true);
assert.equal(t.isToolError({ tool_output: "Fehler: nicht gefunden" }), true);
assert.equal(t.isToolError({ tool_output: [{ type: "text", text: "{\\"pfad\\": \\"a\\"}" }] }), false);
assert.equal(t.isToolError({ tool_output: null }), false);
assert.equal(t.toolOutputText({ content: [{ type: "text", text: "a" }, { type: "text", text: "b" }] }), "a\\nb");
assert.equal(t.toolOutputText(null), "");
''', **{"tool-results": "t"})


@needs_node
def test_search_hits_are_extracted_from_each_cli_shape():
    run_node('''
const wissen = { pfad: "informatik/curriculum/abitur.pdf", seite: 91, ausschnitt: "…Potenziale…" };
// Codex: Text-Inhalt mit einem JSON-Objekt je Treffer
let hits = t.extractHits("search_wissen", { content: [{ type: "text", text: JSON.stringify(wissen) }, { type: "text", text: JSON.stringify({ ...wissen, seite: 92 }) }] });
assert.equal(hits.length, 2); assert.equal(hits[0].path, "wissen/informatik/curriculum/abitur.pdf");
assert.equal(hits[0].page, 91); assert.equal(hits[0].openable, false);
// Vibe: pretty-printed Objekt als String; Claude: Liste
assert.equal(t.extractHits("mcp_wissen.search_wissen", JSON.stringify(wissen, null, 2)).length, 1);
assert.equal(t.extractHits("mcp__wissen__search_wissen", [{ type: "text", text: JSON.stringify([wissen, wissen]) }]).length, 2);
// Mehrere Objekte ohne Trenner und Klammern in Strings
const glued = '{"pfad":"a/b.pdf","ausschnitt":"} { kein Ende"}\\n{"pfad":"c/d.pdf"}';
assert.deepEqual(t.extractHits("search_wissen", glued).map((h) => h.path), ["wissen/a/b.pdf", "wissen/c/d.pdf"]);
// Unterrichtsmaterial ist oeffnbar, Fremdes nicht
const unterricht = t.extractHits("search_unterricht", JSON.stringify([
  { path: "unterricht/mathe/ab_potenzen.qmd", title: "Potenzen", snippet: "…" }, { path: "unterricht/mathe/bild.png" }, { path: "src/x.py" }]));
assert.deepEqual(unterricht.map((h) => h.openable), [true, false, false]);
assert.equal(unterricht[0].title, "Potenzen");
// andere Werkzeuge und Muell liefern nichts
assert.deepEqual(t.extractHits("shell", JSON.stringify(wissen)), []);
assert.deepEqual(t.extractHits("search_wissen", "kein json"), []);
assert.deepEqual(t.extractHits("search_wissen", null), []);
assert.equal(t.extractHits("search_wissen", JSON.stringify({ pfad: "x".repeat(10), ausschnitt: "y".repeat(1000) }))[0].snippet.length, 240);
''', **{"tool-results": "t"})


# -- Verlauf (mehrere Chats) ------------------------------------------------------------------------------


MEMORY = "const memory = () => { const data = new Map(); return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k), data }; };"


@needs_node
def test_threads_roundtrip_titles_and_active_chat():
    run_node(MEMORY + r"""
const store = memory();
assert.deepEqual(h.loadThreads(store), { activeId: null, threads: [] });
const a = h.createThread({ docPath: "unterricht/m/ab_x.qmd", sessionId: "s1", providerId: "claude", model: "opus",
  messages: [{ role: "user", text: "Hallo   Welt" }, { role: "assistant", text: "Hi" }] });
const b = h.createThread({ messages: [{ role: "user", text: "x".repeat(60) }] });
assert.equal(h.saveThreads({ activeId: b.id, threads: [a, b] }, store), true);
const loaded = h.loadThreads(store);
assert.equal(loaded.activeId, b.id); assert.equal(loaded.threads.length, 2);
const [la, lb] = loaded.threads;
assert.equal(la.title, "Hallo Welt · ab_x.qmd"); assert.equal(la.sessionId, "s1"); assert.equal(la.model, "opus");
assert.equal(lb.title, "x".repeat(40) + "…");
assert.equal(h.titleFor(h.createThread()), "Neuer Chat");
// ungueltige/unbekannte aktive ID faellt auf den ersten Chat zurueck
const raw = JSON.parse(store.getItem(h.THREADS_KEY)); raw.activeId = "gibt-es-nicht"; store.setItem(h.THREADS_KEY, JSON.stringify(raw));
assert.equal(h.loadThreads(store).activeId, a.id);
""", history="h")


@needs_node
def test_legacy_single_chat_is_migrated_once():
    run_node(MEMORY + r"""
const store = memory();
store.setItem(h.LEGACY_KEY, JSON.stringify({ sessionId: "s9", providerId: "claude", model: "", messages: [{ role: "user", text: "Alt" }, { role: "assistant", text: "Antwort" }] }));
const loaded = h.loadThreads(store);
assert.equal(loaded.threads.length, 1); assert.equal(loaded.threads[0].sessionId, "s9"); assert.equal(loaded.activeId, loaded.threads[0].id);
h.saveThreads(loaded, store);
assert.equal(store.getItem(h.LEGACY_KEY), null);  // altes Format ist abgeloest
assert.equal(h.loadThreads(store).threads.length, 1);
// leeres altes Format erzeugt nichts
const empty = memory(); empty.setItem(h.LEGACY_KEY, JSON.stringify({ messages: [] })); assert.deepEqual(h.loadThreads(empty), { activeId: null, threads: [] });
""", history="h")


@needs_node
def test_threads_are_validated_trimmed_and_pruned():
    run_node(MEMORY + r"""
const store = memory();
store.setItem(h.THREADS_KEY, JSON.stringify({ threads: [
  { id: "ok", messages: [{ role: "system", text: "x" }, { role: "user" }, { role: "user", text: "gut" }, null], sessionId: 5, docPath: 7 },
  { messages: [] }, null, "text" ], activeId: "ok" }));
const [only] = h.loadThreads(store).threads;
assert.deepEqual(only.messages, [{ role: "user", text: "gut" }]); assert.equal(only.sessionId, null); assert.equal(only.docPath, "");
store.setItem(h.THREADS_KEY, "{kaputt"); assert.deepEqual(h.loadThreads(store), { activeId: null, threads: [] });
// Anzahl: aelteste fallen weg, der aktive Chat nie
const many = Array.from({ length: 30 }, (_, i) => h.createThread({ updated: 1000 + i, messages: [{ role: "user", text: "m" + i }] }));
const oldest = many[0];
const kept = h.pruneThreads(many, oldest.id);
assert.equal(kept.length, h.MAX_THREADS);  // der aktive Chat zaehlt mit assert.ok(kept.includes(oldest)); assert.ok(kept.includes(many[29])); assert.ok(!kept.includes(many[1]));
// Gesamtgroesse
const big = Array.from({ length: 5 }, (_, i) => h.createThread({ updated: i, messages: [{ role: "user", text: "z".repeat(100_000) }] }));
const sized = h.pruneThreads(big, big[0].id);
assert.ok(sized.length <= 4 && sized.includes(big[0]));
// Nachrichten je Chat: Anzahl und Zeichen, neueste bleiben
const msgs = Array.from({ length: 200 }, (_, i) => ({ role: "user", text: String(i) }));
assert.equal(h.trimMessages(msgs).length, h.MAX_MESSAGES); assert.equal(h.trimMessages(msgs).at(-1).text, "199");
assert.deepEqual(h.trimMessages([{ role: "user", text: "alt" }, { role: "assistant", text: "x".repeat(h.MAX_CHARS - 5) }, { role: "user", text: "neu" }]).map((m) => m.text.length), [h.MAX_CHARS - 5, 3]);
""", history="h")


@needs_node
def test_threads_storage_failure_modes_and_cleanup():
    run_node(MEMORY + r"""
const store = memory();
// Nur ein leerer aktiver Chat: nichts speichern
const blank = h.createThread();
h.saveThreads({ activeId: blank.id, threads: [blank] }, store); assert.equal(store.data.size, 0);
const used = h.createThread({ sessionId: "s", messages: [] });
h.saveThreads({ activeId: used.id, threads: [used, blank] }, store);
assert.equal(JSON.parse(store.getItem(h.THREADS_KEY)).threads.length, 1);  // leere Nebenchats entfallen
h.clearAllThreads(store); assert.equal(store.data.size, 0);
const full = { getItem: () => null, setItem: () => { throw new Error("quota"); }, removeItem: () => {} };
assert.equal(h.saveThreads({ activeId: used.id, threads: [used] }, full), false);
const locked = { getItem: () => { throw new Error("gesperrt"); } };
assert.deepEqual(h.loadThreads(locked), { activeId: null, threads: [] });
""", history="h")


# -- Markdown: Tabellen und Formeln ------------------------------------------------------------------------


@needs_node
def test_markdown_tables_and_formulas():
    run_node(r"""
const [intro, table] = md.parseMarkdown("Text davor\n| a | b |\n|:--|--:|\n| 1 | **2** |\n| $x^2$ | z \\| q |\n");
assert.equal(intro.type, "paragraph"); assert.equal(table.type, "table");  // Tabelle beendet den Absatz
assert.deepEqual(table.align, ["left", "right"]); assert.equal(table.rows.length, 2);
assert.equal(table.rows[0][1][0].type, "strong"); assert.equal(table.rows[1][0][0].type, "math");
assert.equal(table.rows[1][1][0].text, "z | q");  // maskierter Strich
assert.equal(md.parseMarkdown("| a | b |\n| kein Trenner |")[0].type, "paragraph");
const blocks = md.parseMarkdown("$$\\frac{a}{b}$$\n\n$$\nx = 2\ny = 3\n$$\n\n\\[ a^2 \\]");
assert.deepEqual(blocks.map((b) => b.type), ["math", "math", "math"]); assert.equal(blocks[1].text, "x = 2\ny = 3");
const types = (text) => md.parseInline(text).map((n) => n.type);
assert.deepEqual(types("mit $a^2$ und \\(b\\)"), ["text", "math", "text", "math"]);
assert.deepEqual(types("5 $ und 6 $"), ["text"]);       // Geldbetraege sind keine Formel
assert.deepEqual(types("kostet $5 oder $6"), ["text"]);
assert.deepEqual(types("$ x $"), ["text"]);
assert.deepEqual(types("`$x$` bleibt Code"), ["code", "text"]);
md.parseMarkdown("$$\n\\frac{"); md.parseMarkdown("| |\n|-|"); md.parseMarkdown("$$");  // unvollstaendig: kein Fehler
""", markdown="md")


@needs_node
def test_tex_parsing_and_text_form():
    run_node(r"""
const text = (src) => t.texToText(t.parseTex(src));
assert.equal(text("a^{n+1} = a^n \\cdot a"), "a^n+1 = a^n · a");
assert.equal(text("\\frac{a^2+b^2}{2} \\le \\sqrt{x_1}"), "(a^2+b^2)/(2) ≤ √(x_1)");
assert.equal(text("10^{-3} \\times 5 \\neq \\pi"), "10^-3 × 5 ≠ π");
assert.equal(text("\\text{cm}^2"), "cm^2");
assert.equal(text("x \\unbekannt y"), "x \\unbekannt y");   // unbekannte Befehle bleiben sichtbar
assert.equal(text("\\left( a \\right)"), "( a )");
assert.deepEqual(t.parseTex("a^2")[1], { t: "sup", children: [{ t: "text", text: "2" }] });
assert.equal(t.parseTex("\\frac{1}{2}")[0].t, "frac");
// Robustheit: unvollstaendig, tief verschachtelt, sehr lang
for (const src of ["\\frac{", "{{{{", "^", "_{", "\\", "\\sqrt[3]", "}", "a^{b^{c^{d^{e^{f^{g^{h^{i^{j}}}}}}}}}", "x".repeat(10000)]) t.parseTex(src);
assert.ok(text("x".repeat(10000)).length <= 2000);
""", tex="t")


# -- Schnellaktionen ----------------------------------------------------------------------------------------


@needs_node
def test_quick_actions_by_document_kind():
    run_node(r"""
const titles = (path, custom = []) => q.actionsFor(path, custom).map((a) => a.title);
assert.equal(q.kindForPath("unterricht/m/ab_potenzen.qmd"), "worksheet");
assert.equal(q.kindForPath("unterricht/m/ab_mini_x.qmd"), "mini");
assert.equal(q.kindForPath("unterricht/m/slide.qmd"), "slide");
assert.equal(q.kindForPath("unterricht/m/01 slide.qmd"), "slide");
assert.equal(q.kindForPath("unterricht/m/ab_x_loesung.qmd"), "solution");
assert.equal(q.kindForPath("unterricht/m/notizen.md"), "other");
assert.equal(q.kindForPath(""), null);
assert.ok(titles("unterricht/m/ab_x.qmd").includes("Lösung erstellen"));
assert.ok(!titles("unterricht/m/slide.qmd").includes("Lösung erstellen"));
assert.ok(titles("unterricht/m/slide.qmd").includes("Folien sparsamer texten"));
assert.ok(titles("unterricht/m/ab_x_loesung.qmd").includes("Erklärungen ergänzen"));
assert.deepEqual(titles(""), []);  // ohne Dokument gibt es keine eingebauten Aktionen
// eigene Prompts: ohne Art ueberall, mit Art nur dort; ohne Dokument nur Prompts ohne Art
const custom = [{ title: "Immer", prompt: "p", kinds: [] }, { title: "Nur Folie", prompt: "p", kinds: ["slide"] }];
assert.deepEqual(titles("", custom), ["Immer"]);
assert.ok(titles("unterricht/m/slide.qmd", custom).includes("Nur Folie"));
assert.ok(!titles("unterricht/m/ab_x.qmd", custom).includes("Nur Folie"));
assert.ok(q.actionsFor("unterricht/m/ab_x.qmd", custom).find((a) => a.title === "Immer").custom);
// jeder eingebaute Prompt ist nicht leer und bezieht sich auf Projektwerkzeuge/-regeln
for (const action of q.BUILTIN_ACTIONS) { assert.ok(action.prompt.length > 20); assert.ok(action.kinds.every((k) => q.KINDS.includes(k))); }
""", **{"quick-actions": "q"})


@needs_node
def test_slash_filter_and_custom_prompt_format():
    run_node(r"""
const actions = [{ title: "Lösung erstellen" }, { title: "AFB kennzeichnen" }, { title: "Mini-AB daraus machen" }, { title: "Konventionen prüfen und beheben" }];
const names = (input) => q.filterSlash(input, actions).map((a) => a.title);
assert.equal(names("/").length, 4);                               // nur Schraegstrich: alles
assert.deepEqual(names("/afb"), ["AFB kennzeichnen"]);
assert.deepEqual(names("/mini"), ["Mini-AB daraus machen"]);
assert.deepEqual(names("/beh"), ["Konventionen prüfen und beheben"]);   // Wortanfang mitten im Titel
assert.deepEqual(names("/ung"), ["Lösung erstellen"]);               // Teilstring zuletzt
assert.deepEqual(names("/zzz"), []);
assert.deepEqual(names("kein slash"), []);
assert.deepEqual(names("/a\nb"), []);
const { prompts, errors } = q.parseCustomPrompts("# Kommentar\n\nKurz [slide, worksheet] | Kürze alles\nOhne Art | Etwas tun | mit weiterem Strich\nKaputt ohne Strich\n| ohne Titel\nFalsch [xyz] | p");
assert.deepEqual(prompts, [
  { title: "Kurz", prompt: "Kürze alles", kinds: ["slide", "worksheet"] },
  { title: "Ohne Art", prompt: "Etwas tun | mit weiterem Strich", kinds: [] }]);
assert.equal(errors.length, 3); assert.ok(errors[0].includes("Zeile 5"));
assert.deepEqual(q.parseCustomPrompts(q.formatCustomPrompts(prompts)).prompts, prompts);   // Rundlauf
""", **{"quick-actions": "q"})


@needs_node
def test_privacy_helpers_and_retry_prompt():
    run_node(r"""
assert.equal(q.operatorFor("claude"), "Anthropic"); assert.equal(q.operatorFor("codex"), "OpenAI");
assert.equal(q.operatorFor("mistral"), "Mistral AI"); assert.equal(q.operatorFor("unbekannt"), "unbekannt"); assert.equal(q.operatorFor(""), "dem Anbieter");
for (const path of ["unterricht/m/klasse-10/klausur-2026/ab.qmd", "unterricht/informatik/klausuren/e1/a.qmd", "unterricht/m/Klausur_a.qmd"]) assert.equal(q.isSensitivePath(path), true, path);
for (const path of ["unterricht/m/ab_klausurvorbereitung.qmd", "unterricht/m/ab.qmd", "", null]) assert.equal(q.isSensitivePath(path), false, String(path));
const prompt = q.retryPrompt({ old_text: "a".repeat(1000), new_text: "b".repeat(2000) });
assert.ok(prompt.includes("propose_document_edit") && prompt.includes("geändert"));
assert.ok(prompt.length < 1500);   // lange Texte werden gekuerzt
""", **{"quick-actions": "q"})


@needs_node
def test_source_links_for_knowledge_pdfs():
    run_node(r"""
const hits = t.extractHits("search_wissen", JSON.stringify([
  { pfad: "informatik/curriculum/abitur 2028.pdf", seite: 91, ausschnitt: "…" }, { pfad: "mathe/notizen.md" }]));
assert.equal(hits[0].sourceUrl, "/api/chat/source?path=wissen%2Finformatik%2Fcurriculum%2Fabitur%202028.pdf#page=91");
assert.equal(hits[1].sourceUrl, "");                                // nur PDFs bekommen einen Quellenlink
assert.equal(t.sourceUrl("wissen/a.pdf", null), "/api/chat/source?path=wissen%2Fa.pdf");
assert.equal(t.sourceUrl("wissen/a.pdf", 0), "/api/chat/source?path=wissen%2Fa.pdf");
assert.equal(t.toolLabel("mcp__wissen__check_document"), "Regeln prüfen");
assert.equal(t.toolLabel("mcp__wissen__propose_new_document"), "Neue Datei vorschlagen");
assert.equal(t.isBuiltinTool("mcp__wissen__read_unit"), false);
""", **{"tool-results": "t"})
