import asyncio
import logging
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def _clean_git_output(raw: bytes) -> str:
    """Strip carriage returns git uses for terminal progress bars."""
    text = raw.decode(errors="replace")
    lines = [line.split("\r")[-1] for line in text.splitlines()]
    return "\n".join(line for line in lines if line.strip())


async def _run_git(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: subprocess.run(["git", *args], cwd=cwd, capture_output=True),
    )


class GitHubClient:
    """Fetches a single commit from GitHub via git fetch --depth=1.

    The output directory is left as a proper git repository.
    At most `semaphore` git operations run concurrently.
    """

    def __init__(self, token: str | None, semaphore: asyncio.Semaphore) -> None:
        self._token = token
        self._semaphore = semaphore

    def _authenticated_url(self, url: str) -> str:
        if self._token:
            return url.replace("https://", f"https://{self._token}@", 1)
        return url

    async def download(self, url: str, commit_hash: str, output_dir: Path) -> bool:
        """Shallow-fetch the commit and check it out as a git repo.

        Returns False if the commit is unreachable on GitHub (caller falls back to SWH).
        Raises RuntimeError on unexpected git failures.
        """
        async with self._semaphore:
            return await self._fetch_and_checkout(url, commit_hash, output_dir)

    async def _fetch_and_checkout(self, url: str, commit_hash: str, output_dir: Path) -> bool:
        clone_url = self._authenticated_url(url)
        logger.info("[github] fetching %s @ %s", url, commit_hash)
        t0 = time.monotonic()

        output_dir.mkdir(parents=True, exist_ok=True)
        await _run_git("init", str(output_dir))
        await _run_git("remote", "add", "origin", clone_url, cwd=str(output_dir))

        logger.info("[github] git fetch --depth=1 origin %s", commit_hash)
        fetch = await _run_git(
            "fetch", "--depth=1", "origin", commit_hash,
            cwd=str(output_dir),
        )
        if fetch.returncode != 0:
            stderr = _clean_git_output(fetch.stderr)
            if stderr:
                logger.error("[github] fetch failed:\n%s", stderr)
            return False

        log = await _run_git(
            "log", "FETCH_HEAD", "-1",
            "--format=  hash:    %H%n  date:    %ai%n  author:  %an <%ae>%n  subject: %s",
            cwd=str(output_dir),
        )
        if log.returncode == 0:
            logger.info("[github] commit info:\n%s", log.stdout.decode(errors="replace").strip())

        logger.info("[github] checking out FETCH_HEAD …")
        checkout = await _run_git("checkout", "FETCH_HEAD", cwd=str(output_dir))
        if checkout.returncode != 0:
            raise RuntimeError(
                f"git checkout failed for {url}@{commit_hash}: "
                f"{_clean_git_output(checkout.stderr)}"
            )

        elapsed = time.monotonic() - t0
        logger.info("[github] done in %.1fs → %s", elapsed, output_dir)
        return True
