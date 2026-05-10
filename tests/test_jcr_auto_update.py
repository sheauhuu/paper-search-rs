from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_search_mcp import config as config_module  # noqa: E402
from paper_search_mcp.config import Config  # noqa: E402
from paper_search_mcp.jcr import updater  # noqa: E402
from paper_search_mcp.jcr.models import JcrEntry, JcrIndex  # noqa: E402
from paper_search_mcp.tools import paper_search as paper_search_module  # noqa: E402


def _write_version(data_dir: Path, *, days_ago: int, remote_ref: str = "local") -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (datetime.now() - timedelta(days=days_ago)).isoformat()
    (data_dir / "version.json").write_text(
        json.dumps(
            {
                "last_update": timestamp,
                "last_check": timestamp,
                "remote_ref": remote_ref,
            }
        ),
        encoding="utf-8",
    )


def _make_jcr_data(data_dir: Path) -> Path:
    csv_dir = data_dir / "repo" / "中科院分区表及JCR原始数据文件"
    csv_dir.mkdir(parents=True, exist_ok=True)
    (csv_dir / "JCR2024UTF8.csv").write_text(
        "Journal,ISSN,IF(2024),IF Quartile,IF Rank,Category\n"
        "Nature,0028-0836,64.8,Q1,1/326,MULTIDISCIPLINARY SCIENCES\n",
        encoding="utf-8",
    )
    return csv_dir


class JcrAutoUpdateTests(unittest.TestCase):
    def test_config_defaults_runtime_auto_update_to_seven_days(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                config = Config()

        self.assertEqual(config.jcr["auto_update_days"], 7)

    def test_config_auto_update_days_zero_disables_runtime_updates(self) -> None:
        with patch.dict(os.environ, {"PAPER_SEARCH_JCR_AUTO_UPDATE_DAYS": "0"}, clear=True):
            with patch.object(config_module, "_find_legacy_config_files", return_value=[]):
                config = Config()

        self.assertEqual(config.jcr["auto_update_days"], 0)

    def test_missing_data_triggers_runtime_update_when_enabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            with patch.object(updater, "update_jcr_data", return_value=data_dir):
                changed = updater.ensure_jcr_data_current(
                    config_dir=temp_dir,
                    auto_update_days=7,
                )

        self.assertTrue(changed)

    def test_missing_data_does_not_update_when_disabled(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with patch.object(updater, "update_jcr_data") as update_jcr_data:
                changed = updater.ensure_jcr_data_current(
                    config_dir=temp_dir,
                    auto_update_days=0,
                )

        self.assertFalse(changed)
        update_jcr_data.assert_not_called()

    def test_recent_check_skips_remote_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _make_jcr_data(data_dir)
            _write_version(data_dir, days_ago=1, remote_ref="same")

            with patch.object(updater, "get_remote_ref") as get_remote_ref:
                changed = updater.ensure_jcr_data_current(
                    config_dir=temp_dir,
                    auto_update_days=7,
                )

        self.assertFalse(changed)
        get_remote_ref.assert_not_called()

    def test_elapsed_check_with_same_remote_ref_only_touches_last_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _make_jcr_data(data_dir)
            _write_version(data_dir, days_ago=9, remote_ref="same")

            with patch.object(updater, "get_remote_ref", return_value="same"):
                with patch.object(updater, "update_jcr_data") as update_jcr_data:
                    changed = updater.ensure_jcr_data_current(
                        config_dir=temp_dir,
                        auto_update_days=7,
                    )

            info = json.loads((data_dir / "version.json").read_text(encoding="utf-8"))

        self.assertFalse(changed)
        update_jcr_data.assert_not_called()
        self.assertEqual(info["remote_ref"], "same")
        self.assertGreater(datetime.fromisoformat(info["last_check"]), datetime.now() - timedelta(days=1))

    def test_elapsed_check_with_changed_remote_ref_updates(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _make_jcr_data(data_dir)
            _write_version(data_dir, days_ago=9, remote_ref="old")

            with patch.object(updater, "get_remote_ref", return_value="new"):
                with patch.object(updater, "update_jcr_data", return_value=data_dir) as update_jcr_data:
                    with patch.object(updater, "get_checked_out_ref", return_value="new"):
                        changed = updater.ensure_jcr_data_current(
                            config_dir=temp_dir,
                            auto_update_days=7,
                        )

            info = json.loads((data_dir / "version.json").read_text(encoding="utf-8"))

        self.assertTrue(changed)
        update_jcr_data.assert_called_once_with(temp_dir)
        self.assertEqual(info["remote_ref"], "new")

    def test_failed_remote_check_updates_last_check_to_throttle_retries(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _make_jcr_data(data_dir)
            _write_version(data_dir, days_ago=9, remote_ref="old")

            with patch.object(updater, "get_remote_ref", side_effect=RuntimeError("network down")):
                changed = updater.ensure_jcr_data_current(
                    config_dir=temp_dir,
                    auto_update_days=7,
                )

            info = json.loads((data_dir / "version.json").read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertGreater(datetime.fromisoformat(info["last_check"]), datetime.now() - timedelta(days=1))

    def test_local_revision_failure_does_not_abort_runtime_check(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            _make_jcr_data(data_dir)
            _write_version(data_dir, days_ago=9, remote_ref="")

            with patch.object(updater, "get_remote_ref", return_value="new"):
                with patch.object(updater, "get_local_remote_ref", side_effect=RuntimeError("bad repo")):
                    with patch.object(updater, "update_jcr_data") as update_jcr_data:
                        changed = updater.ensure_jcr_data_current(
                            config_dir=temp_dir,
                            auto_update_days=7,
                        )

            info = json.loads((data_dir / "version.json").read_text(encoding="utf-8"))

        self.assertFalse(changed)
        update_jcr_data.assert_not_called()
        self.assertEqual(info["remote_ref"], "new")
        self.assertGreater(datetime.fromisoformat(info["last_check"]), datetime.now() - timedelta(days=1))

    def test_runtime_update_still_reloads_when_revision_read_fails(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)

            with patch.object(updater, "update_jcr_data", return_value=data_dir):
                with patch.object(updater, "get_checked_out_ref", side_effect=RuntimeError("bad git")):
                    changed = updater.ensure_jcr_data_current(
                        config_dir=temp_dir,
                        auto_update_days=7,
                    )

            info = json.loads((data_dir / "version.json").read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertNotIn("remote_ref", info)

    def test_get_jcr_index_updates_missing_data_then_loads_index(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            csv_dir = _make_jcr_data(data_dir)
            index = JcrIndex()
            index.add(JcrEntry(journal="Nature", issn="00280836", impact_factor=64.8))
            config = Config.__new__(Config)
            config._raw = {
                "jcr": {
                    "enabled": True,
                    "data_dir": temp_dir,
                    "auto_update_days": 7,
                }
            }

            paper_search_module._jcr_index = None
            with patch.object(paper_search_module, "ensure_jcr_data_current", return_value=True) as ensure:
                with patch.object(paper_search_module, "load_jcr_index", return_value=index) as load:
                    loaded = paper_search_module._get_jcr_index(config)

        self.assertIs(loaded, index)
        ensure.assert_called_once_with(config_dir=temp_dir, auto_update_days=7)
        load.assert_called_once_with(str(csv_dir))

    def test_get_jcr_index_ignores_index_metadata_write_failures(self) -> None:
        with TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            csv_dir = _make_jcr_data(data_dir)
            index = JcrIndex()
            index.add(JcrEntry(journal="Nature", issn="00280836", impact_factor=64.8))
            config = Config.__new__(Config)
            config._raw = {
                "jcr": {
                    "enabled": True,
                    "data_dir": temp_dir,
                    "auto_update_days": 0,
                }
            }

            paper_search_module._jcr_index = None
            with patch.object(paper_search_module, "load_jcr_index", return_value=index) as load:
                with patch.object(updater, "_write_version", side_effect=PermissionError("read-only")):
                    loaded = paper_search_module._get_jcr_index(config)

        self.assertIs(loaded, index)
        load.assert_called_once_with(str(csv_dir))

    def test_get_jcr_index_returns_none_without_side_effect_when_jcr_disabled(self) -> None:
        config = Config.__new__(Config)
        config._raw = {"jcr": {"enabled": False}}

        paper_search_module._jcr_index = None
        with patch.object(paper_search_module, "ensure_jcr_data_current") as ensure:
            loaded = paper_search_module._get_jcr_index(config)

        self.assertIsNone(loaded)
        ensure.assert_not_called()


if __name__ == "__main__":
    unittest.main()
