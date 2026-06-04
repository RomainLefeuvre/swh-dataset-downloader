import asyncio
import logging
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

from .github_client import GitHubClient
from .models import DownloadSource, DownloadTask, TaskStatus
from .swh_client import SWHVaultClient

logger = logging.getLogger(__name__)
http_logger = logging.getLogger(__name__ + ".http")

# Maximum concurrent jobs per backend
SWH_MAX_CONCURRENT = 2
GITHUB_MAX_CONCURRENT = 5


def _redact_headers(headers: dict) -> dict:
    """Replace Authorization token values with '***' for safe logging."""
    return {
        k: ("***" if k.lower() == "authorization" else v)
        for k, v in headers.items()
    }


def _build_trace_config() -> aiohttp.TraceConfig:
    """Return a TraceConfig that logs every HTTP request and response at DEBUG level."""

    async def on_request_start(
        _session: aiohttp.ClientSession,
        _ctx: object,
        params: aiohttp.TraceRequestStartParams,
    ) -> None:
        http_logger.debug(
            "→ %s %s  headers=%s",
            params.method,
            params.url,
            _redact_headers(dict(params.headers)),
        )

    async def on_request_end(
        _session: aiohttp.ClientSession,
        _ctx: object,
        params: aiohttp.TraceRequestEndParams,
    ) -> None:
        http_logger.debug(
            "← %s %s  status=%d",
            params.method,
            params.url,
            params.response.status,
        )

    trace = aiohttp.TraceConfig()
    trace.on_request_start.append(on_request_start)
    trace.on_request_end.append(on_request_end)
    return trace


def _make_output_dir_name(index: int, url: str, swhid: str) -> str:
    """Build a human-readable, filesystem-safe directory name."""
    path = urlparse(url).path.strip("/").replace("/", "_")
    path = re.sub(r"[^\w\-.]", "_", path)
    short_hash = swhid.split(":")[-1][:12]
    return f"{index:04d}_{path}_{short_hash}"


DONE_MARKER = ".done"


async def _process_task(
    task: DownloadTask,
    swh: SWHVaultClient,
    gh: GitHubClient,
) -> DownloadTask:
    done_marker = task.output_dir / DONE_MARKER
    if done_marker.exists():
        logger.info("[%d] skipped (already done)  %s  %s", task.index, task.url, task.commit_hash)
        task.status = TaskStatus.DONE
        return task

    logger.info("[%d] start  %s  %s", task.index, task.url, task.commit_hash)
    t0 = time.monotonic()
    task.status = TaskStatus.DOWNLOADING
    try:
        if task.is_github_url and task.commit_hash:
            try:
                fetched = await gh.download(task.url, task.commit_hash, task.output_dir)
            except Exception as gh_exc:
                logger.warning(
                    "[%d] GitHub download raised %s → falling back to SWH vault",
                    task.index, gh_exc,
                )
                fetched = False
            if fetched:
                task.source = DownloadSource.GITHUB
            else:
                logger.info(
                    "[%d] Commit %s not fetchable from GitHub (%s) → falling back to SWH gitbare",
                    task.index, task.commit_hash, task.url,
                )
                await swh.download(task.swhid, task.output_dir)
                task.source = DownloadSource.SWH_GITBARE
        else:
            logger.info("[%d] Non-GitHub URL → using SWH gitbare", task.index)
            await swh.download(task.swhid, task.output_dir)
            task.source = DownloadSource.SWH_GITBARE

        task.status = TaskStatus.DONE
        done_marker.touch()
        elapsed = time.monotonic() - t0
        logger.info(
            "[%d] done in %.1fs  [%s]  %s  %s",
            task.index, elapsed, task.source.value, task.url, task.commit_hash,
        )

    except Exception as exc:
        elapsed = time.monotonic() - t0
        task.status = TaskStatus.FAILED
        task.error = str(exc)
        logger.error(
            "[%d] failed after %.1fs  %s  %s  — %s",
            task.index, elapsed, task.url, task.commit_hash, exc,
        )

    return task


async def run_pipeline(
    pairs: list[dict],
    output_base: Path,
    swh_token: str,
    github_token: str | None = None,
    debug: bool = False,
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

    trace_configs = [_build_trace_config()] if debug else []
    connector = aiohttp.TCPConnector(limit=20)
    timeout = aiohttp.ClientTimeout(total=3600)  # vault cooking can take tens of minutes
    async with aiohttp.ClientSession(
        connector=connector, timeout=timeout, trace_configs=trace_configs
    ) as session:
        swh = SWHVaultClient(swh_token, session, swh_semaphore)
        gh = GitHubClient(github_token, github_semaphore)

        results = await asyncio.gather(*[_process_task(t, swh, gh) for t in tasks])

    return list(results)
