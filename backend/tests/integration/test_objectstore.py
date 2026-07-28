"""Object store for the data lake (QV-067) — local-fs round-trip + S3 offline construction.

The local backend is exercised for real; the S3/MinIO backend is only *constructed* from settings +
its paths asserted (no network) — the live round-trip is deferred with Docker/AWS.
Gated on the optional ``[lake]`` extra; runs in the ``backend-rls`` job (which installs it).
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("pyarrow")
pytestmark = pytest.mark.integration

from quantvista.core.config import Settings  # noqa: E402
from quantvista.core.objectstore import get_object_store  # noqa: E402


def _local_settings(tmp: Path) -> Settings:
    return Settings(object_store_backend="local", object_store_root=str(tmp))


def test_partition_paths(tmp_path: Path) -> None:
    store = get_object_store(_local_settings(tmp_path))
    assert store.partition_dir("NSE", "daily_prices", 2024, 1).endswith("/NSE/daily_prices/2024/01")
    assert store.partition_file("NSE", "daily_prices", 2024, 3).endswith("/2024/03/part.parquet")
    assert store.read_glob("NSE", "daily_prices").endswith("/NSE/daily_prices/*/*/part.parquet")


def test_local_roundtrip_and_table_exists(tmp_path: Path) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    store = get_object_store(_local_settings(tmp_path))
    assert store.table_exists("NSE", "daily_prices") is False  # nothing exported yet

    pdir = store.partition_dir("NSE", "daily_prices", 2024, 1)
    store.fs.create_dir(pdir, recursive=True)
    pq.write_table(
        pa.table({"x": pa.array([1, 2, 3])}),
        store.partition_file("NSE", "daily_prices", 2024, 1),
        filesystem=store.fs,
    )
    assert store.table_exists("NSE", "daily_prices") is True
    assert Path(store.partition_file("NSE", "daily_prices", 2024, 1)).exists()


def test_s3_store_constructs_offline() -> None:
    # The S3/MinIO backend is real code, validated without connecting (mirrors QV-008 Terraform).
    settings = Settings(
        object_store_backend="s3",
        s3_endpoint_url="http://localhost:9000",
        s3_bucket="quantvista-local",
    )
    store = get_object_store(settings)
    assert store.scheme == "s3://"
    assert store.read_glob("NSE", "daily_prices") == (
        "s3://quantvista-local/NSE/daily_prices/*/*/part.parquet"
    )
