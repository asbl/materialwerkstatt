import { RangeSet, StateEffect, StateField } from "@codemirror/state";
import { Decoration, EditorView, GutterMarker, gutter } from "@codemirror/view";

export const diagnosticsEffect = StateEffect.define();

class DiagnosticMarker extends GutterMarker {
  constructor(level, message) {
    super();
    this.level = level;
    this.message = message;
  }
  eq(other) { return this.level === other.level && this.message === other.message; }
  toDOM() {
    const marker = document.createElement("span");
    marker.className = `material-diagnostic-marker material-diagnostic-${this.level}`;
    marker.textContent = "●";
    marker.title = this.message;
    marker.setAttribute("aria-label", this.message);
    return marker;
  }
}

export const diagnosticsField = StateField.define({
  create: () => ({ marks: Decoration.none, markers: RangeSet.empty }),
  update(value, transaction) {
    if (transaction.docChanged) value = { marks: Decoration.none, markers: RangeSet.empty };
    for (const effect of transaction.effects) {
      if (!effect.is(diagnosticsEffect)) continue;
      const marks = [];
      const lines = new Map();
      for (const issue of effect.value) {
        if (!issue.line || issue.level === "ok") continue;
        const line = transaction.state.doc.line(Math.max(1, Math.min(transaction.state.doc.lines, issue.line)));
        const message = `${issue.title}: ${issue.detail}`;
        // Server columns count Unicode code points; CodeMirror uses UTF-16 offsets.
        const start = [...line.text].slice(0, Math.max(0, (issue.column || 1) - 1)).join("").length;
        const length = [...line.text].slice(Math.max(0, (issue.column || 1) - 1), Math.max(0, (issue.column || 1) - 1) + (issue.length || 1)).join("").length;
        const from = line.from + Math.min(start, line.length);
        const to = Math.min(line.to, from + Math.max(1, length));
        const spec = { class: `cm-material-diagnostic cm-material-diagnostic-${issue.level}`, attributes: { title: message } };
        marks.push(from < to ? Decoration.mark(spec).range(from, to) : Decoration.line(spec).range(line.from));
        const existing = lines.get(line.from);
        const rank = { error: 3, warning: 2, info: 1 };
        const level = (rank[existing?.level] || 0) > (rank[issue.level] || 0) ? existing.level : issue.level;
        lines.set(line.from, { level, message: [existing?.message, message].filter(Boolean).join("\n") });
      }
      value = {
        marks: Decoration.set(marks, true),
        markers: RangeSet.of([...lines].map(([from, item]) => new DiagnosticMarker(item.level, item.message).range(from)), true)
      };
    }
    return value;
  },
  provide: field => [
    EditorView.decorations.from(field, value => value.marks),
    gutter({ class: "material-diagnostics-gutter", markers: view => view.state.field(field).markers })
  ]
});
