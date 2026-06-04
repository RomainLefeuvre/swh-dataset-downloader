import asyncio
import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .github_client import GitHubClient
from .models import DownloadSource, DownloadTask, TaskStatus
from .swh_client import SWHVaultClient

logger = logging.getLogger(__name__)

# Maximum concurrent jobs per backend
SWH_MAX_CONCURRENT = 2
GITHUB_MAX_CONCURRENT = 2


def _make_output_dir_name(index: int, url: str, swhid: str) -> str:
    """Build a human-readable, filesystem-safe directory name."""
    path = urlparse(url).path.strip("/").replace("/", "_")
    path = re.sub(r"[^\w\-.]", "_", path)
    short_hash = swhid.split(":")[-1][:12]
    return f"{index:04d}_{path}_{short_hash}"


async def _process_task(
    task: DownloadTask,
    swh: SWHVaultClient,
    gh: GitHubClient,
) -> DownloadTask:
    task.status = TaskStatus.DOWNLOADING
    try:
        if task.is_github_url:
            commit = task.commit_hash
            if commit and await gh.commit_exists(task.url, commit):
                logger.info("[%d] Commit present on GitHub → downloading from GitHub", task.index)
                task.source = DownloadSource.GITHUB
                await gh.download(task.url, commit, task.output_dir)
            else:
                logger.info("[%d] Commit absent from GitHub → falling back to SWH vault", task.index)
                task.source = DownloadSource.SWH_VAULT
                await swh.download(task.swhid, task.output_dir)
        else:
            logger.info("[%d] Non-GitHub URL → using SWH vault", task.index)
            task.source = DownloadSource.SWH_VAULT
            await swh.download(task.swhid, task.output_dir)

        task.status = TaskStatus.DONE

    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error = str(exc)
        logger.error("[%d] Failed for %s: %s", task.index, task.url, exc)

    return task


async def run_pipeline(
    pairs: list[dict],
    output_base: Path,
    swh_token: str,
    github_token: str | None = None,
) -> list[DownloadTask]:
    """Run all download tasks concurrently, respecting per-backend concurrency limits."""
    swh_semaphore = asyncio.Semaphore(SWH_MAX_CONCURRENT)
    github_semaphore = asyncio.Semaphore(GITHUB_MAX_CONCURRENT)

    tasks = [
        DownloadTask(
            index=i,
            url=pair["url"],
            swhid=pair["swhid"],
            output_dir=output_base / _make_output_dir_name(i, pair["url"], pair["swhid"]),
        )
        for i, pair in enumerate(pairs)
    ]

    # Use a single shared aiohttp session for connection pooling
    connector = aiohttp.TCPConnector(limit=20)
    timeout = aiohttp.ClientTimeout(total=3600)  # vault cooking can take tens of minutes
    async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
        swh = SWHVaultClient(swh_token, session, swh_semaphore)
        gh = GitHubClient(github_token, session, github_semaphore)

        results = await asyncio.gather(*[_process_task(t, swh, gh) for t in tasks])

    return list(results)
