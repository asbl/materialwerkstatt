from datetime import date

from material_core.state import shared_file
from material_ui.plugins.erinnerungen.reminders import ReminderNotifier
from material_ui.plugins.storage import PluginStorage


def test_local_file_moves_to_shared_folder_once(tmp_path):
    legacy = tmp_path / ".material-ui" / "tag-settings.json"
    legacy.parent.mkdir()
    legacy.write_text('{"rootTags": ["a"]}')

    target = shared_file(tmp_path, "tag-settings.json")

    assert target == tmp_path / "daten" / "tag-settings.json"
    assert target.read_text() == '{"rootTags": ["a"]}'
    assert not legacy.exists()


def test_synced_file_wins_over_stale_local_copy(tmp_path):
    storage = PluginStorage(tmp_path / "lokal", tmp_path / "gemeinsam")
    storage.write_json(storage.path("plan.json"), {"alt": True})
    storage.write_json(tmp_path / "gemeinsam" / "plan.json", {"neu": True})

    assert storage.read_json(storage.shared_path("plan.json")) == {"neu": True}
    assert storage.read_json(storage.path("plan.json")) == {"alt": True}


def test_reminders_without_items_write_nothing(tmp_path):
    storage = PluginStorage(tmp_path / "lokal", tmp_path / "gemeinsam")

    ReminderNotifier(storage, notify=lambda *_: None).tick([], today=date(2026, 1, 5))

    assert not storage.shared_path("reminders.json").exists()
