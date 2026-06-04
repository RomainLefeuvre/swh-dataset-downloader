import asyncio
import io
import logging
import tarfile
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def _parse_github_repo(url: str) -> tuple[str, str]:
    """Return (owner, repo) from any GitHub repository URL."""
    path = urlparse(url).path.strip("/").removesuffix(".git")
    parts = path.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Cannot parse GitHub owner/repo from URL: {url}")
    return parts[0], parts[1]


def _extract_tar_strip_root(content: bytes, output_dir: Path) -> None:
    """Extract a tar.gz while stripping the single root directory GitHub wraps around the tree."""
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        members = tar.getmembers()
        if not members:
            return

        # All GitHub tarballs have a single top-level dir like "owner-repo-sha1234/"
        root_prefix = members[0].name.split("/")[0] + "/"

        for member in members:
            if member.name.startswith(root_prefix):
                member.name = member.name[len(root_prefix):]
            if not member.name:
                continue
            try:
                tar.extract(member, output_dir, set_attrs=False)
            except TypeError:
                # set_attrs added in Python 3.12
                tar.extract(member, output_dir)


class GitHubClient:
    """Async client for GitHub: commit presence check + tarball download.

    At most `semaphore` concurrent downloads are active at any time.
    Commit existence checks are lightweight and do not occupy a slot.
    """

    def __init__(
        self,
        token: str | None,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._headers = {"Accept": "application/vnd.github+json"}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._session = session
        self._semaphore = semaphore

    async def commit_exists(self, url: str, commit_hash: str) -> bool:
        """Return True if the commit is reachable on GitHub (HTTP 200)."""
        owner, repo = _parse_github_repo(url)
        api_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/commits/{commit_hash}"
        try:
            async with self._session.get(api_url, headers=self._headers) as resp:
                if resp.status == 200:
                    return True
                if resp.status == 404:
                    return False
                # Rate limit or other transient error — treat as not available
                logger.warning(
                    "GitHub commit check returned unexpected status %s for %s@%s",
                    resp.status, url, commit_hash,
                )
                return False
        except aiohttp.ClientError as exc:
            logger.warning("GitHub commit check failed for %s@%s: %s", url, commit_hash, exc)
            return False

    async def download(self, url: str, commit_hash: str, output_dir: Path) -> None:
        """Download the repo tree at commit_hash as a tar.gz and extract it."""
        async with self._semaphore:
            await self._download_tarball(url, commit_hash, output_dir)

    async def _download_tarball(self, url: str, commit_hash: str, output_dir: Path) -> None:
        owner, repo = _parse_github_repo(url)
        tarball_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/tarball/{commit_hash}"

        async with self._session.get(
            tarball_url, headers=self._headers, allow_redirects=True
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"GitHub tarball download failed (HTTP {resp.status}) "
                    f"for {url}@{commit_hash}: {body}"
                )
            content = await resp.read()

        _extract_tar_strip_root(content, output_dir)
        logger.info("GitHub %s@%s: extracted to %s", url, commit_hash, output_dir)
