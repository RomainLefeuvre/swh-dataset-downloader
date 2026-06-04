import asyncio
import io
import logging
import tarfile
from pathlib import Path

import aiohttp

logger = logging.getLogger(__name__)

SWH_API_BASE = "https://archive.softwareheritage.org/api/1"
POLL_INTERVAL_SECONDS = 30


def _extract_tar(content: bytes, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as tar:
        try:
            tar.extractall(output_dir, filter="data")
        except TypeError:
            # filter= parameter added in Python 3.12
            tar.extractall(output_dir)  # noqa: S202


class SWHVaultClient:
    """Async client for the Software Heritage Vault API.

    At most `semaphore` concurrent cooking jobs are active at any time.
    Polling counts as part of the job (it still occupies a slot).
    """

    def __init__(
        self,
        token: str,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
    ) -> None:
        self._headers = {"Authorization": f"Bearer {token}"}
        self._session = session
        self._semaphore = semaphore

    async def download(self, swhid: str, output_dir: Path) -> None:
        """Request cooking, poll until done, then extract the flat tar.gz."""
        async with self._semaphore:
            await self._cook_and_extract(swhid, output_dir)

    async def _cook_and_extract(self, swhid: str, output_dir: Path) -> None:
        cook_url = f"{SWH_API_BASE}/vault/flat/{swhid}/"

        # Start cooking (POST). If already cooked, SWH returns 200 with status=done.
        async with self._session.post(cook_url, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                raise RuntimeError(f"SWH cook request failed (HTTP {resp.status}): {body}")
            data = await resp.json()

        status = data.get("status", "new")
        logger.info("SWH vault %s: initial status=%s", swhid, status)

        while status not in ("done", "failed"):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            async with self._session.get(cook_url, headers=self._headers) as resp:
                data = await resp.json()
            status = data.get("status", "pending")
            logger.info("SWH vault %s: status=%s", swhid, status)

        if status == "failed":
            raise RuntimeError(
                f"SWH vault cooking failed for {swhid}: {data.get('exception', 'unknown error')}"
            )

        # Download the raw bundle
        raw_url = f"{SWH_API_BASE}/vault/flat/{swhid}/raw/"
        async with self._session.get(raw_url, headers=self._headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"SWH raw download failed (HTTP {resp.status}): {body}")
            content = await resp.read()

        _extract_tar(content, output_dir)
        logger.info("SWH vault %s: extracted to %s", swhid, output_dir)
