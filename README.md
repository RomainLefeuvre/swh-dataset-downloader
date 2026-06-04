# swh-dataset-downloader

Download source code associated to commit archived on Software Heritage take as input a list of   `(repository URL, revision SWHID)` pairs.

Each entry is fetched from **GitHub** (shallow clone) when possible, falling back to the **[Software Heritage Vault](https://archive.softwareheritage.org/api/1/vault/)** (git-bare bundle). Already-downloaded entries are skipped on re-run.

---

## Quick start

```bash
pip install -r requirements.txt

export SWH_TOKEN=your_swh_token       # required — https://archive.softwareheritage.org/api/auth/login/
export GITHUB_TOKEN=your_github_token  # optional, avoids rate limiting

python -m downloader input.json --output-dir ./output
```

Or with Docker:

```bash
cp .env.example .env   # fill in SWH_TOKEN
docker compose up --build
```

---

## Input format

JSON or CSV, one entry per commit:

```json
[
  { "url": "https://github.com/pallets/flask",       "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d" },
  { "url": "https://gitlab.com/inkscape/inkscape",   "swhid": "swh:1:rev:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2" }
]
```

```csv
url,swhid
https://github.com/pallets/flask,swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d
```

---

## Output

One subdirectory per entry, named `{index}_{repo}_{short_hash}/`, with a `.done` marker on success.

```
output/
├── 0000_pallets_flask_0e1a9420d2d6/
└── 0001_inkscape_inkscape_a1b2c3d4e5f6/
```

---

## Python

```python
import asyncio
from pathlib import Path
from downloader.pipeline import run_pipeline

results = asyncio.run(run_pipeline(
    pairs=[
        {"url": "https://github.com/pallets/flask", "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d"},
    ],
    output_base=Path("./output"),
    swh_token="your_swh_token",
    github_token="your_github_token",  # optional
))

for task in results:
    print(task.status, task.source, task.output_dir)
```

---

See [ADVANCED.md](ADVANCED.md) for Python API reference, logging, and Docker details.
