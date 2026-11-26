from __future__ import annotations

from course_sync.classes.cli import (
    build_arg_parser as build_cli_arg_parser,
    print_course_status as print_cli_course_status,
    print_moodle_ping_report as print_cli_moodle_ping_report,
    run_cli_command,
    serve_preview as serve_preview_impl,
)


def run(application, argv: list[str] | None = None) -> None:
    parser = build_cli_arg_parser(application.DEFAULT_PORT)
    args = parser.parse_args(argv)
    run_cli_command(
        args,
        parser=parser,
        root_dir=application.ROOT_DIR,
        courses_dir=application.COURSES_DIR,
        sync_course=application.sync_course,
        build_preview_runtime=application.prepare_preview_runtime,
        serve_preview=lambda port: serve_preview_impl(
            port,
            courses_dir=application.COURSES_DIR,
            runtime_proxy_prefix=application.RUNTIME_PROXY_PREFIX,
            h5p_runtime_port=application.H5P_RUNTIME_PORT,
            ensure_h5p_runtime_server=application.ensure_h5p_runtime_server,
            load_course_preview_state=application.load_course_preview_state,
            preview_controller=application.preview_controller,
            resolve_runtime_question_from_path=application.resolve_runtime_question_from_path,
            ensure_runtime_question_ready=application.ensure_runtime_question_ready,
            rewrite_runtime_html=application.rewrite_runtime_html,
            escape_inline=application.escape_inline,
            start_runtime_question_preparation=application.start_runtime_question_preparation,
            rebuild_runtime_question=application.rebuild_runtime_question,
            prepare_preview_runtime=lambda: application.prepare_preview_runtime(),
            template_renderer=application.template_renderer,
        ),
        resolve_moodle_client=application.resolve_moodle_client,
        import_moodle_course=application.import_moodle_course,
        push_moodle_course=application.push_moodle_course,
        sync_metadata_path=application._SYNC_METADATA_STORE.path,
        build_moodle_ping_report=application.build_moodle_ping_report,
        print_moodle_ping_report=print_cli_moodle_ping_report,
        build_course_status=application.build_course_status,
        print_course_status=print_cli_course_status,
        export_chapter=application.export_chapter,
        upload_moodle_chapter=application.upload_moodle_chapter,
        upload_moodle_course=application.upload_moodle_course,
        audit_course=application.audit_course,
        verify_moodle_course=application.verify_moodle_course,
        update_h5p_libraries_from_github=application.update_h5p_libraries_from_github,
        update_h5p_libraries_from_local_export=application.update_h5p_libraries_from_local_export,
        import_moodle_from_mbz=application.import_moodle_from_mbz,
        export_static_site=application.export_static_site,
    )
