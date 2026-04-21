#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import subprocess
import math
import shutil
import sys
import tempfile
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from serato_stems import SeratoStemsFile, StemChunk, build_stems_file, parse_stems_file

XOR_KEY = 0x26
DEFAULT_VERSION = (1, 2)
DEFAULT_CHUNK_ORDER = [0, 3, 2, 1]

ROLE_TO_INDEX = {
    "vocals": 0,
    "bass": 1,
    "drums": 2,
    "melody": 3,
}


def _tool_path(name: str) -> Optional[str]:
    repo_bin = Path(__file__).resolve().parent.parent / "bin" / name
    if repo_bin.exists():
        return str(repo_bin)
    return shutil.which(name)


def _ffmpeg_path() -> Optional[str]:
    return _tool_path("ffmpeg")


def _injector_work_root() -> Path:
    root = Path.home() / "Music" / "Custom Stem Injector"
    root.mkdir(parents=True, exist_ok=True)
    return root


@dataclass
class AudioMeta:
    sample_rate: int
    sample_frames_total: int


def _syncsafe_to_int(b4: bytes) -> int:
    return ((b4[0] & 0x7F) << 21) | ((b4[1] & 0x7F) << 14) | ((b4[2] & 0x7F) << 7) | (b4[3] & 0x7F)


def strip_mp3_tags_and_align_frames(data: bytes) -> bytes:
    start = 0
    end = len(data)

    if len(data) >= 10 and data[:3] == b"ID3":
        tag_size = _syncsafe_to_int(data[6:10])
        footer = 10 if (data[5] & 0x10) else 0
        start = min(len(data), 10 + tag_size + footer)

    if end - start >= 128 and data[end - 128 : end - 125] == b"TAG":
        end -= 128

    core = data[start:end]

    sync_offset = -1
    for i in range(len(core) - 1):
        if core[i] == 0xFF and (core[i + 1] & 0xE0) == 0xE0:
            sync_offset = i
            break
    if sync_offset < 0:
        raise ValueError("Could not find MPEG frame sync after MP3 tag stripping")
    return core[sync_offset:]


def mp3_file_to_payload(index: int, path: Path) -> bytes:
    mp3_frames = load_serato_compatible_mp3_frames(path)
    body = bytes(b ^ XOR_KEY for b in mp3_frames)
    return index.to_bytes(4, "big") + body


_BITRATE_KBPS = {
    # MPEG1 Layer III
    (3, 1): {
        1: 32, 2: 40, 3: 48, 4: 56, 5: 64, 6: 80, 7: 96,
        8: 112, 9: 128, 10: 160, 11: 192, 12: 224, 13: 256, 14: 320,
    },
    # MPEG2/2.5 Layer III
    (2, 1): {
        1: 8, 2: 16, 3: 24, 4: 32, 5: 40, 6: 48, 7: 56,
        8: 64, 9: 80, 10: 96, 11: 112, 12: 128, 13: 144, 14: 160,
    },
    (0, 1): {
        1: 8, 2: 16, 3: 24, 4: 32, 5: 40, 6: 48, 7: 56,
        8: 64, 9: 80, 10: 96, 11: 112, 12: 128, 13: 144, 14: 160,
    },
}

_SAMPLE_RATES = {
    3: {0: 44100, 1: 48000, 2: 32000},  # MPEG1
    2: {0: 22050, 1: 24000, 2: 16000},  # MPEG2
    0: {0: 11025, 1: 12000, 2: 8000},   # MPEG2.5
}


def _first_mp3_frame_props(mp3_bytes: bytes) -> tuple[int, int, int] | None:
    if len(mp3_bytes) < 4:
        return None
    h = int.from_bytes(mp3_bytes[:4], "big")
    if ((h >> 21) & 0x7FF) != 0x7FF:
        return None
    version_id = (h >> 19) & 0x3
    layer_desc = (h >> 17) & 0x3
    bitrate_idx = (h >> 12) & 0xF
    sample_idx = (h >> 10) & 0x3
    channel_mode = (h >> 6) & 0x3
    if version_id == 1 or layer_desc != 1 or bitrate_idx in (0, 15) or sample_idx == 3:
        return None
    bitrate = _BITRATE_KBPS.get((version_id, layer_desc), {}).get(bitrate_idx)
    sample_rate = _SAMPLE_RATES.get(version_id, {}).get(sample_idx)
    if not bitrate or not sample_rate:
        return None
    return bitrate, sample_rate, channel_mode


def _transcode_mp3_serato_compatible(path: Path) -> Optional[bytes]:
    return _transcode_mp3(path, sample_rate=44100, bitrate_kbps=320, channels=2)


def _transcode_mp3(
    path: Path,
    *,
    sample_rate: int,
    bitrate_kbps: int,
    channels: int,
    gain_db: float = 0.0,
) -> Optional[bytes]:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory(prefix="stems_norm_") as td:
        out = Path(td) / "norm.mp3"
        for encoder in ("libmp3lame", "mp3"):
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(path),
                "-vn",
                "-ac",
                str(channels),
                "-ar",
                str(sample_rate),
            ]
            if abs(gain_db) > 1e-6:
                # Apply fixed gain with limiter to avoid clipping on hot source stems.
                cmd += ["-af", f"volume={gain_db:.2f}dB,alimiter=limit=0.98"]
            cmd += [
                "-c:a",
                encoder,
                "-b:a",
                f"{int(bitrate_kbps)}k",
                "-write_xing",
                "0",
                "-id3v2_version",
                "0",
                "-map_metadata",
                "-1",
                str(out),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                return out.read_bytes()
            except subprocess.CalledProcessError:
                continue
        return None


def _copy_id3_and_art_from_source_ffmpeg(source: Path, target: Path) -> Optional[str]:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return "metadata/art copy skipped: ffmpeg not found"

    with tempfile.TemporaryDirectory(prefix="stems_meta_") as td:
        out = Path(td) / "with_meta.mp3"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(target),
            "-i",
            str(source),
            "-map",
            "0:a",
            "-map",
            "1:v?",
            "-c:a",
            "copy",
            "-c:v",
            "copy",
            "-map_metadata",
            "1",
            "-id3v2_version",
            "3",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            target.write_bytes(out.read_bytes())
            return None
        except subprocess.CalledProcessError:
            return f"metadata/art copy failed for prepared base: {target}"


def _copy_id3_text_from_source_mutagen(source: Path, target: Path) -> Optional[str]:
    if source.suffix.lower() != ".mp3":
        return f"metadata/art copy via mutagen skipped (source is not MP3): {source.name}"

    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
    except ModuleNotFoundError:
        pydeps = Path(__file__).resolve().parent / "_pydeps"
        if pydeps.exists() and str(pydeps) not in sys.path:
            sys.path.insert(0, str(pydeps))
        try:
            from mutagen.id3 import ID3, ID3NoHeaderError
        except Exception:
            return "metadata/art copy via mutagen unavailable"

    try:
        src_tags = ID3(str(source))
    except ID3NoHeaderError:
        return f"metadata/art copy skipped: source has no ID3 tags ({source.name})"
    except Exception:
        return f"metadata/art copy via mutagen failed reading source: {source.name}"

    try:
        dst_tags = ID3(str(target))
        dst_tags.clear()
    except ID3NoHeaderError:
        dst_tags = ID3()
    except Exception:
        dst_tags = ID3()

    def _is_serato_runtime_frame(frame: object) -> bool:
        frame_id = str(getattr(frame, "FrameID", "") or "").upper()
        if frame_id in {"GEOB", "PRIV"}:
            return True
        marker_parts: list[str] = [frame_id]
        for attr in ("owner", "desc", "text"):
            value = getattr(frame, attr, None)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                marker_parts.extend(str(v) for v in value)
            else:
                marker_parts.append(str(value))
        marker_blob = " ".join(marker_parts).lower()
        if "serato" in marker_blob:
            return True
        return False

    def _is_textual_frame(frame: object) -> bool:
        frame_id = str(getattr(frame, "FrameID", "") or "").upper()
        safe_text_frame_ids = {
            "TALB",  # album
            "TPE1",  # lead artist
            "TPE2",  # album artist
            "TIT2",  # title
            "TIT1",  # grouping/content group
            "TCON",  # genre
            "TKEY",  # key
            "TDRC",  # year/date
            "TRCK",  # track number
            "TPOS",  # disc number
            "TCOM",  # composer
            "TPUB",  # publisher
            "TCMP",  # compilation flag
            "TSRC",  # ISRC
            "TENC",  # encoded by
            "TCOP",  # copyright
            "TEXT",  # lyricist/text writer
            "TLAN",  # language
            "TSSE",  # encoder settings
            "TXXX",  # excluded below
            "COMM",  # excluded below
            "TBPM",  # excluded below
        }
        return frame_id in safe_text_frame_ids

    def _is_excluded_text_frame(frame: object) -> bool:
        frame_id = str(getattr(frame, "FrameID", "") or "").upper()
        if frame_id == "TBPM":
            return True
        if frame_id in {"TXXX", "COMM"}:
            return True
        marker_parts: list[str] = [frame_id]
        for attr in ("desc", "owner", "text"):
            value = getattr(frame, attr, None)
            if value is None:
                continue
            if isinstance(value, (list, tuple)):
                marker_parts.extend(str(v) for v in value)
            else:
                marker_parts.append(str(value))
        marker_blob = " ".join(marker_parts).lower()
        excluded_tokens = (
            "bpm",
            "beatgrid",
            "beat grid",
            "serato_markers",
            "serato markers",
            "hotcue",
            "hot cue",
            "saved loop",
            "loop",
            "cue",
        )
        return any(token in marker_blob for token in excluded_tokens)

    try:
        for frame in src_tags.values():
            if _is_serato_runtime_frame(frame):
                continue
            if not _is_textual_frame(frame):
                continue
            if _is_excluded_text_frame(frame):
                continue
            dst_tags.add(frame)
        dst_tags.save(str(target), v2_version=3)
        return None
    except Exception:
        return f"ID3 text-tag copy via mutagen failed writing target: {target.name}"


def _copy_id3_and_art_from_source(source: Path, target: Path) -> tuple[Optional[str], str]:
    mutagen_warn = _copy_id3_text_from_source_mutagen(source, target)
    if mutagen_warn is None:
        return None, "mutagen_text_only"

    return mutagen_warn, "none"


def load_serato_compatible_mp3_frames(path: Path) -> bytes:
    raw = path.read_bytes()
    cleaned = strip_mp3_tags_and_align_frames(raw)
    props = _first_mp3_frame_props(cleaned)
    if props is not None:
        bitrate, sample_rate, channel_mode = props
        if bitrate == 320 and sample_rate == 44100 and channel_mode in (0, 1):
            return cleaned
    transcoded = _transcode_mp3_serato_compatible(path)
    if transcoded is not None:
        return strip_mp3_tags_and_align_frames(transcoded)
    return cleaned


def load_mp3_frames_matching_template_slot(path: Path, template_payload: bytes) -> bytes:
    if len(template_payload) <= 4:
        return load_serato_compatible_mp3_frames(path)

    tpl_body = bytes(b ^ XOR_KEY for b in template_payload[4:])
    tpl_props = _first_mp3_frame_props(tpl_body)
    if tpl_props is None:
        return load_serato_compatible_mp3_frames(path)

    tpl_bitrate, tpl_sample_rate, tpl_channel_mode = tpl_props

    raw = path.read_bytes()
    cleaned = strip_mp3_tags_and_align_frames(raw)
    in_props = _first_mp3_frame_props(cleaned)
    if in_props is not None:
        in_bitrate, in_sample_rate, _in_channel_mode = in_props
        if in_bitrate == tpl_bitrate and in_sample_rate == tpl_sample_rate:
            return cleaned

    channels = 1 if tpl_channel_mode == 3 else 2
    transcoded = _transcode_mp3(
        path,
        sample_rate=tpl_sample_rate,
        bitrate_kbps=tpl_bitrate,
        channels=channels,
    )
    if transcoded is not None:
        return strip_mp3_tags_and_align_frames(transcoded)
    return cleaned


def _mp3_frame_length(header4: bytes) -> int | None:
    if len(header4) < 4:
        return None
    h = int.from_bytes(header4, "big")
    if ((h >> 21) & 0x7FF) != 0x7FF:
        return None

    version_id = (h >> 19) & 0x3  # 3=MPEG1,2=MPEG2,0=MPEG2.5
    layer_desc = (h >> 17) & 0x3  # 1=Layer III
    bitrate_idx = (h >> 12) & 0xF
    sample_idx = (h >> 10) & 0x3
    padding = (h >> 9) & 0x1

    if version_id == 1 or layer_desc != 1 or bitrate_idx in (0, 15) or sample_idx == 3:
        return None

    bitrate_table = _BITRATE_KBPS.get((version_id, layer_desc))
    sample_table = _SAMPLE_RATES.get(version_id)
    if not bitrate_table or not sample_table:
        return None

    bitrate = bitrate_table.get(bitrate_idx)
    sample_rate = sample_table.get(sample_idx)
    if not bitrate or not sample_rate:
        return None

    if version_id == 3:
        # MPEG1 Layer III
        frame_len = int((144000 * bitrate) / sample_rate) + padding
    else:
        # MPEG2/2.5 Layer III
        frame_len = int((72000 * bitrate) / sample_rate) + padding
    return frame_len if frame_len > 0 else None


def _samples_per_frame(header4: bytes) -> int | None:
    if len(header4) < 4:
        return None
    h = int.from_bytes(header4, "big")
    if ((h >> 21) & 0x7FF) != 0x7FF:
        return None
    version_id = (h >> 19) & 0x3
    layer_desc = (h >> 17) & 0x3
    if version_id == 1 or layer_desc != 1:
        return None
    return 1152 if version_id == 3 else 576


def extract_mp3_prefix_frames(mp3_bytes: bytes, frames: int = 4) -> bytes:
    """Return first N valid MP3 frames from a cleaned MP3 stream."""
    pos = 0
    out = bytearray()
    count = 0
    n = len(mp3_bytes)

    while pos + 4 <= n and count < frames:
        if not (mp3_bytes[pos] == 0xFF and (mp3_bytes[pos + 1] & 0xE0) == 0xE0):
            break
        flen = _mp3_frame_length(mp3_bytes[pos : pos + 4])
        if flen is None or pos + flen > n:
            break
        out.extend(mp3_bytes[pos : pos + flen])
        pos += flen
        count += 1

    if count == 0:
        raise ValueError("Could not extract any valid MP3 frames for muted payload")
    return bytes(out)


def _iter_mp3_frames(mp3_bytes: bytes):
    pos = 0
    n = len(mp3_bytes)
    while pos + 4 <= n:
        if not (mp3_bytes[pos] == 0xFF and (mp3_bytes[pos + 1] & 0xE0) == 0xE0):
            break
        flen = _mp3_frame_length(mp3_bytes[pos : pos + 4])
        if flen is None or pos + flen > n:
            break
        yield mp3_bytes[pos : pos + flen]
        pos += flen


def _mp3_stream_len(mp3_bytes: bytes) -> int:
    pos = 0
    n = len(mp3_bytes)
    while pos + 4 <= n:
        if not (mp3_bytes[pos] == 0xFF and (mp3_bytes[pos + 1] & 0xE0) == 0xE0):
            break
        flen = _mp3_frame_length(mp3_bytes[pos : pos + 4])
        if flen is None or pos + flen > n:
            break
        pos += flen
    return pos


def _pick_audio_frame(frames: list[bytes]) -> bytes | None:
    for fr in frames:
        head = fr[:256]
        if b"Xing" in head or b"Info" in head or b"LAME" in head:
            continue
        return fr
    return frames[0] if frames else None


def normalize_mp3_to_total_samples(mp3_bytes: bytes, total_samples: int) -> bytes:
    """Trim/pad MP3 frame stream to cover target total samples."""
    frames = list(_iter_mp3_frames(mp3_bytes))
    if not frames:
        raise ValueError("Could not parse MP3 frames for normalization")

    def frame_samples(fr: bytes) -> int:
        return _samples_per_frame(fr[:4]) or 1152

    out = []
    acc = 0
    for fr in frames:
        out.append(fr)
        acc += frame_samples(fr)
        if acc >= total_samples:
            break

    if acc < total_samples:
        pad_fr = None
        for fr in reversed(frames):
            head = fr[:256]
            if b"Xing" in head or b"Info" in head or b"LAME" in head:
                continue
            pad_fr = fr
            break
        if pad_fr is None:
            pad_fr = frames[-1]

        pad_samples = frame_samples(pad_fr)
        while acc < total_samples:
            out.append(pad_fr)
            acc += pad_samples

    return b"".join(out)


def make_full_length_muted_payload(index: int, source_mp3_path: Path, total_samples: int) -> bytes:
    """Build full-duration, valid MP3 payload using repeated safe frame.

    This keeps Serato from regenerating while making non-target slots effectively inert.
    """
    cleaned = load_serato_compatible_mp3_frames(source_mp3_path)

    frames = list(_iter_mp3_frames(cleaned))
    if not frames:
        raise ValueError("Could not parse MP3 frames for muted payload generation")

    # Prefer an audio frame (avoid Xing/Info/LAME metadata frame if present).
    safe = None
    for fr in frames[:32]:
        head = fr[:256]
        if b"Xing" in head or b"Info" in head or b"LAME" in head:
            continue
        safe = fr
        break
    if safe is None:
        safe = frames[min(1, len(frames) - 1)]

    spf = _samples_per_frame(safe[:4]) or 1152
    need = max(1, int(math.ceil(total_samples / spf)))
    stream = safe * need
    body = bytes(b ^ XOR_KEY for b in stream)
    return index.to_bytes(4, "big") + body


def mp3_file_to_payload_with_target(index: int, path: Path, total_samples: int) -> bytes:
    cleaned = load_serato_compatible_mp3_frames(path)
    normalized = normalize_mp3_to_total_samples(cleaned, total_samples)
    body = bytes(b ^ XOR_KEY for b in normalized)
    return index.to_bytes(4, "big") + body


def mp3_file_to_payload_with_target_and_lead_delay(
    index: int,
    path: Path,
    total_samples: int,
    delay_samples: int,
    sample_rate: int,
) -> bytes:
    cleaned = load_serato_compatible_mp3_frames(path)
    if delay_samples > 0:
        frames = list(_iter_mp3_frames(cleaned))
        if frames:
            spf = _samples_per_frame(frames[0][:4]) or 1152
            delay_frames = max(1, int(math.ceil(delay_samples / float(spf))))

            lead = None
            silent_mp3 = _generate_silent_mp3(delay_frames * spf, sample_rate)
            if silent_mp3 is not None:
                try:
                    silent_cleaned = strip_mp3_tags_and_align_frames(silent_mp3)
                    silent_frames = list(_iter_mp3_frames(silent_cleaned))
                    lead = _pick_audio_frame(silent_frames)
                except Exception:
                    lead = None
            if lead is None:
                lead = _pick_audio_frame(frames) or frames[0]

            cleaned = b"".join([lead] * delay_frames + frames)

    normalized = normalize_mp3_to_total_samples(cleaned, total_samples)
    body = bytes(b ^ XOR_KEY for b in normalized)
    return index.to_bytes(4, "big") + body


def mp3_file_to_payload_with_exact_body_len(index: int, path: Path, target_body_len: int) -> bytes:
    """Encode MP3 to Serato payload body with exact byte length (template-compatible)."""
    cleaned = load_serato_compatible_mp3_frames(path)
    return mp3_frames_to_payload_with_exact_body_len(index, cleaned, target_body_len)


def mp3_frames_to_payload_with_exact_body_len(
    index: int,
    cleaned: bytes,
    target_body_len: int,
    template_body: bytes | None = None,
    template_audio_len: int | None = None,
) -> bytes:
    if template_body is not None and len(template_body) == target_body_len:
        out = bytearray(template_body)
        max_n = template_audio_len if template_audio_len is not None else target_body_len
        n = min(len(cleaned), max_n, target_body_len)
        out[:n] = cleaned[:n]
        out = bytes(out)
    elif len(cleaned) >= target_body_len:
        out = cleaned[:target_body_len]
    else:
        # Keep Serato-style trailing fill value observed in generated files.
        out = cleaned + (b"\x8c" * (target_body_len - len(cleaned)))
    body = bytes(b ^ XOR_KEY for b in out)
    return index.to_bytes(4, "big") + body


def mp3_file_to_payload_with_exact_body_len_and_lead_delay(
    index: int,
    path: Path,
    target_body_len: int,
    delay_samples: int,
    sample_rate: int,
) -> bytes:
    """Template-compatible payload with optional leading delay frames."""
    cleaned = load_serato_compatible_mp3_frames(path)
    return mp3_frames_to_payload_with_exact_body_len_and_lead_delay(
        index=index,
        cleaned=cleaned,
        target_body_len=target_body_len,
        delay_samples=delay_samples,
        sample_rate=sample_rate,
    )


def mp3_frames_to_payload_with_exact_body_len_and_lead_delay(
    *,
    index: int,
    cleaned: bytes,
    target_body_len: int,
    delay_samples: int,
    sample_rate: int,
    template_body: bytes | None = None,
    template_audio_len: int | None = None,
) -> bytes:
    frames = list(_iter_mp3_frames(cleaned))
    if not frames:
        raise ValueError("Could not parse MP3 frames for delayed fixed-length payload build")

    if delay_samples > 0:
        spf = _samples_per_frame(frames[0][:4]) or 1152
        delay_frames = max(1, int(math.ceil(delay_samples / float(spf))))
        lead = None
        silent_mp3 = _generate_silent_mp3(delay_frames * spf, sample_rate)
        if silent_mp3 is not None:
            try:
                silent_cleaned = strip_mp3_tags_and_align_frames(silent_mp3)
                silent_frames = list(_iter_mp3_frames(silent_cleaned))
                lead = _pick_audio_frame(silent_frames)
            except Exception:
                lead = None
        if lead is None:
            lead = _pick_audio_frame(frames) or frames[0]
        stream = b"".join([lead] * delay_frames + frames)
    else:
        stream = cleaned

    if template_body is not None and len(template_body) == target_body_len:
        out = bytearray(template_body)
        max_n = template_audio_len if template_audio_len is not None else target_body_len
        n = min(len(stream), max_n, target_body_len)
        out[:n] = stream[:n]
        out = bytes(out)
    elif len(stream) >= target_body_len:
        out = stream[:target_body_len]
    else:
        out = stream + (b"\x8c" * (target_body_len - len(stream)))
    body = bytes(b ^ XOR_KEY for b in out)
    return index.to_bytes(4, "big") + body


def build_silent_payload_from_template(
    *,
    index: int,
    template_payload: bytes,
    total_samples: int,
    sample_rate: int,
) -> bytes:
    target_len = max(0, len(template_payload) - 4)
    tpl_body = bytes(b ^ XOR_KEY for b in template_payload[4:]) if target_len > 0 else b""

    silent_mp3 = _generate_silent_mp3(total_samples, sample_rate)
    if silent_mp3 is None:
        return template_payload

    with tempfile.TemporaryDirectory(prefix="stems_silent_tpl_") as td:
        sp = Path(td) / "silent.mp3"
        sp.write_bytes(silent_mp3)
        cleaned = load_mp3_frames_matching_template_slot(sp, template_payload)

    normalized = normalize_mp3_to_total_samples(cleaned, total_samples)
    # For mute slots, avoid overlaying into template audio bytes; preserve only sizing.
    return mp3_frames_to_payload_with_exact_body_len(
        index=index,
        cleaned=normalized,
        target_body_len=target_len,
        template_body=None,
    )


def _generate_silent_mp3(total_samples: int, sample_rate: int) -> Optional[bytes]:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return None

    duration = max(0.01, total_samples / float(sample_rate))
    with tempfile.TemporaryDirectory(prefix="stems_silence_") as td:
        out = Path(td) / "silence.mp3"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r={sample_rate}:cl=stereo",
            "-t",
            f"{duration:.6f}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
            "-write_xing",
            "0",
            "-id3v2_version",
            "0",
            "-map_metadata",
            "-1",
            str(out),
        ]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            return out.read_bytes()
        except subprocess.CalledProcessError:
            return None



def sidecar_for_audio(audio_path: Path) -> Path:
    return audio_path.with_name(f"{audio_path.stem}.1.2.serato-stems")


def read_audio_meta(audio_path: Path) -> AudioMeta:
    cmd = ["afinfo", str(audio_path)]
    p = subprocess.run(cmd, check=True, capture_output=True, text=True)
    out = p.stdout

    rate_match = re.search(r"Data format:\s+\d+ ch,\s+(\d+) Hz", out)
    if not rate_match:
        raise ValueError("Could not parse sample rate from afinfo output")
    sample_rate = int(rate_match.group(1))

    # Prefer explicit packet-based frame accounting when present (common for MP3).
    packets_match = re.search(r"audio packets:\s*(\d+)", out, re.IGNORECASE)
    fpp_match = re.search(r"(\d+)\s*frames/packet", out, re.IGNORECASE)
    if packets_match and fpp_match:
        sample_frames_total = int(packets_match.group(1)) * int(fpp_match.group(1))
    else:
        # Example (AAC): audio ... = 12286080
        frames_match = re.search(r"=\s*(\d+)\s*$", out, re.MULTILINE)
        if frames_match:
            sample_frames_total = int(frames_match.group(1))
        else:
            # Fallback from estimated duration when afinfo omits explicit frame total.
            dur_match = re.search(r"estimated duration:\s*([0-9.]+)\s*sec", out, re.IGNORECASE)
            if not dur_match:
                raise ValueError("Could not parse total sample frames from afinfo output")
            sample_frames_total = int(round(float(dur_match.group(1)) * sample_rate))

    return AudioMeta(sample_rate=sample_rate, sample_frames_total=sample_frames_total)


def build_sidecar(
    *,
    base_audio: Path,
    vocals: Path,
    bass: Optional[Path],
    drums: Optional[Path],
    melody: Optional[Path],
    instrumental: Optional[Path],
    two_stem_strategy: str = "compat",
    vocals_delay_samples_override: Optional[int] = None,
    vocals_delay_ms_override: Optional[float] = None,
    template_sidecar_override: Optional[Path] = None,
    use_template: bool = True,
    overwrite: bool = True,
) -> dict:
    out_path = sidecar_for_audio(base_audio)
    two_stem_mode = instrumental is not None

    warnings: list[str] = []

    existing_template = out_path if (use_template and out_path.exists()) else None
    template_source = "base"
    if use_template and template_sidecar_override and template_sidecar_override.exists():
        if existing_template is None or template_sidecar_override.resolve() != existing_template.resolve():
            existing_template = template_sidecar_override
            template_source = "override"
    tpl = None
    timing_mismatch = False
    base_meta = None
    if existing_template:
        tpl = parse_stems_file(existing_template)
        major, minor = tpl.major, tpl.minor
        chunk_order = [c.index for c in tpl.chunks]
        # Template-lock timing in template mode to maximize Serato acceptance.
        sample_rate = tpl.sample_rate
        sample_frames = tpl.sample_frames
        try:
            base_meta = read_audio_meta(base_audio)
            timing_mismatch = (
                base_meta.sample_rate != tpl.sample_rate
                or base_meta.sample_frames_total != tpl.sample_frames
            )
        except Exception:
            timing_mismatch = False
    else:
        meta = read_audio_meta(base_audio)
        major, minor = DEFAULT_VERSION
        chunk_order = DEFAULT_CHUNK_ORDER[:]
        sample_rate = meta.sample_rate
        sample_frames = meta.sample_frames_total

    payloads: dict[int, bytes] = {}
    stem_delay_samples = 0
    if vocals_delay_ms_override is not None:
        stem_delay_samples = max(
            0, int(round((float(vocals_delay_ms_override) / 1000.0) * float(sample_rate)))
        )
    elif vocals_delay_samples_override is not None:
        stem_delay_samples = max(0, int(vocals_delay_samples_override))
    delayed_slot_indexes = (
        {ROLE_TO_INDEX["vocals"], ROLE_TO_INDEX["drums"]}
        if two_stem_mode
        else set(ROLE_TO_INDEX.values())
    )

    if existing_template:
        # Compatibility-first path: historically most accepted by Serato when template exists.
        by_idx_tpl = {c.index: c for c in tpl.chunks}

        def encode_slot(idx: int, p: Path) -> bytes:
            target_len = len(by_idx_tpl[idx].payload) - 4
            tpl_body = bytes(b ^ XOR_KEY for b in by_idx_tpl[idx].payload[4:])
            tpl_audio_len = _mp3_stream_len(tpl_body)
            tpl_props = _first_mp3_frame_props(tpl_body)
            slot_cleaned = load_mp3_frames_matching_template_slot(p, by_idx_tpl[idx].payload)
            slot_props = _first_mp3_frame_props(slot_cleaned)
            if tpl_props is not None and slot_props is not None:
                if tpl_props[:2] != slot_props[:2]:
                    warnings.append(
                        f"slot {idx}: template codec {tpl_props[0]}kbps@{tpl_props[1]}Hz differs from source codec {slot_props[0]}kbps@{slot_props[1]}Hz after normalization"
                    )

            if idx in delayed_slot_indexes and stem_delay_samples > 0:
                return mp3_frames_to_payload_with_exact_body_len_and_lead_delay(
                    index=idx,
                    cleaned=slot_cleaned,
                    target_body_len=target_len,
                    delay_samples=stem_delay_samples,
                    sample_rate=sample_rate,
                    template_body=tpl_body if len(tpl_body) == target_len else None,
                    template_audio_len=tpl_audio_len,
                )

            slot_normalized = normalize_mp3_to_total_samples(slot_cleaned, sample_frames)
            if len(slot_normalized) > target_len:
                warnings.append(
                    f"slot {idx}: source body {len(slot_normalized)} > template body {target_len}; overlaying into template body for Serato compatibility"
                )
            return mp3_frames_to_payload_with_exact_body_len(
                idx,
                slot_normalized,
                target_len,
                template_body=tpl_body if len(tpl_body) == target_len else None,
                template_audio_len=tpl_audio_len,
            )
    else:
        # When creating a new sidecar from scratch, align timeline to base sample frame count.
        def encode_slot(idx: int, p: Path) -> bytes:
            if idx in delayed_slot_indexes and stem_delay_samples > 0:
                return mp3_file_to_payload_with_target_and_lead_delay(
                    idx, p, sample_frames, stem_delay_samples, sample_rate
                )
            return mp3_file_to_payload_with_target(idx, p, sample_frames)

    payloads[ROLE_TO_INDEX["vocals"]] = encode_slot(ROLE_TO_INDEX["vocals"], vocals)

    if two_stem_mode:
        payloads[ROLE_TO_INDEX["drums"]] = encode_slot(ROLE_TO_INDEX["drums"], instrumental)
        if existing_template:
            by_idx = {c.index: c for c in tpl.chunks}
        else:
            by_idx = {}

        if two_stem_strategy == "mute":
            if existing_template:
                # Template-compatible silence for non-target slots.
                try:
                    payloads[ROLE_TO_INDEX["bass"]] = build_silent_payload_from_template(
                        index=ROLE_TO_INDEX["bass"],
                        template_payload=by_idx[ROLE_TO_INDEX["bass"]].payload,
                        total_samples=sample_frames,
                        sample_rate=sample_rate,
                    )
                    payloads[ROLE_TO_INDEX["melody"]] = build_silent_payload_from_template(
                        index=ROLE_TO_INDEX["melody"],
                        template_payload=by_idx[ROLE_TO_INDEX["melody"]].payload,
                        total_samples=sample_frames,
                        sample_rate=sample_rate,
                    )
                    warnings.append(
                        "two_stem_strategy=mute wrote template-compatible silent bass/melody payloads"
                    )
                except Exception:
                    payloads[ROLE_TO_INDEX["bass"]] = by_idx[ROLE_TO_INDEX["bass"]].payload
                    payloads[ROLE_TO_INDEX["melody"]] = by_idx[ROLE_TO_INDEX["melody"]].payload
                    warnings.append(
                        "two_stem_strategy=mute fallback: failed to build silent bass/melody, kept template payloads"
                    )
            else:
                # Use true generated silence for non-target slots.
                silent_mp3 = _generate_silent_mp3(sample_frames, sample_rate)
                if silent_mp3 is not None:
                    with tempfile.TemporaryDirectory(prefix="stems_mute_") as td:
                        sp = Path(td) / "silent.mp3"
                        sp.write_bytes(silent_mp3)
                        payloads[ROLE_TO_INDEX["bass"]] = encode_slot(ROLE_TO_INDEX["bass"], sp)
                        payloads[ROLE_TO_INDEX["melody"]] = encode_slot(ROLE_TO_INDEX["melody"], sp)
                    warnings.append("two_stem_strategy=mute used ffmpeg-generated silent fillers for bass/melody")
                else:
                    # Last-resort fallback when ffmpeg is unavailable.
                    payloads[ROLE_TO_INDEX["bass"]] = make_full_length_muted_payload(
                        ROLE_TO_INDEX["bass"], instrumental, sample_frames
                    )
                    payloads[ROLE_TO_INDEX["melody"]] = make_full_length_muted_payload(
                        ROLE_TO_INDEX["melody"], instrumental, sample_frames
                    )
                    warnings.append(
                        "two_stem_strategy=mute fallback: ffmpeg not found, used instrumental-derived inert fillers for bass/melody"
                    )
        else:
            # compat: keep existing bass/melody if template exists, else use instrumental.
            if existing_template:
                payloads[ROLE_TO_INDEX["bass"]] = by_idx[ROLE_TO_INDEX["bass"]].payload
                payloads[ROLE_TO_INDEX["melody"]] = by_idx[ROLE_TO_INDEX["melody"]].payload
            else:
                payloads[ROLE_TO_INDEX["bass"]] = encode_slot(ROLE_TO_INDEX["bass"], instrumental)
                payloads[ROLE_TO_INDEX["melody"]] = encode_slot(ROLE_TO_INDEX["melody"], instrumental)
    else:
        assert bass is not None and drums is not None and melody is not None
        payloads[ROLE_TO_INDEX["bass"]] = encode_slot(ROLE_TO_INDEX["bass"], bass)
        payloads[ROLE_TO_INDEX["drums"]] = encode_slot(ROLE_TO_INDEX["drums"], drums)
        payloads[ROLE_TO_INDEX["melody"]] = encode_slot(ROLE_TO_INDEX["melody"], melody)

    chunks = [StemChunk(index=idx, payload=payloads[idx]) for idx in chunk_order]
    model = SeratoStemsFile(
        major=major,
        minor=minor,
        stem_count=4,
        sample_frames=sample_frames,
        sample_rate=sample_rate,
        chunks=chunks,
    )

    data = build_stems_file(model)
    if (not overwrite) and out_path.exists():
        raise FileExistsError(f"Target exists: {out_path}")
    out_path.write_bytes(data)

    report = {
        "base_audio": str(base_audio),
        "output_sidecar": str(out_path),
        "used_existing_template": bool(existing_template),
        "template_source": template_source if existing_template else "none",
        "template_sidecar": str(existing_template) if existing_template else None,
        "mode": "two_stem" if two_stem_mode else "four_stem",
        "two_stem_strategy": two_stem_strategy if two_stem_mode else None,
        "sample_rate": sample_rate,
        "sample_frames": sample_frames,
        "chunk_order": chunk_order,
        "inputs": {
            "vocals": str(vocals),
            "bass": str(bass) if bass else None,
            "drums": str(drums) if drums else None,
            "melody": str(melody) if melody else None,
            "instrumental": str(instrumental) if instrumental else None,
        },
        "stem_delay_samples": stem_delay_samples,
        "vocals_delay_samples": stem_delay_samples,
        "output_bytes": len(data),
    }
    if warnings:
        report["warnings"] = warnings
    if existing_template and timing_mismatch:
        report.setdefault("warnings", []).append(
            f"template timing mismatch detected; kept template timing in output: template={tpl.sample_frames}@{tpl.sample_rate}, base={base_meta.sample_frames_total}@{base_meta.sample_rate}"
        )
    if stem_delay_samples > 0:
        delay_ms = round((stem_delay_samples / float(sample_rate)) * 1000.0, 2)
        delay_scope = "vocals+instrumental" if two_stem_mode else "all four stems"
        report.setdefault("warnings", []).append(
            f"applied stem lead-delay compensation ({delay_scope}): {stem_delay_samples} samples ({delay_ms} ms)"
        )
    report["ffmpeg_path"] = _ffmpeg_path()
    return report


def report_to_json(report: dict) -> str:
    return json.dumps(report, indent=2)


def prepare_files_for_serato(
    *,
    mode: str,
    base_audio: Path,
    vocals: Path,
    bass: Optional[Path],
    drums: Optional[Path],
    melody: Optional[Path],
    instrumental: Optional[Path],
    add_gain_stems: bool = False,
    copy_base_metadata: bool = True,
    preserve_base_mp3_bytes: bool = True,
    expect_template_generation: bool = True,
) -> dict:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; cannot prepare files")

    if mode not in {"two", "four"}:
        raise ValueError("mode must be 'two' or 'four'")

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    prep_root = _injector_work_root() / f"Custom Stems Prep - {base_audio.stem} - {ts}"
    prep_root.mkdir(parents=True, exist_ok=True)

    jobs: list[tuple[str, Path, Path]] = []
    jobs.append(("base", base_audio, prep_root / f"{base_audio.stem}.mp3"))
    jobs.append(("vocals", vocals, prep_root / f"{base_audio.stem} [vocals].mp3"))
    if mode == "two":
        assert instrumental is not None
        jobs.append(("instrumental", instrumental, prep_root / f"{base_audio.stem} [music].mp3"))
    else:
        assert bass is not None and drums is not None and melody is not None
        jobs.append(("bass", bass, prep_root / f"{base_audio.stem} [bass].mp3"))
        jobs.append(("drums", drums, prep_root / f"{base_audio.stem} [drums].mp3"))
        jobs.append(("melody", melody, prep_root / f"{base_audio.stem} [melody].mp3"))

    outputs: dict[str, str] = {}
    warnings: list[str] = []
    stem_gain_db = 4.0 if add_gain_stems else 0.0
    base_audio_preserved = False

    for role, src, dest in jobs:
        # Preserve source MP3 bytes for base track to avoid encoder-delay drift
        # that can shift Serato beatgrid/cue timing.
        if role == "base" and preserve_base_mp3_bytes and src.suffix.lower() == ".mp3":
            shutil.copy2(src, dest)
            outputs[role] = str(dest)
            base_audio_preserved = True
            try:
                _ = read_audio_meta(dest)
            except Exception:
                warnings.append(f"could not read afinfo metadata for prepared file: {dest}")
            continue

        apply_gain = role != "base" and stem_gain_db > 0.0
        trans = _transcode_mp3(
            src,
            sample_rate=44100,
            bitrate_kbps=320,
            channels=2,
            gain_db=stem_gain_db if apply_gain else 0.0,
        )
        if trans is None:
            raise RuntimeError(f"failed to transcode {role}: {src}")
        dest.write_bytes(trans)
        outputs[role] = str(dest)
        try:
            _ = read_audio_meta(dest)
        except Exception:
            warnings.append(f"could not read afinfo metadata for prepared file: {dest}")

    # Copy source ID3/art onto prepared base before Serato template generation.
    base_metadata_from_source = False
    base_metadata_copy_method = "none"
    base_out = Path(outputs.get("base", ""))
    if base_out:
        if base_audio_preserved:
            base_metadata_copy_method = "preserved_mp3"
            warnings.append("prepared base preserved source MP3 bytes to keep beatgrid/cue timing")
        elif not copy_base_metadata:
            base_metadata_copy_method = "disabled"
            warnings.append("skipped source metadata/art copy for prepared base (align mode); using clean base for retagging")
        else:
            # FLAC/other non-MP3 sources can produce metadata/art payloads that are less Serato-stable
            # when mapped onto prepared MP3. Keep prepared base metadata-clean for non-MP3 input.
            if base_audio.suffix.lower() == ".mp3":
                meta_warn, base_metadata_copy_method = _copy_id3_and_art_from_source(base_audio, base_out)
                if meta_warn:
                    warnings.append(meta_warn)
                else:
                    base_metadata_from_source = True
                    try:
                        _ = read_audio_meta(base_out)
                    except Exception:
                        warnings.append(f"could not read afinfo metadata for prepared file after ID3/art copy: {base_out}")
            else:
                warnings.append(
                    f"skipped source metadata/art copy for non-MP3 base ({base_audio.suffix.lower()}); using clean prepared base for Serato stability"
                )

    if expect_template_generation:
        instructions = [
            "Step 1: In Serato, import ONLY the prepared base file path below.",
            "Step 2: Let Serato generate its own .1.2.serato-stems for that prepared base file.",
            "Step 3: Return to Build mode and use the prepared stems from this folder as inputs.",
            "Step 4: Keep filename/path unchanged after Serato creates the template sidecar.",
        ]
    else:
        instructions = [
            "Step 1: Use Build mode with the prepared files from this folder.",
            "Step 2: Sidecar is generated from scratch (no template sidecar required).",
            "Step 3: Re-import the final base audio in Serato and re-analyze/re-cue as needed.",
        ]

    return {
        "mode": mode,
        "prep_folder": str(prep_root),
        "outputs": outputs,
        "instructions": instructions,
        "ffmpeg_path": ffmpeg,
        "warnings": warnings,
        "stem_gain_db": stem_gain_db if add_gain_stems else 0.0,
        "base_metadata_from_source": base_metadata_from_source,
        "base_metadata_copy_method": base_metadata_copy_method,
    }
