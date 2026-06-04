import asyncio
import csv
import json
import logging
import sys
from pathlib import Path

import click

from .models import TaskStatus
from .pipeline import run_pipeline


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def _load_pairs(input_file: Path) -> list[dict]:
    with open(input_file) as f:
        if input_file.suffix == ".json":
            pairs = json.load(f)
        elif input_file.suffix == ".csv":
            reader = csv.DictReader(f)
            pairs = list(reader)
        else:
            raise click.BadParameter(
                f"Unsupported format '{input_file.suffix}'. Use .json or .csv."
            )

    for i, pair in enumerate(pairs):
        if "url" not in pair or "swhid" not in pair:
            raise click.BadParameter(
                f"Entry {i} is missing 'url' or 'swhid' field: {pair}"
            )
    return pairs


@click.command()
@click.argument("input_file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output-dir", "-o",
    default="./output",
    type=click.Path(path_type=Path),
    show_default=True,
    help="Directory where source trees are extracted.",
)
@click.option(
    "--swh-token",
    envvar="SWH_TOKEN",
    required=True,
    help="Software Heritage API bearer token. Can also be set via SWH_TOKEN env var.",
)
@click.option(
    "--github-token",
    envvar="GITHUB_TOKEN",
    default=None,
    help="GitHub API token (optional, raises rate limits). Can also be set via GITHUB_TOKEN.",
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug logging.")
def main(
    input_file: Path,
    output_dir: Path,
    swh_token: str,
    github_token: str | None,
    verbose: bool,
) -> None:
    """Download source trees for a list of (url, swhid) pairs.

    INPUT_FILE must be a JSON array or CSV file where each entry has a 'url'
    (repository URL) and a 'swhid' (e.g. swh:1:rev:abc123...) field.

    For GitHub URLs, the tool first checks whether the commit is still
    accessible on GitHub and downloads from there if possible (faster, no
    cooking delay). Otherwise it falls back to the SWH Vault API.
    """
    _setup_logging(verbose)

    pairs = _load_pairs(input_file)
    if not pairs:
        click.echo("No entries found in input file. Nothing to do.")
        return

    click.echo(f"Processing {len(pairs)} entries → {output_dir}/")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = asyncio.run(
        run_pipeline(pairs, output_dir, swh_token, github_token)
    )

    # ── Summary ────────────────────────────────────────────────────────────────
    click.echo()
    click.echo("─" * 60)
    for task in results:
        if task.status == TaskStatus.DONE:
            source_tag = f"[{task.source.value}]" if task.source else ""
            click.echo(f"  OK  {task.index:04d}  {task.url}  {source_tag}")
        else:
            click.echo(f"  FAIL {task.index:04d}  {task.url}  {task.error}")
    click.echo("─" * 60)

    done = sum(1 for r in results if r.status == TaskStatus.DONE)
    failed = len(results) - done
    click.echo(f"Done: {done}/{len(results)}  Failed: {failed}")

    if failed:
        sys.exit(1)
