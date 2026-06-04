# Advanced usage

## CLI options

```
Usage: python -m downloader [OPTIONS] INPUT_FILE

Options:
  -o, --output-dir PATH    Directory where source trees are extracted. [default: ./output]
  --swh-token TEXT         Software Heritage API bearer token. [$SWH_TOKEN]
  --github-token TEXT      GitHub API token (optional). [$GITHUB_TOKEN]
  -v, --verbose            Enable debug logging (prints every HTTP request/response).
  --help                   Show this message and exit.
```

---

## How it works

```
For each (url, swhid) pair — all processed concurrently:

  GitHub URL?
    YES → git fetch --depth=1 origin <commit>
           ├─ success → git checkout -f FETCH_HEAD
           └─ failure → SWH Vault git-bare
    NO  → SWH Vault git-bare

  SWH Vault git-bare:
    POST /api/1/vault/git-bare/{swhid}/      ← request cooking
    GET  /api/1/vault/git-bare/{swhid}/      ← poll every 30 s
    GET  /api/1/vault/git-bare/{swhid}/raw/  ← download + extract
```

Concurrency limits (asyncio semaphores):
- SWH Vault: 2 concurrent jobs (cook + poll + download)
- GitHub: 5 concurrent fetches

---

## Python API

```python
import asyncio
from pathlib import Path
from downloader.pipeline import run_pipeline

results = asyncio.run(run_pipeline(
    pairs=[
        {"url": "https://github.com/pallets/flask", "swhid": "swh:1:rev:0e1a9420..."},
    ],
    output_base=Path("./output"),
    swh_token="your_swh_token",
    github_token="your_github_token",  # optional
))

for task in results:
    print(task.status, task.source, task.output_dir)
```

### DownloadTask fields

| Field | Type | Description |
|---|---|---|
| `index` | `int` | Position in the input list |
| `url` | `str` | Repository URL |
| `swhid` | `str` | Software Heritage identifier |
| `output_dir` | `Path` | Extraction directory |
| `status` | `TaskStatus` | `DONE` or `FAILED` |
| `source` | `DownloadSource` | `GITHUB` or `SWH_GITBARE` |
| `error` | `str \| None` | Error message if failed |

---

## Logging

```python
import logging
logging.getLogger("downloader").setLevel(logging.INFO)
logging.getLogger("downloader.pipeline.http").setLevel(logging.DEBUG)  # all HTTP traffic
```

---

## Docker

```bash
cp .env.example .env
# fill in SWH_TOKEN and optionally GITHUB_TOKEN

cp input_example.json input.json
docker compose up --build
```

To pass extra flags:

```bash
docker compose run --rm downloader input.json --output-dir /app/output --verbose
```
