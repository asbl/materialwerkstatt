"""Invoke entry point; task implementations live in src/project_tasks.py and
src/course_sync_tasks.py (course-sync tasks, namespaced under `kurse.*`)."""

from __future__ import annotations

import sys
from pathlib import Path

from invoke import Collection

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / "src"))

from material_core import workspace as _workspace

try:
    _workspace.activate()
except _workspace.WorkspaceError as _error:
    raise SystemExit(str(_error)) from None

import project_tasks as _project_tasks
import course_sync_tasks as _course_sync_tasks

namespace = Collection.from_module(_project_tasks)
namespace.add_collection(Collection.from_module(_course_sync_tasks), name="kurse")

import lernstand_tasks as _lernstand_tasks
namespace.add_collection(Collection.from_module(_lernstand_tasks), name="lernstand")

# Optional packages own their Invoke tasks. The tools repository has no dependency
# on an individual plugin; uninstalling one simply removes its task namespace.
from importlib.metadata import entry_points
import warnings

for _extension in entry_points(group="material_ui.tasks"):
    try:
        namespace.add_collection(_extension.load()(ROOT_DIR), name=_extension.name)
    except Exception as _error:
        warnings.warn(f"Plugin-Tasks {_extension.name} konnten nicht geladen werden: {_error}", RuntimeWarning)
