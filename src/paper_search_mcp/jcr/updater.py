"""JCR data updater — git clone/pull from ShowJCR repo."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger

SHOWJCR_REPO = "https://github.com/hitfyd/ShowJCR.git"


def get_data_dir(config_dir: str = "") -> Path:
    """Get JCR data directory, creating if needed."""
    if config_dir:
        d = Path(config_dir)
    else:
        d = Path.home() / ".paper-search-mcp" / "jcr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def update_jcr_data(config_dir: str = "") -> Path:
    """Clone or update ShowJCR repo to get latest CSV/DB data.

    Returns path to the data directory containing CSV files and jcr.db.
    """
    data_dir = get_data_dir(config_dir)
    repo_dir = data_dir / "repo"

    if (repo_dir / ".git").is_dir():
        # Pull latest
        logger.info(f"Updating ShowJCR repo at {repo_dir}")
        try:
            subprocess.run(
                ["git", "pull"],
                cwd=str(repo_dir),
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"git pull failed: {e.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning("git pull timed out")
    else:
        # Fresh clone
        logger.info(f"Cloning ShowJCR repo to {repo_dir}")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", SHOWJCR_REPO, str(repo_dir)],
                capture_output=True,
                text=True,
                timeout=300,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            logger.error(f"git clone failed: {e.stderr}")
            raise RuntimeError(f"Failed to clone ShowJCR: {e.stderr}")
        except subprocess.TimeoutExpired:
            raise RuntimeError("git clone timed out")

    # Data files are in repo/中科院分区表及JCR原始数据文件/
    csv_dir = repo_dir / "中科院分区表及JCR原始数据文件"
    if not csv_dir.is_dir():
        raise RuntimeError(f"Data directory not found: {csv_dir}")

    return csv_dir


def has_jcr_data(data_dir: Path) -> bool:
    """Return whether data_dir contains loadable ShowJCR data."""
    csv_dir = data_dir / "repo" / "中科院分区表及JCR原始数据文件"
    if _contains_jcr_data(csv_dir):
        return True
    return _contains_jcr_data(data_dir)


def get_jcr_data_source_dir(data_dir: Path) -> Path | None:
    """Return the best local directory to pass to load_jcr_index."""
    csv_dir = data_dir / "repo" / "中科院分区表及JCR原始数据文件"
    if _contains_jcr_data(csv_dir):
        return csv_dir
    if _contains_jcr_data(data_dir):
        return data_dir
    return None


def read_version(data_dir: Path) -> dict[str, Any]:
    """Read JCR version metadata."""
    version_file = data_dir / "version.json"
    if not version_file.is_file():
        return {}
    try:
        with open(version_file, encoding="utf-8") as f:
            info = json.load(f)
        return info if isinstance(info, dict) else {}
    except Exception as exc:
        logger.warning(f"[jcr] Failed to read version metadata: {exc}")
        return {}


def get_local_remote_ref(data_dir: Path) -> str:
    """Return the locally recorded or checked-out ShowJCR revision."""
    info = read_version(data_dir)
    remote_ref = info.get("remote_ref")
    if isinstance(remote_ref, str) and remote_ref:
        return remote_ref

    return get_checked_out_ref(data_dir)


def get_checked_out_ref(data_dir: Path) -> str:
    """Return the actual checked-out ShowJCR repo revision."""

    repo_dir = data_dir / "repo"
    if (repo_dir / ".git").is_dir():
        return _git_output(["git", "rev-parse", "HEAD"], cwd=repo_dir)
    return ""


def get_remote_ref() -> str:
    """Return the upstream ShowJCR HEAD revision without cloning the repo."""
    output = _git_output(["git", "ls-remote", SHOWJCR_REPO, "HEAD"])
    if not output:
        return ""
    return output.split()[0]


def should_check_remote(data_dir: Path, auto_update_days: int) -> bool:
    """Return whether runtime auto-update should check the upstream repo."""
    if auto_update_days <= 0:
        return False

    info = read_version(data_dir)
    raw_last_check = info.get("last_check") or info.get("last_update")
    if not isinstance(raw_last_check, str) or not raw_last_check:
        return True

    try:
        last_check = datetime.fromisoformat(raw_last_check)
    except ValueError:
        return True
    return datetime.now() - last_check >= timedelta(days=auto_update_days)


def touch_last_check(data_dir: Path, remote_ref: str = "") -> None:
    """Record a successful upstream check without changing data files."""
    info = read_version(data_dir)
    info["last_check"] = datetime.now().isoformat()
    info["source"] = SHOWJCR_REPO
    if remote_ref:
        info["remote_ref"] = remote_ref
    _write_version(data_dir, info)


def try_touch_last_check(data_dir: Path, remote_ref: str = "") -> None:
    """Best-effort last-check write for runtime throttling."""
    try:
        touch_last_check(data_dir, remote_ref=remote_ref)
    except OSError as exc:
        logger.warning(f"[jcr] Failed to write remote-check metadata: {exc}")


def try_save_index_size(data_dir: Path, index_size: int) -> None:
    """Best-effort record of the last successfully loaded JCR index size."""
    info = read_version(data_dir)
    info["index_size"] = index_size
    try:
        _write_version(data_dir, info)
    except OSError as exc:
        logger.warning(f"[jcr] Failed to write index metadata: {exc}")


def ensure_jcr_data_current(config_dir: str = "", auto_update_days: int = 7) -> bool:
    """Ensure runtime JCR data is present and reasonably current.

    Returns True when local JCR data changed and callers should reload indexes.
    Runtime failures are logged and swallowed so search requests can still use
    existing local data.
    """
    if auto_update_days <= 0:
        return False

    data_dir = get_data_dir(config_dir)
    if not has_jcr_data(data_dir):
        logger.info("[jcr] Local data missing; downloading ShowJCR data")
        return _runtime_update(config_dir, data_dir)

    if not should_check_remote(data_dir, auto_update_days):
        return False

    try:
        remote_ref = get_remote_ref()
    except RuntimeError as exc:
        logger.warning(f"[jcr] Failed to check ShowJCR remote: {exc}")
        try_touch_last_check(data_dir)
        return False

    if not remote_ref:
        logger.warning("[jcr] ShowJCR remote check returned no revision")
        try_touch_last_check(data_dir)
        return False

    try:
        local_ref = get_local_remote_ref(data_dir)
    except RuntimeError as exc:
        logger.warning(f"[jcr] Failed to read local ShowJCR revision: {exc}")
        try_touch_last_check(data_dir, remote_ref=remote_ref)
        return False

    if local_ref == remote_ref:
        logger.info("[jcr] Local ShowJCR data is up to date")
        try_touch_last_check(data_dir, remote_ref=remote_ref)
        return False

    logger.info("[jcr] ShowJCR remote changed; updating local data")
    return _runtime_update(config_dir, data_dir, remote_ref=remote_ref)


def needs_update(data_dir: Path, max_age_days: int = 30) -> bool:
    """Check if JCR data needs updating based on age."""
    version_file = data_dir / "version.json"
    if not version_file.is_file():
        return True

    try:
        with open(version_file, encoding="utf-8") as f:
            info = json.load(f)
        last_update = datetime.fromisoformat(info.get("last_update", "2000-01-01"))
        return datetime.now() - last_update > timedelta(days=max_age_days)
    except Exception:
        return True


def save_version(
    data_dir: Path,
    jcr_year: int = 0,
    remote_ref: str = "",
    index_size: int | None = None,
) -> None:
    """Save version info after successful update."""
    info = {
        "last_update": datetime.now().isoformat(),
        "last_check": datetime.now().isoformat(),
        "source": SHOWJCR_REPO,
        "jcr_year": jcr_year,
    }
    if remote_ref:
        info["remote_ref"] = remote_ref
    if index_size is not None:
        info["index_size"] = index_size
    _write_version(data_dir, info)


def _contains_jcr_data(path: Path) -> bool:
    if not path.is_dir():
        return False
    return (path / "jcr.db").is_file() or any(path.glob("JCR*UTF8.csv"))


def _runtime_update(
    config_dir: str,
    data_dir: Path,
    remote_ref: str = "",
) -> bool:
    try:
        update_jcr_data(config_dir)
    except RuntimeError as exc:
        logger.warning(f"[jcr] Runtime update failed: {exc}")
        return False

    checked_out_ref = ""
    try:
        checked_out_ref = get_checked_out_ref(data_dir)
    except RuntimeError as exc:
        logger.warning(f"[jcr] Failed to read checked-out ShowJCR revision: {exc}")

    if remote_ref and checked_out_ref and checked_out_ref != remote_ref:
        logger.warning(
            "[jcr] ShowJCR update completed but checked-out revision "
            "does not match remote HEAD"
        )
        return False

    save_version(data_dir, remote_ref=checked_out_ref or remote_ref)
    return True


def _git_output(args: list[str], cwd: Path | None = None) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr.strip() or str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("git command timed out") from exc
    return result.stdout.strip()


def _write_version(data_dir: Path, info: dict[str, Any]) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    version_file = data_dir / "version.json"
    with open(version_file, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2)
