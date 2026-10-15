import types
from unittest.mock import patch

from libs.events.loader import _load_item, load_events, load_listeners


class TestLoader:
    def test_load_item_with_string_imports_module(self):
        with patch("libs.events.loader.importlib.import_module") as mock_import:
            _load_item("some.package.events", "events")
            mock_import.assert_called_once_with("some.package.events")

    def test_load_item_with_module_walks_packages_and_imports_matching_filename(self):
        mock_package = types.ModuleType("my_pkg")
        mock_package.__path__ = ["/fake/path"]

        walk_results = [
            (None, "my_pkg.sub.events", False),
            (None, "my_pkg.sub.other", False),
            (None, "my_pkg.domain.events", False),
        ]

        with (
            patch("libs.events.loader.pkgutil.walk_packages", return_value=walk_results),
            patch("libs.events.loader.importlib.import_module") as mock_import,
        ):
            _load_item(mock_package, "events")

            assert mock_import.call_count == 2
            mock_import.assert_any_call("my_pkg.sub.events")
            mock_import.assert_any_call("my_pkg.domain.events")

    def test_load_listeners_calls_load_item_with_listeners(self):
        with patch("libs.events.loader._load_item") as mock_load_item:
            load_listeners("my.module")
            mock_load_item.assert_called_once_with("my.module", "listeners")

    def test_load_events_calls_load_item_with_events(self):
        with patch("libs.events.loader._load_item") as mock_load_item:
            load_events("my.module")
            mock_load_item.assert_called_once_with("my.module", "events")
