#!/usr/bin/env python3
"""Utilities for inspecting and rebuilding Serato .serato-stems files.

Current format understanding for v1.2 files:
- 8-byte magic: b"srtshead"
- 4-byte big-endian header size (expected 16)
- 2-byte big-endian major version
- 2-byte big-endian minor version
- 4-byte big-endian stem count
- 4-byte big-endian sample frames
- 4-byte big-endian sample rate
- Repeated chunks:
  - 4-byte chunk tag: b"stem"
  - 4-byte big-endian payload size
  - payload bytes (first 4 bytes are observed stem index)
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List


MAGIC = b"srtshead"
CHUNK_TAG = b"stem"
HEADER_BYTES = 28


@dataclass
class StemChunk:
    index: int
    payload: bytes


@dataclass
class SeratoStemsFile:
    major: int
    minor: int
    stem_count: int
    sample_frames: int
    sample_rate: int
    chunks: List[StemChunk]


def parse_stems_file(path: Path) -> SeratoStemsFile:
    data = path.read_bytes()
    if len(data) < HEADER_BYTES:
        raise ValueError("File too small to be a Serato stems file")
    if data[:8] != MAGIC:
        raise ValueError("Bad magic, expected 'srtshead'")

    header_size = int.from_bytes(data[8:12], "big")
    major = int.from_bytes(data[12:14], "big")
    minor = int.from_bytes(data[14:16], "big")
    stem_count = int.from_bytes(data[16:20], "big")
    sample_frames = int.from_bytes(data[20:24], "big")
    sample_rate = int.from_bytes(data[24:28], "big")

    if header_size != 16:
        raise ValueError(f"Unsupported header size {header_size}, expected 16")

    pos = HEADER_BYTES
    chunks: List[StemChunk] = []
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError(f"Truncated chunk header at offset {pos}")
        tag = data[pos : pos + 4]
        if tag != CHUNK_TAG:
            raise ValueError(f"Unexpected chunk tag {tag!r} at offset {pos}")
        size = int.from_bytes(data[pos + 4 : pos + 8], "big")
        payload_start = pos + 8
        payload_end = payload_start + size
        if payload_end > len(data):
            raise ValueError(
                f"Chunk at {pos} claims size {size}, beyond end of file"
            )
        payload = data[payload_start:payload_end]
        if len(payload) < 4:
            raise ValueError(f"Chunk at {pos} payload too small to include stem index")
        stem_index = int.from_bytes(payload[:4], "big")
        chunks.append(StemChunk(index=stem_index, payload=payload))
        pos = payload_end

    if pos != len(data):
        raise ValueError("Parser did not end exactly at EOF")
    if len(chunks) != stem_count:
        raise ValueError(
            f"Header stem_count={stem_count} but found {len(chunks)} stem chunks"
        )

    return SeratoStemsFile(
        major=major,
        minor=minor,
        stem_count=stem_count,
        sample_frames=sample_frames,
        sample_rate=sample_rate,
        chunks=chunks,
    )


def build_stems_file(model: SeratoStemsFile) -> bytes:
    if model.stem_count != len(model.chunks):
        raise ValueError("stem_count does not match number of chunks")

    out = bytearray()
    out.extend(MAGIC)
    out.extend((16).to_bytes(4, "big"))
    out.extend(model.major.to_bytes(2, "big"))
    out.extend(model.minor.to_bytes(2, "big"))
    out.extend(model.stem_count.to_bytes(4, "big"))
    out.extend(model.sample_frames.to_bytes(4, "big"))
    out.extend(model.sample_rate.to_bytes(4, "big"))

    for chunk in model.chunks:
        if len(chunk.payload) < 4:
            raise ValueError(f"Payload for stem index {chunk.index} is too small")
        payload_idx = int.from_bytes(chunk.payload[:4], "big")
        if payload_idx != chunk.index:
            chunk = StemChunk(index=chunk.index, payload=chunk.index.to_bytes(4, "big") + chunk.payload[4:])
        out.extend(CHUNK_TAG)
        out.extend(len(chunk.payload).to_bytes(4, "big"))
        out.extend(chunk.payload)

    return bytes(out)


def cmd_info(args: argparse.Namespace) -> int:
    model = parse_stems_file(Path(args.input))
    info = {
        "file": str(args.input),
        "version": f"{model.major}.{model.minor}",
        "stem_count": model.stem_count,
        "sample_frames": model.sample_frames,
        "sample_rate": model.sample_rate,
        "chunks": [
            {
                "chunk_order": i,
                "stem_index": c.index,
                "payload_bytes": len(c.payload),
            }
            for i, c in enumerate(model.chunks)
        ],
    }
    print(json.dumps(info, indent=2))
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    model = parse_stems_file(Path(args.input))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "source": str(args.input),
        "version": {"major": model.major, "minor": model.minor},
        "stem_count": model.stem_count,
        "sample_frames": model.sample_frames,
        "sample_rate": model.sample_rate,
        "chunks": [],
    }

    for i, chunk in enumerate(model.chunks):
        name = f"chunk_{i:02d}_stem_{chunk.index}.bin"
        target = out_dir / name
        target.write_bytes(chunk.payload)
        manifest["chunks"].append(
            {
                "chunk_order": i,
                "stem_index": chunk.index,
                "payload_file": name,
                "payload_bytes": len(chunk.payload),
            }
        )

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Extracted {len(model.chunks)} chunks to {out_dir}")
    return 0


def cmd_repack(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    base = manifest_path.parent
    manifest = json.loads(manifest_path.read_text())

    chunks = []
    for item in manifest["chunks"]:
        payload = (base / item["payload_file"]).read_bytes()
        idx = int(item["stem_index"])
        chunks.append(StemChunk(index=idx, payload=payload))

    model = SeratoStemsFile(
        major=int(manifest["version"]["major"]),
        minor=int(manifest["version"]["minor"]),
        stem_count=int(manifest["stem_count"]),
        sample_frames=int(manifest["sample_frames"]),
        sample_rate=int(manifest["sample_rate"]),
        chunks=chunks,
    )

    out = build_stems_file(model)
    Path(args.output).write_bytes(out)
    print(f"Wrote {args.output} ({len(out)} bytes)")
    return 0


def cmd_swap(args: argparse.Namespace) -> int:
    model = parse_stems_file(Path(args.input))
    if args.order:
        order = [int(x.strip()) for x in args.order.split(",") if x.strip()]
        if len(order) != len(model.chunks):
            raise ValueError(
                f"--order requires {len(model.chunks)} items, got {len(order)}"
            )
        model.chunks = [model.chunks[i] for i in order]

    for mapping in args.replace:
        stem_index_text, payload_file = mapping.split("=", 1)
        stem_index = int(stem_index_text)
        payload = Path(payload_file).read_bytes()

        found = False
        for i, chunk in enumerate(model.chunks):
            if chunk.index == stem_index:
                if len(payload) < 4:
                    raise ValueError(f"Replacement payload for stem {stem_index} is too small")
                model.chunks[i] = StemChunk(index=stem_index, payload=payload)
                found = True
                break
        if not found:
            raise ValueError(f"No chunk with stem index {stem_index} found")

    out = build_stems_file(model)
    Path(args.output).write_bytes(out)
    print(f"Wrote {args.output} ({len(out)} bytes)")
    return 0


def make_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Inspect and rebuild Serato .serato-stems files")
    sub = p.add_subparsers(dest="cmd", required=True)

    info = sub.add_parser("info", help="Print file metadata and chunk layout")
    info.add_argument("input")
    info.set_defaults(func=cmd_info)

    extract = sub.add_parser("extract", help="Extract chunk payloads to a folder")
    extract.add_argument("input")
    extract.add_argument("out_dir")
    extract.set_defaults(func=cmd_extract)

    repack = sub.add_parser("repack", help="Rebuild stems file from manifest.json")
    repack.add_argument("manifest")
    repack.add_argument("output")
    repack.set_defaults(func=cmd_repack)

    swap = sub.add_parser("swap", help="Swap chunk order and/or replace payloads by stem index")
    swap.add_argument("input")
    swap.add_argument("output")
    swap.add_argument(
        "--replace",
        action="append",
        default=[],
        help="Replacement mapping stem_index=payload_file (can be repeated)",
    )
    swap.add_argument(
        "--order",
        help="Comma-separated chunk-order permutation (e.g. 1,0,2,3)",
    )
    swap.set_defaults(func=cmd_swap)

    return p


def main() -> int:
    parser = make_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
