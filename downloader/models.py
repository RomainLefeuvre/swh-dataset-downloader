from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional


class DownloadSource(Enum):
    GITHUB = "github"
    SWH_GITBARE = "swh_gitbare"


class TaskStatus(Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    DONE = "done"
    FAILED = "failed"


@dataclass
class DownloadTask:
    index: int
    url: str
    swhid: str
    output_dir: Path
    source: Optional[DownloadSource] = None
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None

    @property
    def commit_hash(self) -> Optional[str]:
        """Extract hex hash from a swhid like swh:1:rev:abc123..."""
        parts = self.swhid.split(":")
        if len(parts) == 4 and parts[0] == "swh":
            return parts[3]
        return None

    @property
    def is_github_url(self) -> bool:
        return "github.com" in self.url
