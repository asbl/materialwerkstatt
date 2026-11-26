from types import SimpleNamespace

from invoke.parser import Parser, ParserContext

import course_sync_tasks


def test_publish_passes_negative_backup_option_and_other_flags(monkeypatch):
    context = ParserContext(name="publish", args=course_sync_tasks.publish.get_arguments())
    parsed = Parser(contexts=[context]).parse_argv([
        "publish", "--course", "oop-example", "--target", "example",
        "--headless", "--skip-tests", "--no-verify-mbz-sync",
    ])[0].as_kwargs
    assert parsed["verify_mbz_sync"] is False
    assert parsed["headless"] is True
    assert parsed["skip_tests"] is True
    commands = []
    monkeypatch.setattr(course_sync_tasks, "_run_python", lambda ctx, *args, **kwargs: commands.append(args))
    monkeypatch.setattr(course_sync_tasks, "test", lambda ctx: (_ for _ in ()).throw(AssertionError("Tests were already run")))
    course_sync_tasks.publish.body(SimpleNamespace(), **parsed)
    assert len(commands) == 1
    assert "--verify-mbz-sync" not in commands[0]
    assert "--headless" in commands[0]


def test_publish_preserves_backup_check_by_default(monkeypatch):
    context = ParserContext(name="publish", args=course_sync_tasks.publish.get_arguments())
    parsed = Parser(contexts=[context]).parse_argv(["publish", "--skip-tests"])[0].as_kwargs
    commands = []
    monkeypatch.setattr(course_sync_tasks, "_run_python", lambda ctx, *args, **kwargs: commands.append(args))
    course_sync_tasks.publish.body(SimpleNamespace(), **parsed)
    assert "--verify-mbz-sync" in commands[0]
