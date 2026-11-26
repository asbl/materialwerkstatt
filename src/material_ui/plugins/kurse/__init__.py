"""Kurs-Plugin: H5P-Kurse bearbeiten, auditieren, Moodle-Aktionen und Vorschau.

Die Endpunkte bleiben unter /api/kurse/… stabil; der Kern kennt keine Kurslogik
mehr. Kurs-Einträge speist das Plugin über ctx.index in /api/qmds ein.
"""

from __future__ import annotations


def register(ctx) -> None:
    # Kanonische Imports, damit CLI/Host und Plugin dieselben Modulinstanzen nutzen.
    from material_ui.plugins.kurse.adapter import CourseAdapter
    from material_ui.plugins.kurse.service import CourseService
    from material_ui.plugins.kurse.preview import PreviewService
    from material_ui.plugins.kurse.routes import register_routes

    documents = ctx.documents
    adapter = CourseAdapter(ctx.config.root, application=ctx.course_application,
                            processes=ctx.processes)
    service = CourseService(ctx.config, ctx.documents, ctx.jobs,
                            ctx.processes.run, ctx.workers.start_worker, adapter)
    preview = PreviewService(ctx.config, ctx.processes, service.course_sync_env,
                             ctx.workers.start_worker, adapter.ensure_h5p_runtime_server)

    ctx.service = service
    ctx.preview = preview

    # Kurs-Einträge in den Dokumentenindex; Invalidierung bei Ordneraktionen.
    ctx.index.register(service.entries, service.invalidate_kurs_cache)

    register_routes(ctx, service, preview, documents)

    # H5P-Runtime beim Serverstart vorwärmen (früher services().preview.prewarm()).
    ctx.lifecycle.on_start(preview.prewarm)

    def close():
        service.close()
        preview.close()

    ctx.lifecycle.on_shutdown(close)
