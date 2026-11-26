from __future__ import annotations

import threading
from pathlib import Path

from course_sync.application import CourseApplication
from course_sync.config import settings
from course_sync.classes.cli.runner import create_new_course, list_course_chapters, list_course_summaries
from course_sync.classes.moodle_playwright_uploader import read_chapter_question_order


class CourseAdapter:
    create_new_course = staticmethod(create_new_course)
    list_course_chapters = staticmethod(list_course_chapters)
    list_course_summaries = staticmethod(list_course_summaries)
    read_chapter_question_order = staticmethod(read_chapter_question_order)

    def __init__(self, root: Path, *, application=None, processes=None):
        self.root = root
        self._application = application
        self.processes = processes
        self.lock = threading.Lock()

    def application(self) -> CourseApplication:
        with self.lock:
            if self._application is None:
                self._application = CourseApplication(settings.build_app_config().with_root(self.root))
            return self._application

    def parse_course(self, course_dir: Path):
        return self.application().parse_course(course_dir)

    def sync_course(self, course_dir: Path):
        return self.application().sync_course(course_dir)

    def ensure_h5p_runtime_server(self):
        application = self.application()
        starter = self.processes.start if self.processes is not None else None
        return application.runtime_cli_service().ensure_h5p_runtime_server(application.H5P_RUNTIME_PORT, start_process=starter)
