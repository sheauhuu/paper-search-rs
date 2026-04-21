"""JCR data updater — git clone/pull from ShowJCR repo."""

from __future__ import annotations

import subprocess
from pathlib import Path

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


def needs_update(data_dir: Path, max_age_days: int = 30) -> bool:
    """Check if JCR data needs updating based on age."""
    version_file = data_dir / "version.json"
    if not version_file.is_file():
        return True

    import json
    from datetime import datetime, timedelta

    try:
        with open(version_file) as f:
            info = json.load(f)
        last_update = datetime.fromisoformat(info.get("last_update", "2000-01-01"))
        return datetime.now() - last_update > timedelta(days=max_age_days)
    except Exception:
        return True


def save_version(data_dir: Path, jcr_year: int = 0) -> None:
    """Save version info after successful update."""
    import json
    from datetime import datetime

    version_file = data_dir / "version.json"
    info = {
        "last_update": datetime.now().isoformat(),
        "jcr_year": jcr_year,
    }
    with open(version_file, "w") as f:
        json.dump(info, f, indent=2)
