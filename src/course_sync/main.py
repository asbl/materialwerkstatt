from __future__ import annotations

import sys
from types import ModuleType

from course_sync import application as _application
from course_sync.application import CourseApplication, get_application
from course_sync.classes.models import CourseActivity, PythonQuestionBlock
from course_sync.cli import run


def main() -> None:
    from material_core import workspace

    try:
        workspace.activate()
    except workspace.WorkspaceError as error:
        raise SystemExit(str(error)) from None
    run(get_application())


class _CompatibilityModule(ModuleType):
    def __getattr__(self, name):
        application = get_application()
        try:
            return getattr(application, name)
        except AttributeError:
            return getattr(_application, name)

    def __setattr__(self, name, value):
        application = get_application()
        if hasattr(application, name):
            setattr(application, name, value)
        else:
            super().__setattr__(name, value)


if __name__ == "__main__":
    main()
else:
    sys.modules[__name__].__class__ = _CompatibilityModule
