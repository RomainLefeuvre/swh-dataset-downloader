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
    """Async client for the Software Heritage Vault API (git-bare bundles).

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
        """Request git-bare cooking, poll until done, then extract the tar.gz.

        Requires a revision SWHID (swh:1:rev:...).
        """
        if not swhid.startswith("swh:1:rev:"):
            raise ValueError(f"git-bare requires a revision SWHID, got: {swhid}")
        async with self._semaphore:
            await self._cook_and_extract(swhid, output_dir)

    async def _cook_and_extract(self, swhid: str, output_dir: Path) -> None:
        cook_url = f"{SWH_API_BASE}/vault/git-bare/{swhid}/"

        async with self._session.post(cook_url, headers=self._headers) as resp:
            if resp.status not in (200, 201):
                body = await resp.text()
                raise RuntimeError(f"SWH git-bare cook request failed (HTTP {resp.status}): {body}")
        logger.info("SWH vault git-bare %s: cooking requested", swhid)

        data: dict = {}
        status = "new"
        while status not in ("done", "failed"):
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            async with self._session.get(cook_url, headers=self._headers) as resp:
                data = await resp.json()
            status = data.get("status", "pending")
            progress = data.get("progress_message", "")
            logger.info("SWH vault git-bare %s: status=%s  %s", swhid, status, progress)

        if status == "failed":
            raise RuntimeError(
                f"SWH vault git-bare cooking failed for {swhid}: {data.get('exception', 'unknown error')}"
            )

        raw_url = f"{SWH_API_BASE}/vault/git-bare/{swhid}/raw/"
        async with self._session.get(raw_url, headers=self._headers) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(f"SWH git-bare raw download failed (HTTP {resp.status}): {body}")
            content = await resp.read()

        _extract_tar(content, output_dir)
        logger.info("SWH vault git-bare %s: extracted to %s", swhid, output_dir)
