"""Object store for the data lake (QV-067) — one interface over local-fs and S3/MinIO.

Historical price partitions are offloaded to Parquet, path-partitioned
``/{market}/{table}/{year}/{month}/part.parquet`` (03 §7). This module hides *where* those files
live behind a ``pyarrow.fs`` filesystem + a base prefix, so the export writer and the DuckDB reader
work unchanged against either backend:

- **local** (dev/CI): a filesystem root (``settings.object_store_root``).
- **s3** (MinIO/S3): a real ``S3FileSystem`` wired to the existing ``s3_*`` settings. Authored +
  offline-validated here; the live round-trip is deferred with Docker/AWS (see deferred-work.md).

``pyarrow`` is an optional ``[lake]`` extra, so it is imported lazily — importing this module never
requires the extra; only calling ``get_object_store`` does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid importing the optional extra at module load
    from quantvista.core.config import Settings


@dataclass(frozen=True)
class ObjectStore:
    """A ``pyarrow`` filesystem + a base prefix. Builds partition paths + DuckDB read globs."""

    fs: Any  # pyarrow.fs.FileSystem
    base: str  # local dir path, or "{bucket}" for s3
    scheme: str  # "" for local, "s3://" for s3

    def partition_dir(self, market: str, table: str, year: int, month: int) -> str:
        return f"{self.base}/{market}/{table}/{year:04d}/{month:02d}"

    def partition_file(self, market: str, table: str, year: int, month: int) -> str:
        return f"{self.partition_dir(market, table, year, month)}/part.parquet"

    def read_glob(self, market: str, table: str) -> str:
        """A DuckDB-readable glob over every ``{year}/{month}`` partition of ``table``."""
        return f"{self.scheme}{self.base}/{market}/{table}/*/*/part.parquet"

    def table_exists(self, market: str, table: str) -> bool:
        """True if any partitions have been exported for ``market``/``table`` (else a glob read
        would error / there is simply no data yet)."""
        from pyarrow.fs import FileType

        info = self.fs.get_file_info(f"{self.base}/{market}/{table}")
        return bool(info.type != FileType.NotFound)


def get_object_store(settings: Settings) -> ObjectStore:
    """Build the configured store. ``local`` (default) or ``s3`` (MinIO/S3, offline-validated)."""
    import pyarrow.fs as pafs  # lazy: only the [lake] extra path needs it

    if settings.object_store_backend == "s3":
        fs = pafs.S3FileSystem(
            endpoint_override=settings.s3_endpoint_url,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            scheme="http" if settings.s3_endpoint_url.startswith("http://") else "https",
        )
        return ObjectStore(fs=fs, base=settings.s3_bucket, scheme="s3://")

    root = Path(settings.object_store_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return ObjectStore(fs=pafs.LocalFileSystem(), base=str(root), scheme="")


__all__ = ["ObjectStore", "get_object_store"]
