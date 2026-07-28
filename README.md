# swh-dataset-downloader

Download source code associated to commit archived on Software Heritage take as input a list of   `(repository URL, revision SWHID)` pairs.

Each entry is fetched from **GitHub** (shallow clone) when possible, falling back to the **[Software Heritage Vault](https://archive.softwareheritage.org/api/1/vault/)** (git-bare bundle). Already-downloaded entries are skipped on re-run.

> **Disclaimer:** this is an independent, community-maintained tool. It is **not** developed or maintained by Software Heritage, and is not officially supported by them.

---

## Does this tool suit my need?

**Use case:** you have a list of `(repository origin, revision SWHID)` pairs archived on Software Heritage, and you want to download the corresponding source code as fast as possible — trying the origin (e.g. GitHub) first, and only falling back to the slower Software Heritage infrastructure (Vault) as a last resort when the revision no longer exists at the origin.

If that matches what you're after, this tool is for you. If you instead need guaranteed retrieval straight from the Software Heritage archive (regardless of speed, or when the origin is expected to be gone), consider using the [Software Heritage API](https://archive.softwareheritage.org/api/) or [Vault](https://archive.softwareheritage.org/api/1/vault/) directly.

---

## Why?

Software Heritage stores repositories in a **deduplicated** manner: files, directories and revisions are content-addressed and shared across the entire archive rather than kept as one tree per repository. To reconstruct the source tree of a single commit, the archive has to walk the revision's directory graph and re-assemble it from individual blobs — blobs that aren't necessarily stored with any locality to one another. That reconstruction is what makes direct downloads from Software Heritage (Vault bundles included) comparatively slow.

Other tooling such as [swh-fuse](https://docs.softwareheritage.org/devel/swh-fuse/index.html) or [swh-mosaic](https://docs.softwareheritage.org/devel/swh-mosaic/index.html) address this by querying a `swh-graph` instance, but standing one up yourself is prohibitively costly for most use cases.

Since the large majority of archived revisions are still reachable at their origin (GitHub, GitLab, etc.), fetching from there first is almost always faster — falling back to the Software Heritage Vault only when the origin copy is gone.

**Note:** when constructing a `.mosaic` file for the revisions you need is feasible in your setup, using [swh-mosaic](https://docs.softwareheritage.org/devel/swh-mosaic/index.html) directly is currently the most relevant way to reconstruct source trees from Software Heritage — it targets small source-code objects specifically and avoids Vault's cook/fetch round-trip, without requiring a full `swh-graph` deployment.

---

## Quick start

```bash
pip install -r requirements.txt

export SWH_TOKEN=your_swh_token  # required — https://archive.softwareheritage.org/api/auth/login/

python -m downloader input.json --output-dir ./output
```

Or with Docker:

```bash
cp .env.example .env   # fill in SWH_TOKEN
docker compose up --build
```

---

## Input format

JSON or CSV, one entry per commit. An optional `output_dir` overrides the auto-generated subdirectory name:

```json
[
  { "url": "https://github.com/pallets/flask",       "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d" },
  { "url": "https://gitlab.com/inkscape/inkscape",   "swhid": "swh:1:rev:a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2", "output_dir": "inkscape" }
]
```

```csv
url,swhid,output_dir
https://github.com/pallets/flask,swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d,
```

---

## Output

One subdirectory per entry, with a `.done` marker on success. Named `{index}_{repo}_{short_hash}/` unless `output_dir` was set for that entry.

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
        {"url": "https://github.com/pallets/flask", "swhid": "swh:1:rev:0e1a9420d2d6863c5bdddb9ba55e0b55d6f58a9d", "output_dir": "flask"},
    ],
    output_base=Path("./output"),
    swh_token="your_swh_token",
))

for task in results:
    print(task.status, task.source, task.output_dir)
```

---

See [ADVANCED.md](ADVANCED.md) for Python API reference, logging, and Docker details.

---

## Getting API tokens

### Software Heritage token (required)

1. [Create a Software Heritage account](https://archive.softwareheritage.org/oidc/login/)
2. Once logged in, go to your [profile token page](https://archive.softwareheritage.org/oidc/profile/#tokens) and generate a new token.
3. Set it as `SWH_TOKEN` in your environment or `.env` file.

