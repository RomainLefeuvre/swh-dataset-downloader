# swh-dataset-downloader

Downloads source tree snapshots for a list of `(repository URL, commit SWHID)` pairs.

For **GitHub URLs**, the tool first checks whether the commit is still accessible on GitHub and downloads from there directly (no cooking delay). For any other host — or if the commit has been removed from GitHub — it falls back to the **[Software Heritage Vault API](https://archive.softwareheritage.org/api/1/vault/)**.

---

## Features

- Accepts `.json` or `.csv` input files
- Automatically routes each entry to the fastest available source (GitHub → SWH Vault)
- Respects concurrency limits: **max 2 concurrent SWH Vault jobs**, **max 2 concurrent GitHub downloads**
- SWH Vault jobs are polled asynchronously — all entries progress simultaneously
- Debug mode (`-v`) logs every HTTP request and response, with tokens redacted
- Fully Dockerized

---

## Input format

Each entry needs a `url` (repository URL) and a `swhid` (Software Heritage revision identifier).

**JSON** (`input.json`):
```json
[
  {
    "url": "https://github.com/pallets/flask",
    "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d"
  },
  {
    "url": "https://gitlab.com/inkscape/inkscape",
    "swhid": "swh:1:rev:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"
  }
]
```

**CSV** (`input.csv`):
```csv
url,swhid
https://github.com/pallets/flask,swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d
https://gitlab.com/inkscape/inkscape,swh:1:rev:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2
```

---

## Output structure

Each entry is extracted into its own subdirectory under `--output-dir`:

```
output/
├── 0000_pallets_flask_0e1a9420d2d6/
│   ├── src/
│   └── ...
└── 0001_inkscape_inkscape_a1b2c3d4e5f6/
    └── ...
```

---

## Usage

### Prerequisites

- Python 3.12+
- A [Software Heritage API token](https://archive.softwareheritage.org/api/auth/login/) (required)
- A GitHub Personal Access Token (optional, but avoids rate limiting)

### Without Docker

```bash
pip install -r requirements.txt

export SWH_TOKEN=your_swh_token
export GITHUB_TOKEN=your_github_token   # optional

python -m downloader input.json --output-dir ./output
```

All options:

```
Usage: python -m downloader [OPTIONS] INPUT_FILE

  Download source trees for a list of (url, swhid) pairs.

Options:
  -o, --output-dir PATH    Directory where source trees are extracted. [default: ./output]
  --swh-token TEXT         Software Heritage API bearer token. [$SWH_TOKEN]
  --github-token TEXT      GitHub API token (optional). [$GITHUB_TOKEN]
  -v, --verbose            Enable debug logging (prints every HTTP request/response).
  --help                   Show this message and exit.
```

### With Docker

**1. Configure tokens**

```bash
cp .env.example .env
# Edit .env and fill in SWH_TOKEN (and optionally GITHUB_TOKEN)
```

**2. Prepare your input file**

```bash
cp input_example.json input.json
# Edit input.json with your (url, swhid) pairs
```

**3. Run**

```bash
docker compose up --build
```

Downloaded trees will appear in `./output/` on the host.

To pass extra flags (e.g. verbose mode):

```bash
docker compose run --rm downloader input.json --output-dir /app/output --verbose
```

---

## How it works

```
For each (url, swhid) pair — all processed concurrently:

  ┌─ Is it a GitHub URL? ──────────────────────────────────────────┐
  │                                                                 │
  │  YES → GET /repos/{owner}/{repo}/commits/{sha}                 │
  │         ├─ 200 OK  → download tarball from GitHub API  ────────┤
  │         └─ 404     → fall back to SWH Vault            ────────┤
  │                                                                 │
  │  NO  → SWH Vault directly                              ────────┤
  │                                                                 │
  └─────────────────────────────────────────────────────────────────┘

  SWH Vault flow:
    POST /api/1/vault/flat/{swhid}/   ← request cooking
    GET  /api/1/vault/flat/{swhid}/   ← poll every 30 s until status=done
    GET  /api/1/vault/flat/{swhid}/raw/  ← download tar.gz → extract
```

Concurrency is enforced with `asyncio.Semaphore`:
- SWH: 2 slots — held for the full duration of cook + poll + download
- GitHub: 2 slots — held only during the tarball download

---

## Python API

You can call the pipeline directly from your own code without going through the CLI.

### Basic usage

```python
import asyncio
from pathlib import Path
from downloader.pipeline import run_pipeline

pairs = [
    {"url": "https://github.com/pallets/flask",  "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d"},
    {"url": "https://gitlab.com/inkscape/inkscape", "swhid": "swh:1:rev:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2"},
]

results = asyncio.run(
    run_pipeline(
        pairs=pairs,
        output_base=Path("./output"),
        swh_token="your_swh_token",
        github_token="your_github_token",  # optional
        debug=False,
    )
)
```

### Signature

```python
async def run_pipeline(
    pairs: list[dict],          # list of {"url": ..., "swhid": ...}
    output_base: Path,          # root directory where trees are extracted
    swh_token: str,             # SWH bearer token (required)
    github_token: str | None,   # GitHub PAT (optional, raises rate limits)
    debug: bool = False,        # log every HTTP request/response
) -> list[DownloadTask]: ...
```

### Return value

`run_pipeline` returns a `list[DownloadTask]` in input order. Each object exposes:

| Field | Type | Description |
|---|---|---|
| `index` | `int` | Position in the input list |
| `url` | `str` | Repository URL as provided |
| `swhid` | `str` | Software Heritage identifier as provided |
| `output_dir` | `Path` | Directory where the tree was extracted |
| `status` | `TaskStatus` | `DONE` or `FAILED` |
| `source` | `DownloadSource \| None` | `GITHUB` or `SWH_VAULT` |
| `error` | `str \| None` | Error message if `status == FAILED` |

### Inspecting results

```python
from downloader.models import TaskStatus, DownloadSource

for task in results:
    if task.status == TaskStatus.DONE:
        print(f"[{task.source.value}] {task.url} → {task.output_dir}")
    else:
        print(f"FAILED {task.url}: {task.error}")
```

### Inside an existing async context

If you are already inside a coroutine, call `run_pipeline` directly with `await` instead of wrapping it in `asyncio.run`:

```python
async def my_pipeline():
    results = await run_pipeline(pairs, Path("./output"), swh_token="...")
    return results
```

### Logging

The tool uses Python's standard `logging` module under the `downloader` namespace. Wire it into your existing logging setup:

```python
import logging

# Show INFO-level progress messages
logging.getLogger("downloader").setLevel(logging.INFO)

# Also show every HTTP request/response (equivalent to debug=True)
logging.getLogger("downloader.pipeline.http").setLevel(logging.DEBUG)
```

---

## Project structure

```
swh-dataset-downloader/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── requirements.txt
├── input_example.json
└── downloader/
    ├── __main__.py      # python -m downloader entry point
    ├── main.py          # CLI definition (click)
    ├── models.py        # DownloadTask, DownloadSource, TaskStatus
    ├── swh_client.py    # SWH Vault API: cook → poll → download
    ├── github_client.py # GitHub: commit check + tarball download
    └── pipeline.py      # Orchestration, routing, HTTP session, debug tracing
```
