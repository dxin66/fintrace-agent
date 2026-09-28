"""Pinned FinQA downloader with content-hash verification."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

FINQA_REPOSITORY = "https://github.com/czyssrs/FinQA"
FINQA_COMMIT = "0f16e2867befa6840783e58be38c9efb9229d742"
FINQA_SPLITS = {
    "train": "49f237eb9779b569473b26b08048867d04635a7cc39ad6a7a5664c55bb428db6",
    "dev": "a847fb7e0d61a3125a1e2909852df6b89f1ee64d2c5ff1bf689e332214deee51",
    "test": "831dbfb2e785dbc227f895ce3f24046433467aec67b09db2bd6ac7692a8a30dc",
    "private_test": "94dfd3f82aeeb91835da7a161c5d64b9223ed3c630a27457cf5695da2ee24756",
}


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def fetch_commit_files(splits: list[str]) -> dict[str, bytes]:
    """Fetch one pinned Git commit and read dataset blobs without a working checkout."""
    with tempfile.TemporaryDirectory(prefix="fintrace-finqa-") as temporary_directory:
        repository = Path(temporary_directory)
        commands = [
            ["git", "init", "--quiet", str(repository)],
            ["git", "-C", str(repository), "remote", "add", "origin", FINQA_REPOSITORY],
            [
                "git",
                "-C",
                str(repository),
                "fetch",
                "--quiet",
                "--depth",
                "1",
                "origin",
                FINQA_COMMIT,
            ],
        ]
        for command in commands:
            result = subprocess.run(command, capture_output=True, check=False)
            if result.returncode:
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"FinQA Git fetch failed: {error}")
        contents: dict[str, bytes] = {}
        for split in splits:
            result = subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "show",
                    f"FETCH_HEAD:dataset/{split}.json",
                ],
                capture_output=True,
                check=False,
            )
            if result.returncode:
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"failed to read FinQA {split}: {error}")
            contents[split] = result.stdout
        return contents


def fetch_finqa(output_directory: str | Path, splits: list[str]) -> dict[str, object]:
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict[str, object]] = {}
    for split in splits:
        if split not in FINQA_SPLITS:
            raise ValueError(f"unknown FinQA split: {split}")
    contents = fetch_commit_files(splits)
    for split in splits:
        url = (
            "https://raw.githubusercontent.com/czyssrs/FinQA/"
            f"{FINQA_COMMIT}/dataset/{split}.json"
        )
        content = contents[split]
        actual_hash = sha256_bytes(content)
        expected_hash = FINQA_SPLITS[split]
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"FinQA {split} hash mismatch: expected {expected_hash}, got {actual_hash}"
            )
        path = output / f"{split}.json"
        temporary = output / f".{split}.json.tmp"
        temporary.write_bytes(content)
        temporary.replace(path)
        files[split] = {
            "path": str(path),
            "bytes": len(content),
            "sha256": actual_hash,
            "url": url,
        }

    manifest: dict[str, object] = {
        "dataset": "FinQA",
        "repository": FINQA_REPOSITORY,
        "commit": FINQA_COMMIT,
        "files": files,
    }
    manifest_path = output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest
