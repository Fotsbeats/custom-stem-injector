#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
import traceback
import warnings
from pathlib import Path

from stems_injector_core import build_sidecar, prepare_files_for_serato, report_to_json, sidecar_for_audio

ALIGN_ANALYSIS_SR = 11025
ALIGN_ANALYSIS_SECONDS = 90
ALIGN_MAX_SHIFT_SECONDS = 20.0
DEMUCS_MODEL_FILENAME = "htdemucs.yaml"
DEMUCS_WEIGHT_FILENAME = "955717e8-8726e21a.th"
# Keep legacy no-template build path in code, but disabled by default.
LEGACY_NO_TEMPLATE_MODE_ENABLED = True
# Current test workflow: force from-scratch sidecar build (ignore templates).
FORCE_NO_TEMPLATE_WORKFLOW = True
# Kim-2 extraction speed profile (GPU-preferred).
KIM2_GPU_BATCH_SIZE = 8
KIM2_GPU_OVERLAP = 0.25
_PROGRESS_TOKEN = None


def _emit_progress(stage: str, percent: float, message: str = "") -> None:
    try:
        payload = {
            "stage": stage,
            "percent": max(0.0, min(100.0, float(percent))),
            "message": message or "",
        }
        if _PROGRESS_TOKEN is not None:
            payload["token"] = _PROGRESS_TOKEN
        sys.stderr.write(f"PROGRESS_JSON:{json.dumps(payload, separators=(',', ':'))}\n")
        sys.stderr.flush()
    except Exception:
        # Progress updates are best-effort and must never fail core pipeline.
        pass


def _to_path(value: str | None) -> Path | None:
    text = (value or "").strip()
    if not text:
        return None
    return Path(text).expanduser()


def _error(msg: str, code: int = 1) -> int:
    print(json.dumps({"ok": False, "error": msg}))
    return code


def _tool_path(name: str) -> str | None:
    repo_bin = Path(__file__).resolve().parent.parent / "bin" / name
    if repo_bin.exists():
        return str(repo_bin)
    return shutil.which(name)


def _ensure_demucs_runtime_assets(app_root: Path) -> tuple[Path, Path]:
    runtime_dir = app_root / "tools" / "kim2_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    demucs_weight = runtime_dir / DEMUCS_WEIGHT_FILENAME
    demucs_yaml = runtime_dir / DEMUCS_MODEL_FILENAME

    if not demucs_weight.exists():
        raise RuntimeError(
            "Bundled Demucs weights missing. Expected local file: "
            f"{demucs_weight}"
        )

    valid_yaml = False
    if demucs_yaml.exists():
        try:
            content = demucs_yaml.read_text(encoding="utf-8")
            valid_yaml = "models" in content and "955717e8" in content
        except Exception:
            valid_yaml = False
    if not valid_yaml:
        demucs_yaml.write_text("models: ['955717e8']\n", encoding="utf-8")

    checks_dst = runtime_dir / "download_checks.json"
    try:
        checks_obj = json.loads(checks_dst.read_text(encoding="utf-8")) if checks_dst.exists() else {}
    except Exception:
        checks_obj = {}
    if not isinstance(checks_obj, dict):
        checks_obj = {}
    checks_obj.setdefault("vr_download_list", {})
    checks_obj.setdefault("vr_download_vip_list", {})
    checks_obj.setdefault("mdx_download_list", {})
    checks_obj.setdefault("mdx_download_vip_list", {})
    checks_obj.setdefault("demucs_download_list", {})
    checks_obj.setdefault("mdx23c_download_list", {})
    checks_obj.setdefault("mdx23c_download_vip_list", {})
    checks_obj.setdefault("roformer_download_list", {})
    checks_obj["demucs_download_list"]["Demucs v4: htdemucs"] = {
        DEMUCS_WEIGHT_FILENAME: DEMUCS_WEIGHT_FILENAME,
        DEMUCS_MODEL_FILENAME: DEMUCS_MODEL_FILENAME,
    }
    checks_dst.write_text(json.dumps(checks_obj), encoding="utf-8")
    return demucs_weight, demucs_yaml


def _ffmpeg_path() -> str | None:
    return _tool_path("ffmpeg")


def _ffprobe_path() -> str | None:
    return _tool_path("ffprobe")


def _ensure_pydeps() -> Path:
    app_root = Path(__file__).resolve().parent.parent
    pydeps = app_root / "tools" / "_pydeps"
    if not pydeps.exists():
        raise RuntimeError(f"Required Python deps missing: {pydeps}")
    if str(pydeps) not in sys.path:
        sys.path.insert(0, str(pydeps))
    return pydeps


def _injector_work_root() -> Path:
    root = Path.home() / "Music" / "Custom Stem Injector"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _clear_directory_contents(folder: Path) -> None:
    if not folder.exists():
        return
    for child in folder.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


def _cleanup_after_final_copy(base_in_use: Path) -> dict:
    cleanup_report = {
        "extracted_cleared": False,
        "aligned_deleted": False,
        "manual_aligned_deleted": False,
        "prep_deleted": False,
    }
    work_root = _injector_work_root()

    extracted_dir = work_root / "extracted stems"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    _clear_directory_contents(extracted_dir)
    cleanup_report["extracted_cleared"] = True
    cleanup_report["extracted_dir"] = str(extracted_dir)

    aligned_dir = work_root / "aligned stems"
    if aligned_dir.exists() and aligned_dir.is_dir():
        shutil.rmtree(aligned_dir, ignore_errors=True)
        cleanup_report["aligned_deleted"] = True
        cleanup_report["aligned_dir"] = str(aligned_dir)
    else:
        cleanup_report["aligned_dir"] = str(aligned_dir)

    manual_aligned_dir = work_root / "manual aligned stems"
    if manual_aligned_dir.exists() and manual_aligned_dir.is_dir():
        shutil.rmtree(manual_aligned_dir, ignore_errors=True)
        cleanup_report["manual_aligned_deleted"] = True
        cleanup_report["manual_aligned_dir"] = str(manual_aligned_dir)
    else:
        cleanup_report["manual_aligned_dir"] = str(manual_aligned_dir)

    prep_dir = base_in_use.parent
    if (
        prep_dir.exists()
        and prep_dir.is_dir()
        and prep_dir.parent == work_root
        and prep_dir.name.startswith("Custom Stems Prep - ")
    ):
        shutil.rmtree(prep_dir, ignore_errors=True)
        cleanup_report["prep_deleted"] = True
        cleanup_report["prep_deleted_path"] = str(prep_dir)

    return cleanup_report


def _to_mp3(input_audio: Path, output_mp3: Path) -> None:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; cannot convert extracted stems to MP3")
    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(input_audio),
        "-vn",
        "-ar",
        "44100",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "320k",
        "-cutoff",
        "22050",
        str(output_mp3),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg MP3 conversion failed for {input_audio.name}: {err}")


def _mix_to_mp3(inputs: list[Path], output_mp3: Path) -> None:
    if not inputs:
        raise RuntimeError("No input stems provided for mixdown")
    if len(inputs) == 1:
        _to_mp3(inputs[0], output_mp3)
        return
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; cannot mix extracted stems")
    output_mp3.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    for stem in inputs:
        cmd.extend(["-i", str(stem)])
    cmd.extend(
        [
            "-filter_complex",
            f"amix=inputs={len(inputs)}:duration=longest:normalize=0,alimiter=limit=0.98",
            "-vn",
            "-ar",
            "44100",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "320k",
            "-cutoff",
            "22050",
            str(output_mp3),
        ]
    )
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"ffmpeg mixdown failed for {output_mp3.name}: {err}")


def _run_capture(cmd: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)


def _run_quiet(cmd: list[str], timeout: float | None = None) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)


def _normalized(signal):
    import numpy as np

    x = signal.astype("float32", copy=False)
    x = x - float(np.mean(x))
    rms = float(np.sqrt(np.mean(x * x)))
    if rms > 1e-8:
        x = x / rms
    return x


def _envelope(signal, sr: int, envelope_hz: int = 200):
    import numpy as np

    step = max(1, int(sr / max(1, envelope_hz)))
    win = max(1, int(sr * 0.03))
    mag = np.abs(signal.astype("float32", copy=False))
    if win > 1:
        kernel = np.ones(win, dtype=np.float32) / float(win)
        mag = np.convolve(mag, kernel, mode="same")
    env = mag[::step]
    return _normalized(env), step


def _estimate_lag_with_score(reference, target, sr: int, max_shift_seconds: float) -> tuple[int, float]:
    import numpy as np

    a, step_a = _envelope(reference, sr=sr)
    b, step_b = _envelope(target, sr=sr)
    step = max(step_a, step_b)

    n = len(a) + len(b) - 1
    nfft = 1 << (n - 1).bit_length()
    corr_fft = np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)
    corr = np.concatenate((corr_fft[-(len(b) - 1) :], corr_fft[: len(a)]))
    lags_env = np.arange(-(len(b) - 1), len(a), dtype=np.int64)

    max_shift_env = max(1, int((max(0.5, float(max_shift_seconds)) * sr) / step))
    mask = (lags_env >= -max_shift_env) & (lags_env <= max_shift_env)
    if mask.any():
        corr_view = corr[mask]
        lags_view = lags_env[mask]
    else:
        corr_view = corr
        lags_view = lags_env

    best_idx = int(np.argmax(corr_view))
    peak = float(corr_view[best_idx]) if corr_view.size else 0.0
    lag_samples = int(lags_view[best_idx]) * step
    max_shift_samples = int(max(0.5, float(max_shift_seconds)) * sr)
    lag_samples = max(-max_shift_samples, min(max_shift_samples, lag_samples))
    return lag_samples, peak


def _estimate_lag_samples(reference, target, sr: int, max_shift_seconds: float) -> int:
    lag_samples, _ = _estimate_lag_with_score(reference, target, sr=sr, max_shift_seconds=max_shift_seconds)
    return lag_samples


def _shift_to_reference_timeline(signal, lag_samples: int, ref_len: int):
    import numpy as np

    out = np.zeros(int(ref_len), dtype=np.float32)
    x = signal.astype(np.float32, copy=False)
    start = int(lag_samples)
    if start >= 0:
        src_start = 0
        dst_start = start
    else:
        src_start = -start
        dst_start = 0
    n = min(len(x) - src_start, len(out) - dst_start)
    if n > 0:
        out[dst_start : dst_start + n] = x[src_start : src_start + n]
    return out


def _load_for_alignment(path: Path, ffmpeg: str, *, sr: int, seconds: int):
    import numpy as np

    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-t",
        str(seconds),
        "-f",
        "f32le",
        "-",
    ]
    raw = _run_capture(cmd, timeout=max(45, seconds * 2)).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    if audio.size == 0:
        raise RuntimeError(f"No audio decoded for alignment: {path}")
    return audio


def _duration_fallback(path: Path, ffmpeg: str) -> float:
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-f",
        "null",
        "-",
        "-progress",
        "pipe:2",
        "-nostats",
    ]
    proc = subprocess.run(cmd, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=180)
    stderr = proc.stderr.decode("utf-8", errors="replace")
    progress_us = re.findall(r"out_time_(?:us|ms)=(\d+)", stderr)
    if progress_us:
        micros = int(progress_us[-1])
        if micros > 0:
            return micros / 1_000_000.0
    matches = re.findall(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if matches:
        hh, mm, ss = matches[-1]
        return int(hh) * 3600.0 + int(mm) * 60.0 + float(ss)
    header = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if header:
        hh, mm, ss = header.groups()
        return int(hh) * 3600.0 + int(mm) * 60.0 + float(ss)

    # Final fallback: decode mono float PCM and derive duration by sample count.
    sr = 44100
    pcm_cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sr),
        "-f",
        "f32le",
        "-",
    ]
    proc2 = subprocess.Popen(pcm_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    total_bytes = 0
    assert proc2.stdout is not None
    try:
        for chunk in iter(lambda: proc2.stdout.read(1024 * 1024), b""):
            total_bytes += len(chunk)
    finally:
        _, stderr2 = proc2.communicate(timeout=30)
    if proc2.returncode not in (0, None):
        err = stderr2.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"Unable to decode audio for duration: {path}. ffmpeg error: {err[:300]}")
    if total_bytes <= 0:
        raise RuntimeError(f"Unable to determine duration for: {path}")
    samples = total_bytes / 4.0
    return samples / float(sr)


def _audio_duration(path: Path, ffmpeg: str, ffprobe: str | None) -> float:
    if ffprobe:
        cmd = [
            ffprobe,
            "-nostdin",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=duration",
            "-of",
            "json",
            str(path),
        ]
        try:
            out = _run_capture(cmd, timeout=25).stdout.decode("utf-8", errors="replace")
            data = json.loads(out or "{}")
            values = []
            fmt = data.get("format") or {}
            if fmt.get("duration"):
                values.append(float(fmt["duration"]))
            for stream in (data.get("streams") or []):
                if stream.get("duration"):
                    values.append(float(stream["duration"]))
            values = [v for v in values if v > 0]
            if values:
                return max(values)
        except Exception:
            pass
    return _duration_fallback(path, ffmpeg)


def _render_aligned_mp3(
    ffmpeg: str,
    src: Path,
    dst: Path,
    pre_pad_sec: float,
    out_duration_sec: float,
) -> None:
    delay_ms = max(0, int(round(pre_pad_sec * 1000.0)))
    delay_spec = f"{delay_ms}|{delay_ms}"
    afilter = f"adelay={delay_spec},apad,atrim=0:{out_duration_sec:.6f}"
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        afilter,
        "-ar",
        "44100",
        "-ac",
        "2",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(dst),
    ]
    timeout_s = max(120, int(out_duration_sec * 4))
    _run_quiet(cmd, timeout=timeout_s)


def _render_clip_segment_mp3(
    ffmpeg: str,
    src: Path,
    dst: Path,
    *,
    timeline_offset_sec: float,
    clip_start_sec: float,
    clip_end_sec: float,
    out_duration_sec: float,
) -> None:
    src_duration = _audio_duration(src, ffmpeg, _ffprobe_path())
    clip_start = max(0.0, float(clip_start_sec or 0.0))
    clip_end = float(clip_end_sec if clip_end_sec is not None else src_duration)
    if clip_end <= 0.0:
        clip_end = src_duration
    clip_end = min(max(clip_start + 0.001, clip_end), max(src_duration, clip_start + 0.001))

    offset = float(timeline_offset_sec or 0.0)
    if offset < 0.0:
        clip_start += abs(offset)
        offset = 0.0

    if clip_start >= clip_end:
        raise RuntimeError(f"Manual alignment clip became empty for {src.name}")

    delay_ms = max(0, int(round(offset * 1000.0)))
    delay_spec = f"{delay_ms}|{delay_ms}"
    afilter = (
        f"atrim=start={clip_start:.6f}:end={clip_end:.6f},"
        f"asetpts=PTS-STARTPTS,adelay={delay_spec},apad,atrim=0:{out_duration_sec:.6f}"
    )
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-map",
        "0:a:0",
        "-vn",
        "-af",
        afilter,
        "-ar",
        "44100",
        "-ac",
        "2",
        "-codec:a",
        "libmp3lame",
        "-b:a",
        "320k",
        str(dst),
    ]
    timeout_s = max(120, int(out_duration_sec * 4))
    _run_quiet(cmd, timeout=timeout_s)


def _manual_align_commit(
    *,
    base_audio: Path,
    vocals: Path,
    instrumental: Path,
    vocals_offset_seconds: float,
    instrumental_offset_seconds: float,
    vocals_clip_start_seconds: float,
    vocals_clip_end_seconds: float,
    instrumental_clip_start_seconds: float,
    instrumental_clip_end_seconds: float,
    out_dir: Path,
) -> dict:
    ffmpeg = _ffmpeg_path()
    ffprobe = _ffprobe_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; required for manual align commit")

    out_dir.mkdir(parents=True, exist_ok=True)

    base_duration = _audio_duration(base_audio, ffmpeg, ffprobe)
    vocals_duration = _audio_duration(vocals, ffmpeg, ffprobe)
    inst_duration = _audio_duration(instrumental, ffmpeg, ffprobe)

    v_start = max(0.0, float(vocals_clip_start_seconds or 0.0))
    i_start = max(0.0, float(instrumental_clip_start_seconds or 0.0))
    v_end = min(max(v_start + 0.001, float(vocals_clip_end_seconds or vocals_duration)), vocals_duration)
    i_end = min(max(i_start + 0.001, float(instrumental_clip_end_seconds or inst_duration)), inst_duration)
    v_offset = float(vocals_offset_seconds or 0.0)
    i_offset = float(instrumental_offset_seconds or 0.0)

    out_duration = max(
        base_duration,
        max(0.0, v_offset) + max(0.0, v_end - v_start),
        max(0.0, i_offset) + max(0.0, i_end - i_start),
    )
    out_duration = max(out_duration, 1.0)

    vocals_out = out_dir / f"{vocals.stem} - manual.mp3"
    inst_out = out_dir / f"{instrumental.stem} - manual.mp3"

    _render_clip_segment_mp3(
        ffmpeg,
        vocals,
        vocals_out,
        timeline_offset_sec=v_offset,
        clip_start_sec=v_start,
        clip_end_sec=v_end,
        out_duration_sec=out_duration,
    )
    _render_clip_segment_mp3(
        ffmpeg,
        instrumental,
        inst_out,
        timeline_offset_sec=i_offset,
        clip_start_sec=i_start,
        clip_end_sec=i_end,
        out_duration_sec=out_duration,
    )

    return {
        "manual_align_folder": str(out_dir),
        "base": str(base_audio),
        "vocals": str(vocals_out),
        "instrumental": str(inst_out),
        "output_duration_seconds": out_duration,
        "vocals_offset_seconds": v_offset,
        "instrumental_offset_seconds": i_offset,
        "vocals_clip_start_seconds": v_start,
        "vocals_clip_end_seconds": v_end,
        "instrumental_clip_start_seconds": i_start,
        "instrumental_clip_end_seconds": i_end,
    }


def _align_studio_stems(
    *,
    base_audio: Path,
    vocals: Path,
    instrumental: Path,
    out_dir: Path,
    analysis_seconds: int = ALIGN_ANALYSIS_SECONDS,
    max_shift_seconds: float = ALIGN_MAX_SHIFT_SECONDS,
    vocal_nudge_seconds: float = 0.0,
) -> dict:
    _ensure_pydeps()
    ffmpeg = _ffmpeg_path()
    ffprobe = _ffprobe_path()
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found; required for stem alignment")

    out_dir.mkdir(parents=True, exist_ok=True)
    print("Starting analysis decode...", file=sys.stderr, flush=True)
    base_a = _load_for_alignment(base_audio, ffmpeg, sr=ALIGN_ANALYSIS_SR, seconds=analysis_seconds)
    vocals_a = _load_for_alignment(vocals, ffmpeg, sr=ALIGN_ANALYSIS_SR, seconds=analysis_seconds)
    inst_a = _load_for_alignment(instrumental, ffmpeg, sr=ALIGN_ANALYSIS_SR, seconds=analysis_seconds)

    print("Analysis decode complete. Estimating offsets...", file=sys.stderr, flush=True)
    lag_i_samples, lag_i_score = _estimate_lag_with_score(
        base_a, inst_a, sr=ALIGN_ANALYSIS_SR, max_shift_seconds=max_shift_seconds
    )
    # Better vocal target: remove aligned instrumental from base to emphasize vocal structure.
    inst_on_base = _shift_to_reference_timeline(inst_a, lag_i_samples, len(base_a))
    base_vocal_proxy = base_a[: len(inst_on_base)] - inst_on_base
    lag_v_proxy_samples, lag_v_proxy_score = _estimate_lag_with_score(
        base_vocal_proxy, vocals_a, sr=ALIGN_ANALYSIS_SR, max_shift_seconds=max_shift_seconds
    )
    lag_v_direct_samples, lag_v_direct_score = _estimate_lag_with_score(
        base_a, vocals_a, sr=ALIGN_ANALYSIS_SR, max_shift_seconds=max_shift_seconds
    )
    # For studio stems, proxy is usually more trustworthy than direct full-mix matching.
    # Keep direct as fallback only if proxy confidence is dramatically worse.
    if lag_v_proxy_score >= (lag_v_direct_score * 0.65):
        lag_v_samples = lag_v_proxy_samples
        lag_v_method = "proxy(base-minus-inst)"
        lag_v_score = lag_v_proxy_score
    else:
        lag_v_samples = lag_v_direct_samples
        lag_v_method = "direct(base)"
        lag_v_score = lag_v_direct_score

    lag_v_sec = lag_v_samples / float(ALIGN_ANALYSIS_SR)
    lag_v_sec += float(vocal_nudge_seconds or 0.0)
    lag_i_sec = lag_i_samples / float(ALIGN_ANALYSIS_SR)

    d_base = _audio_duration(base_audio, ffmpeg, ffprobe)
    d_vocals = _audio_duration(vocals, ffmpeg, ffprobe)
    d_inst = _audio_duration(instrumental, ffmpeg, ffprobe)

    shift_base, shift_v, shift_i = 0.0, lag_v_sec, lag_i_sec
    earliest = min(shift_base, shift_v, shift_i)
    latest_end = max(shift_base + d_base, shift_v + d_vocals, shift_i + d_inst)

    out_duration = latest_end - earliest
    pre_base = shift_base - earliest
    pre_v = shift_v - earliest
    pre_i = shift_i - earliest

    print(
        "Alignment values: "
        f"lag_v={lag_v_sec:.3f}s, lag_i={lag_i_sec:.3f}s, "
        f"pre_base={pre_base:.3f}s, pre_v={pre_v:.3f}s, pre_i={pre_i:.3f}s, "
        f"out_duration={out_duration:.3f}s, "
        f"v_method={lag_v_method}, v_score={lag_v_score:.3f}, i_score={lag_i_score:.3f}, "
        f"v_nudge={float(vocal_nudge_seconds or 0.0):.3f}s",
        file=sys.stderr,
        flush=True,
    )

    base_out = out_dir / f"{base_audio.stem} - aligned.mp3"
    vocals_out = out_dir / f"{vocals.stem} - aligned.mp3"
    inst_out = out_dir / f"{instrumental.stem} - aligned.mp3"

    print(f"Rendering aligned base -> {base_out.name}", file=sys.stderr, flush=True)
    _render_aligned_mp3(ffmpeg, base_audio, base_out, pre_base, out_duration)
    print(f"Rendering aligned vocals -> {vocals_out.name}", file=sys.stderr, flush=True)
    _render_aligned_mp3(ffmpeg, vocals, vocals_out, pre_v, out_duration)
    print(f"Rendering aligned instrumental -> {inst_out.name}", file=sys.stderr, flush=True)
    _render_aligned_mp3(ffmpeg, instrumental, inst_out, pre_i, out_duration)
    print("Rendering complete.", file=sys.stderr, flush=True)

    report = {
        "align_folder": str(out_dir),
        "base": str(base_audio),
        "vocals": str(vocals),
        "instrumental": str(instrumental),
        "aligned_base": str(base_out),
        "aligned_vocals": str(vocals_out),
        "aligned_instrumental": str(inst_out),
        "lag_vocals_to_base_samples": lag_v_samples,
        "lag_vocals_to_base_seconds": lag_v_sec,
        "lag_vocals_method": lag_v_method,
        "lag_vocals_score": lag_v_score,
        "lag_vocals_nudge_seconds": float(vocal_nudge_seconds or 0.0),
        "lag_instrumental_to_base_samples": lag_i_samples,
        "lag_instrumental_to_base_seconds": lag_i_sec,
        "lag_instrumental_score": lag_i_score,
        "output_duration_seconds": out_duration,
        "analysis_seconds": analysis_seconds,
        "max_shift_seconds": max_shift_seconds,
    }
    return report


def _copy_source_metadata_to_mp3(source_audio: Path, target_mp3: Path) -> str | None:
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        return "ffmpeg not found; metadata copy skipped"
    tmp_out = target_mp3.with_name(f".{target_mp3.stem}.meta.tmp.mp3")
    cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(target_mp3),
        "-i",
        str(source_audio),
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
        str(tmp_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        if tmp_out.exists():
            try:
                tmp_out.unlink()
            except OSError:
                pass
        return f"metadata copy failed for {target_mp3.name}: {err}"
    try:
        tmp_out.replace(target_mp3)
    except OSError as exc:
        return f"metadata replace failed for {target_mp3.name}: {exc}"
    return None


def _load_stereo_44100(path: Path):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    data, in_sr = sf.read(str(path), always_2d=True)
    data = data.astype("float32")
    if data.shape[1] == 1:
        data = np.repeat(data, 2, axis=1)
    data = data.T
    if in_sr != 44100:
        gcd = np.gcd(in_sr, 44100)
        up = 44100 // gcd
        down = in_sr // gcd
        data = np.vstack([resample_poly(ch, up, down).astype("float32") for ch in data])
    return data


def _restore_vocal_high_end(vocals_path: Path, mix_path: Path, cutoff_bin: int = 3072, n_fft: int = 7680, hop: int = 1024) -> None:
    import numpy as np
    import soundfile as sf
    from scipy.signal import stft, istft

    vocals = _load_stereo_44100(vocals_path)
    mix = _load_stereo_44100(mix_path)
    frames = min(vocals.shape[1], mix.shape[1])
    vocals = vocals[:, :frames]
    mix = mix[:, :frames]

    noverlap = n_fft - hop
    restored = np.zeros_like(vocals, dtype=np.float32)

    for ch in (0, 1):
        _, _, spec_mix = stft(mix[ch], fs=44100, nperseg=n_fft, noverlap=noverlap, boundary="zeros", padded=True)
        _, _, spec_voc = stft(vocals[ch], fs=44100, nperseg=n_fft, noverlap=noverlap, boundary="zeros", padded=True)
        bins = spec_mix.shape[0]
        cbin = min(cutoff_bin, bins - 1)
        if cbin < 32:
            restored[ch, : vocals[ch].shape[0]] = vocals[ch]
            continue

        eps = 1e-8
        mask = np.clip(np.abs(spec_voc) / (np.abs(spec_mix) + eps), 0.0, 1.0)
        edge = min(128, cbin // 2)
        edge_mask = np.median(mask[cbin - edge : cbin, :], axis=0, keepdims=True)
        edge_mask = np.clip(edge_mask, 0.0, 1.0)

        spec_out = spec_voc.copy()
        if cbin < bins:
            spec_out[cbin:, :] = spec_mix[cbin:, :] * edge_mask

        blend = min(96, cbin)
        if blend > 0:
            start = cbin - blend
            alpha = np.linspace(0.0, 1.0, blend, dtype=np.float32)[:, None]
            blend_target = spec_mix[start:cbin, :] * edge_mask
            spec_out[start:cbin, :] = (1.0 - alpha) * spec_voc[start:cbin, :] + alpha * blend_target

        _, rec = istft(spec_out, fs=44100, nperseg=n_fft, noverlap=noverlap, input_onesided=True, boundary=True)
        restored[ch, : min(frames, rec.shape[0])] = rec[:frames].astype(np.float32)

    peak = float(np.max(np.abs(restored))) if restored.size else 0.0
    if peak > 0.999:
        restored *= 0.999 / peak
    sf.write(str(vocals_path), restored.T, 44100, subtype="PCM_16")


def _is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in {".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a"}


def _pick_stems(output_dir: Path) -> tuple[Path | None, Path | None]:
    files = sorted([p for p in output_dir.rglob("*") if p.is_file() and _is_audio_file(p)], key=lambda p: p.stat().st_mtime)
    if not files:
        return None, None

    vocals = None
    instrumental = None
    for f in files:
        name = f.name.lower()
        if vocals is None and any(token in name for token in ("vocal", "vox", "voice")):
            vocals = f
        if instrumental is None and (
            "instrumental" in name
            or "karaoke" in name
            or "no_vocal" in name
            or "no-vocal" in name
            or "no vocals" in name
            or "_inst" in name
            or "-inst" in name
        ):
            instrumental = f

    if vocals is None and len(files) == 2:
        vocals = files[0]
    if instrumental is None and len(files) == 2:
        instrumental = files[1] if files[1] != vocals else files[0]

    if vocals is None and files:
        vocals = files[0]
    if instrumental is None and len(files) > 1:
        instrumental = files[1] if files[1] != vocals else files[0]
    return vocals, instrumental


def _ensure_kim2_runtime(app_root: Path) -> tuple[Path, Path]:
    runtime_dir = app_root / "tools" / "kim2_runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    model_dst = runtime_dir / "Kim_Vocal_2.onnx"
    if not model_dst.exists():
        raise RuntimeError(f"Bundled Kim-2 model missing: {model_dst}")

    mdx_data_dst = runtime_dir / "mdx_model_data.json"
    if not mdx_data_dst.exists():
        raise RuntimeError(f"Bundled MDX model data missing: {mdx_data_dst}")

    vr_data_dst = runtime_dir / "vr_model_data.json"
    if not vr_data_dst.exists():
        vr_data_dst.write_text("{}", encoding="utf-8")

    checks_dst = runtime_dir / "download_checks.json"
    try:
        checks_obj = json.loads(checks_dst.read_text(encoding="utf-8")) if checks_dst.exists() else {}
    except Exception:
        checks_obj = {}
    if not isinstance(checks_obj, dict):
        checks_obj = {}
    checks_obj.setdefault("vr_download_list", {})
    checks_obj.setdefault("vr_download_vip_list", {})
    checks_obj.setdefault("mdx_download_list", {})
    checks_obj.setdefault("mdx_download_vip_list", {})
    checks_obj.setdefault("demucs_download_list", {})
    checks_obj.setdefault("mdx23c_download_list", {})
    checks_obj.setdefault("mdx23c_download_vip_list", {})
    checks_obj.setdefault("roformer_download_list", {})
    checks_obj["mdx_download_list"]["MDX-Net Model: Kim Vocal 2"] = "Kim_Vocal_2.onnx"
    checks_dst.write_text(json.dumps(checks_obj), encoding="utf-8")
    return runtime_dir, model_dst


def _patch_audio_separator_loader() -> None:
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    from types import SimpleNamespace
    import audio_separator.separator.common_separator as common_separator

    def _load(path: str, mono: bool = False, sr: int = 44100):
        data, in_sr = sf.read(path, always_2d=True)
        data = data.astype("float32")
        if data.shape[1] == 1:
            data = np.repeat(data, 2, axis=1)
        data = data.T
        if sr and in_sr != sr:
            gcd = np.gcd(in_sr, sr)
            up = sr // gcd
            down = in_sr // gcd
            data = np.vstack([resample_poly(ch, up, down).astype("float32") for ch in data])
        if mono:
            data = np.mean(data, axis=0)
        return data, sr

    common_separator.librosa = SimpleNamespace(load=_load)


def _resolve_onnx_providers(prefer_gpu: bool) -> list[str]:
    import onnxruntime as ort

    available = ort.get_available_providers()
    if prefer_gpu and "CoreMLExecutionProvider" in available:
        # Force CoreML path first; explicit CPU fallback is handled by retry logic.
        return ["CoreMLExecutionProvider"]
    return ["CPUExecutionProvider"]


def _run_kim2(base_audio: Path, out_dir: Path, *, prefer_gpu: bool = True) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    app_root = Path(__file__).resolve().parent.parent
    pydeps = _ensure_pydeps()

    # Ensure pydub/ffmpeg lookups resolve to bundled ffmpeg first.
    os.environ["PATH"] = f"{app_root / 'bin'}:{os.environ.get('PATH', '')}"
    os.environ.setdefault("TQDM_DISABLE", "1")
    warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL*")
    coreml_tmp = app_root / "tmp_coreml"
    coreml_tmp.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(coreml_tmp)
    os.environ["TEMP"] = str(coreml_tmp)
    os.environ["TMP"] = str(coreml_tmp)

    runtime_dir, model_path = _ensure_kim2_runtime(app_root)
    _patch_audio_separator_loader()

    from audio_separator.separator import Separator
    import audio_separator.separator.architectures.mdx_separator as mdx_separator
    from tqdm import tqdm as _tqdm

    def _progress_tqdm(iterable, *args, **kwargs):
        total = kwargs.get("total")
        if total is None:
            try:
                total = len(iterable)
            except Exception:
                total = None
        count = 0
        for item in iterable:
            count += 1
            if total and total > 0:
                pct = (count / float(total)) * 100.0
                _emit_progress("kim2", pct, f"Kim-2 processing {count}/{total}")
            else:
                # Unknown total, send pulsing-like capped progress.
                pct = min(96.0, 8.0 + count * 2.0)
                _emit_progress("kim2", pct, "Kim-2 processing...")
            yield item

    mdx_separator.tqdm = _progress_tqdm

    def _make_separator(batch_size: int):
        mdx_overlap = KIM2_GPU_OVERLAP if prefer_gpu else 0.25
        mdx_batch = int(batch_size)
        return Separator(
            log_level=40,
            model_file_dir=str(runtime_dir),
            output_dir=str(out_dir),
            output_format="wav",
            sample_rate=44100,
            mdx_params={
                "hop_length": 1024,
                "segment_size": 256,
                "overlap": mdx_overlap,
                "batch_size": mdx_batch,
                "enable_denoise": False,
            },
        )

    initial_providers = _resolve_onnx_providers(prefer_gpu)
    providers = list(initial_providers)
    provider_fallback = False
    if prefer_gpu:
        batch_attempts = []
        for b in (KIM2_GPU_BATCH_SIZE, 6, 4, 3, 2, 1):
            if b not in batch_attempts:
                batch_attempts.append(b)
    else:
        batch_attempts = [1]
    used_batch_size = batch_attempts[0]
    base_stem = base_audio.stem
    # Remove prior artifacts for this source to avoid stale file selection.
    for old in out_dir.glob(f"{base_stem}_*Kim_Vocal_2.*"):
        try:
            old.unlink()
        except OSError:
            pass
    for old in (out_dir / f"{base_stem} - vocals.mp3", out_dir / f"{base_stem} - instrumental.mp3"):
        if old.exists():
            try:
                old.unlink()
            except OSError:
                pass

    separator_outputs = None
    last_error: Exception | None = None
    attempted_profiles: list[tuple[list[str], int]] = []

    provider_profiles: list[tuple[list[str], list[int]]] = [(providers, batch_attempts)]
    if prefer_gpu and "CoreMLExecutionProvider" in initial_providers:
        provider_profiles.append((["CPUExecutionProvider"], [1]))

    for provider_set, profile_batches in provider_profiles:
        for batch_size in profile_batches:
            attempted_profiles.append((provider_set, batch_size))
            separator = _make_separator(batch_size)
            separator.onnx_execution_provider = provider_set
            if prefer_gpu and "CoreMLExecutionProvider" in provider_set:
                try:
                    import torch

                    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                        separator.torch_device_mps = torch.device("mps")
                        separator.torch_device = separator.torch_device_mps
                except Exception:
                    pass
            try:
                _emit_progress(
                    "kim2",
                    0.0,
                    f"Starting Kim-2 separation (provider={provider_set[0]}, batch={batch_size})...",
                )
                separator.load_model("Kim_Vocal_2.onnx")
                separator_outputs = separator.separate(str(base_audio))
                providers = provider_set
                used_batch_size = batch_size
                provider_fallback = provider_set != initial_providers
                break
            except Exception as exc:
                last_error = exc
                _emit_progress(
                    "kim2",
                    1.0,
                    f"Kim-2 retrying after profile failure (provider={provider_set[0]}, batch={batch_size})",
                )
                continue
        if separator_outputs is not None:
            break

    if separator_outputs is None:
        if last_error is not None:
            raise last_error
        raise RuntimeError("Kim-2 failed with all provider/batch profiles")

    _emit_progress("kim2", 100.0, "Kim-2 separation complete.")
    output_paths = []
    for p in separator_outputs:
        pth = Path(p)
        if not pth.is_absolute():
            pth = out_dir / pth
        output_paths.append(pth)

    vocals_raw = None
    instrumental_raw = None
    for p in output_paths:
        name = p.name.lower()
        if vocals_raw is None and "(vocals)" in name:
            vocals_raw = p
        if instrumental_raw is None and "(instrumental)" in name:
            instrumental_raw = p

    if not vocals_raw or not instrumental_raw:
        # Fallback for unexpected naming.
        vocals_raw, instrumental_raw = _pick_stems(out_dir)
    if not vocals_raw or not instrumental_raw:
        raise RuntimeError("Kim-2 ran but no vocal/instrumental outputs were detected")

    try:
        _restore_vocal_high_end(vocals_raw, base_audio)
    except Exception:
        # Keep extraction path robust even if restoration fails on unusual files.
        pass

    vocals_mp3 = out_dir / f"{base_stem} - vocals.mp3"
    instrumental_mp3 = out_dir / f"{base_stem} - instrumental.mp3"
    if vocals_raw.suffix.lower() == ".mp3":
        if vocals_raw != vocals_mp3:
            vocals_mp3.write_bytes(vocals_raw.read_bytes())
    else:
        _to_mp3(vocals_raw, vocals_mp3)

    if instrumental_raw.suffix.lower() == ".mp3":
        if instrumental_raw != instrumental_mp3:
            instrumental_mp3.write_bytes(instrumental_raw.read_bytes())
    else:
        _to_mp3(instrumental_raw, instrumental_mp3)

    metadata_warnings = []
    for stem_mp3 in (vocals_mp3, instrumental_mp3):
        warn = _copy_source_metadata_to_mp3(base_audio, stem_mp3)
        if warn:
            metadata_warnings.append(warn)

    report = {
        "base": str(base_audio),
        "vocals": str(vocals_mp3),
        "instrumental": str(instrumental_mp3),
        "extract_folder": str(out_dir),
        "model": str(model_path),
        "onnx_providers": providers,
        "onnx_provider_fallback": provider_fallback,
        "kim2_batch_size": used_batch_size,
    }
    if attempted_profiles:
        report["kim2_profiles_attempted"] = [
            {"provider": p[0][0] if p[0] else "unknown", "batch_size": p[1]}
            for p in attempted_profiles
        ]
    if metadata_warnings:
        report["warnings"] = metadata_warnings
    return report


def _run_demucs_4stem(instrumental_audio: Path, output_root: Path, *, prefer_gpu: bool = True) -> dict[str, Path]:
    app_root = Path(__file__).resolve().parent.parent
    demucs_weight, demucs_yaml = _ensure_demucs_runtime_assets(app_root)

    output_root.mkdir(parents=True, exist_ok=True)
    from audio_separator.separator import Separator

    demucs_params = {
        "segment_size": "Default",
        "shifts": 1,
        "overlap": 0.1,
        "segments_enabled": True,
    }
    sep = Separator(
        log_level=40,
        model_file_dir=str(demucs_weight.parent),
        output_dir=str(output_root),
        output_format="wav",
        sample_rate=44100,
        demucs_params=demucs_params,
    )
    device_used = "cpu"
    if prefer_gpu:
        try:
            import torch

            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                sep.torch_device_mps = torch.device("mps")
                sep.torch_device = sep.torch_device_mps
                device_used = "mps"
        except Exception:
            pass

    sep.load_model(DEMUCS_MODEL_FILENAME)
    _emit_progress("demucs", 0.0, "Starting Demucs split...")
    separated = sep.separate(str(instrumental_audio))
    _emit_progress("demucs", 100.0, "Demucs split complete.")

    output_paths = []
    for p in separated:
        pth = Path(p)
        if not pth.is_absolute():
            pth = output_root / pth
        output_paths.append(pth)

    def _pick(keyword: str) -> Path | None:
        for p in output_paths:
            if f"({keyword.lower()})" in p.name.lower():
                return p
        for p in output_root.glob("*"):
            if p.is_file() and keyword.lower() in p.name.lower():
                return p
        return None

    bass = _pick("bass")
    drums = _pick("drums")
    other = _pick("other")
    if not bass or not drums or not other:
        available = sorted([p.name for p in output_root.glob("*") if p.is_file()])
        raise RuntimeError(
            "Demucs completed but required stems were not found (bass/drums/other). "
            f"Output folder: {output_root}. Files: {available}"
        )

    return {
        "bass": bass,
        "drums": drums,
        "other": other,
        "model": demucs_yaml,
        "weight": demucs_weight,
        "device": device_used,
    }


def _run_kim2_then_demucs(base_audio: Path, out_dir: Path, *, prefer_gpu: bool = True) -> dict:
    t0 = time.perf_counter()
    kim_report = _run_kim2(base_audio, out_dir, prefer_gpu=prefer_gpu)
    t1 = time.perf_counter()
    demucs_dir = out_dir / "_demucs_outputs"
    split = _run_demucs_4stem(Path(kim_report["instrumental"]), demucs_dir, prefer_gpu=prefer_gpu)
    t2 = time.perf_counter()

    base_stem = base_audio.stem
    bass_mp3 = out_dir / f"{base_stem} - bass.mp3"
    drums_mp3 = out_dir / f"{base_stem} - drums.mp3"
    melody_mp3 = out_dir / f"{base_stem} - melody.mp3"

    for src, dest in ((split["bass"], bass_mp3), (split["drums"], drums_mp3)):
        if src.suffix.lower() == ".mp3":
            if src != dest:
                dest.write_bytes(src.read_bytes())
        else:
            _to_mp3(src, dest)
    _to_mp3(split["other"], melody_mp3)
    t3 = time.perf_counter()

    metadata_warnings = list(kim_report.get("warnings", []))
    for stem_mp3 in (bass_mp3, drums_mp3, melody_mp3):
        warn = _copy_source_metadata_to_mp3(base_audio, stem_mp3)
        if warn:
            metadata_warnings.append(warn)

    report = {
        "base": kim_report["base"],
        "vocals": kim_report["vocals"],
        "bass": str(bass_mp3),
        "drums": str(drums_mp3),
        "melody": str(melody_mp3),
        "instrumental": kim_report["instrumental"],
        "extract_folder": str(out_dir),
        "model": kim_report.get("model"),
        "demucs_model": str(split["model"]),
        "demucs_weight": str(split["weight"]),
        "demucs_device": split.get("device"),
        "timing_seconds": {
            "kim2": round(t1 - t0, 3),
            "demucs": round(t2 - t1, 3),
            "postprocess": round(t3 - t2, 3),
            "total": round(t3 - t0, 3),
        },
        "onnx_providers": kim_report.get("onnx_providers", []),
        "onnx_provider_fallback": bool(kim_report.get("onnx_provider_fallback", False)),
    }
    if metadata_warnings:
        report["warnings"] = metadata_warnings
    return report


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        return _error("Empty payload")
    try:
        payload = json.loads(raw)
    except Exception:
        return _error("Invalid JSON payload")

    mode = (payload.get("mode") or "four").strip().lower()
    if mode not in {"four", "two"}:
        return _error("Mode must be 'four' or 'two'")
    action = (payload.get("action") or "build").strip().lower()
    if action not in {"build", "prepare", "extract", "align_studio", "manual_align_commit"}:
        return _error("Action must be 'build', 'prepare', 'extract', 'align_studio', or 'manual_align_commit'")

    try:
        global _PROGRESS_TOKEN
        _PROGRESS_TOKEN = payload.get("progress_token")
        base = _to_path(payload.get("base"))
        vocals = _to_path(payload.get("vocals"))
        bass = _to_path(payload.get("bass"))
        drums = _to_path(payload.get("drums"))
        melody = _to_path(payload.get("melody"))
        instrumental = _to_path(payload.get("instrumental"))
        copy_to = _to_path(payload.get("copy_to"))
        final_output_dir = _to_path(payload.get("final_output_dir"))
        original_base_path = _to_path(payload.get("original_base_path"))
        stem_delay_ms = float(payload.get("stem_delay_ms") or payload.get("vocals_delay_ms") or 0.0)
        # Treat sub-micro delays as strict zero to keep a single deterministic
        # no-delay code path for Serato template compatibility.
        if abs(stem_delay_ms) < 0.001:
            stem_delay_ms = 0.0
        add_gain_stems = bool(payload.get("add_gain_stems", False))
        disable_base_metadata_copy = bool(payload.get("disable_base_metadata_copy", False))

        if not base:
            raise ValueError("Base audio file is required")
        if not base.exists():
            raise ValueError(f"Base audio file not found: {base}")

        def _template_override_from_original() -> Path | None:
            if not original_base_path or not original_base_path.exists():
                return None
            candidate = sidecar_for_audio(original_base_path)
            if candidate.exists():
                return candidate
            return None

        def _resolve_template_for_build() -> Path | None:
            if FORCE_NO_TEMPLATE_WORKFLOW:
                return None
            local_candidate = sidecar_for_audio(base)
            if local_candidate.exists():
                return local_candidate
            return _template_override_from_original()

        if action == "extract":
            extract_folder = _injector_work_root() / "extracted stems"
            use_gpu = bool(payload.get("use_gpu", True))
            if mode == "four":
                extract_report = _run_kim2_then_demucs(base, extract_folder, prefer_gpu=use_gpu)
            else:
                extract_report = _run_kim2(base, extract_folder, prefer_gpu=use_gpu)
            prepared_outputs = {
                "base": extract_report["base"],
                "vocals": extract_report["vocals"],
            }
            if mode == "four":
                prepared_outputs["bass"] = extract_report["bass"]
                prepared_outputs["drums"] = extract_report["drums"]
                prepared_outputs["melody"] = extract_report["melody"]
            else:
                prepared_outputs["instrumental"] = extract_report["instrumental"]
            print(
                json.dumps(
                    {
                        "ok": True,
                        "report": {
                            "extract_folder": extract_report["extract_folder"],
                            "prepared_outputs": prepared_outputs,
                            "model": extract_report["model"],
                            "demucs_model": extract_report.get("demucs_model"),
                            "demucs_weight": extract_report.get("demucs_weight"),
                            "demucs_device": extract_report.get("demucs_device"),
                            "timing_seconds": extract_report.get("timing_seconds"),
                            "onnx_providers": extract_report.get("onnx_providers", []),
                            "onnx_provider_fallback": bool(extract_report.get("onnx_provider_fallback", False)),
                            "warnings": extract_report.get("warnings", []),
                        },
                        "report_json": json.dumps(extract_report),
                    }
                )
            )
            return 0

        if action == "align_studio":
            if not vocals:
                raise ValueError("Vocals MP3 is required for studio stem alignment")
            if not vocals.exists():
                raise ValueError(f"Vocals MP3 not found: {vocals}")
            if not instrumental:
                raise ValueError("Instrumental MP3 is required for studio stem alignment")
            if not instrumental.exists():
                raise ValueError(f"Instrumental MP3 not found: {instrumental}")

            analysis_seconds = max(10, int(payload.get("analysis_seconds") or ALIGN_ANALYSIS_SECONDS))
            max_shift_seconds = max(0.5, float(payload.get("max_shift_seconds") or ALIGN_MAX_SHIFT_SECONDS))
            vocal_nudge_seconds = float(payload.get("vocal_nudge_seconds") or 0.0)
            align_folder = _injector_work_root() / "aligned stems"
            align_report = _align_studio_stems(
                base_audio=base,
                vocals=vocals,
                instrumental=instrumental,
                out_dir=align_folder,
                analysis_seconds=analysis_seconds,
                max_shift_seconds=max_shift_seconds,
                vocal_nudge_seconds=vocal_nudge_seconds,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "report": {
                            "align_folder": align_report["align_folder"],
                            "prepared_outputs": {
                                "base": align_report["aligned_base"],
                                "vocals": align_report["aligned_vocals"],
                                "instrumental": align_report["aligned_instrumental"],
                            },
                            "lag_vocals_to_base_seconds": align_report["lag_vocals_to_base_seconds"],
                            "lag_vocals_method": align_report.get("lag_vocals_method"),
                            "lag_vocals_score": align_report.get("lag_vocals_score"),
                            "lag_vocals_nudge_seconds": align_report.get("lag_vocals_nudge_seconds", 0.0),
                            "lag_instrumental_to_base_seconds": align_report["lag_instrumental_to_base_seconds"],
                            "lag_instrumental_score": align_report.get("lag_instrumental_score"),
                            "output_duration_seconds": align_report["output_duration_seconds"],
                        },
                        "report_json": json.dumps(align_report),
                    }
                )
            )
            return 0

        if action == "manual_align_commit":
            if not vocals:
                raise ValueError("Vocals MP3 is required for manual align commit")
            if not vocals.exists():
                raise ValueError(f"Vocals MP3 not found: {vocals}")
            if not instrumental:
                raise ValueError("Instrumental MP3 is required for manual align commit")
            if not instrumental.exists():
                raise ValueError(f"Instrumental MP3 not found: {instrumental}")

            manual_folder = _injector_work_root() / "manual aligned stems"
            manual_report = _manual_align_commit(
                base_audio=base,
                vocals=vocals,
                instrumental=instrumental,
                vocals_offset_seconds=float(payload.get("vocals_offset_seconds") or 0.0),
                instrumental_offset_seconds=float(payload.get("instrumental_offset_seconds") or 0.0),
                vocals_clip_start_seconds=float(payload.get("vocals_clip_start_seconds") or 0.0),
                vocals_clip_end_seconds=float(payload.get("vocals_clip_end_seconds") or 0.0),
                instrumental_clip_start_seconds=float(payload.get("instrumental_clip_start_seconds") or 0.0),
                instrumental_clip_end_seconds=float(payload.get("instrumental_clip_end_seconds") or 0.0),
                out_dir=manual_folder,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "report": {
                            "manual_align_folder": manual_report["manual_align_folder"],
                            "prepared_outputs": {
                                "base": manual_report["base"],
                                "vocals": manual_report["vocals"],
                                "instrumental": manual_report["instrumental"],
                            },
                            "output_duration_seconds": manual_report["output_duration_seconds"],
                            "vocals_offset_seconds": manual_report["vocals_offset_seconds"],
                            "instrumental_offset_seconds": manual_report["instrumental_offset_seconds"],
                            "vocals_clip_start_seconds": manual_report["vocals_clip_start_seconds"],
                            "vocals_clip_end_seconds": manual_report["vocals_clip_end_seconds"],
                            "instrumental_clip_start_seconds": manual_report["instrumental_clip_start_seconds"],
                            "instrumental_clip_end_seconds": manual_report["instrumental_clip_end_seconds"],
                        },
                        "report_json": json.dumps(manual_report),
                    }
                )
            )
            return 0

        if not vocals:
            raise ValueError("Vocals MP3 is required")
        if not vocals.exists():
            raise ValueError(f"Vocals MP3 not found: {vocals}")

        if mode == "two":
            if not instrumental:
                raise ValueError("Instrumental MP3 is required in 2-stem mode")
            if not instrumental.exists():
                raise ValueError(f"Instrumental MP3 not found: {instrumental}")
            if action == "prepare":
                template_sidecar_override = _template_override_from_original()
                no_template_mode_detected = not (sidecar_for_audio(base).exists() or template_sidecar_override is not None)
                report = prepare_files_for_serato(
                    mode=mode,
                    base_audio=base,
                    vocals=vocals,
                    bass=None,
                    drums=None,
                    melody=None,
                    instrumental=instrumental,
                    add_gain_stems=add_gain_stems,
                    copy_base_metadata=not disable_base_metadata_copy,
                    preserve_base_mp3_bytes=not FORCE_NO_TEMPLATE_WORKFLOW and not (
                        LEGACY_NO_TEMPLATE_MODE_ENABLED and no_template_mode_detected
                    ),
                    expect_template_generation=not FORCE_NO_TEMPLATE_WORKFLOW,
                )
                report["no_template_mode_detected"] = no_template_mode_detected
                report["no_template_mode_enabled"] = LEGACY_NO_TEMPLATE_MODE_ENABLED
                report["forced_no_template_workflow"] = FORCE_NO_TEMPLATE_WORKFLOW
            else:
                template_sidecar_override = _resolve_template_for_build()
                has_template_for_build = template_sidecar_override is not None
                effective_stem_delay_ms = max(0.0, stem_delay_ms)
                if not has_template_for_build and not LEGACY_NO_TEMPLATE_MODE_ENABLED:
                    raise RuntimeError(
                        "Template sidecar required for Build. In Serato, import the prepared base file and let Serato generate "
                        "its .1.2.serato-stems first, then run Build again."
                    )
                if not has_template_for_build and effective_stem_delay_ms < 1.5:
                    effective_stem_delay_ms = 1.5
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=None,
                    drums=None,
                    melody=None,
                    instrumental=instrumental,
                    two_stem_strategy="mute",
                    vocals_delay_ms_override=effective_stem_delay_ms,
                    template_sidecar_override=template_sidecar_override,
                    use_template=not FORCE_NO_TEMPLATE_WORKFLOW,
                    overwrite=True,
                )
                if not has_template_for_build:
                    report.setdefault("warnings", []).append(
                        "no template sidecar detected; using legacy no-template mode with forced delay: 1.5 ms"
                    )
                report["prepared_outputs"] = {
                    "base": str(base),
                    "vocals": str(vocals),
                    "instrumental": str(instrumental),
                }
                report["prep_folder"] = str(base.parent)
        else:
            for label, p in (("Bass MP3", bass), ("Drums MP3", drums), ("Melody MP3", melody)):
                if not p:
                    raise ValueError(f"{label} is required in 4-stem mode")
                if not p.exists():
                    raise ValueError(f"{label} not found: {p}")
            if action == "prepare":
                template_sidecar_override = _template_override_from_original()
                no_template_mode_detected = not (sidecar_for_audio(base).exists() or template_sidecar_override is not None)
                report = prepare_files_for_serato(
                    mode=mode,
                    base_audio=base,
                    vocals=vocals,
                    bass=bass,
                    drums=drums,
                    melody=melody,
                    instrumental=None,
                    add_gain_stems=add_gain_stems,
                    copy_base_metadata=not disable_base_metadata_copy,
                    preserve_base_mp3_bytes=not FORCE_NO_TEMPLATE_WORKFLOW and not (
                        LEGACY_NO_TEMPLATE_MODE_ENABLED and no_template_mode_detected
                    ),
                    expect_template_generation=not FORCE_NO_TEMPLATE_WORKFLOW,
                )
                report["no_template_mode_detected"] = no_template_mode_detected
                report["no_template_mode_enabled"] = LEGACY_NO_TEMPLATE_MODE_ENABLED
                report["forced_no_template_workflow"] = FORCE_NO_TEMPLATE_WORKFLOW
            else:
                template_sidecar_override = _resolve_template_for_build()
                has_template_for_build = template_sidecar_override is not None
                effective_stem_delay_ms = max(0.0, stem_delay_ms)
                if not has_template_for_build and not LEGACY_NO_TEMPLATE_MODE_ENABLED:
                    raise RuntimeError(
                        "Template sidecar required for Build. In Serato, import the prepared base file and let Serato generate "
                        "its .1.2.serato-stems first, then run Build again."
                    )
                if not has_template_for_build and effective_stem_delay_ms < 1.5:
                    effective_stem_delay_ms = 1.5
                report = build_sidecar(
                    base_audio=base,
                    vocals=vocals,
                    bass=bass,
                    drums=drums,
                    melody=melody,
                    instrumental=None,
                    two_stem_strategy="compat",
                    vocals_delay_ms_override=effective_stem_delay_ms,
                    template_sidecar_override=template_sidecar_override,
                    use_template=not FORCE_NO_TEMPLATE_WORKFLOW,
                    overwrite=True,
                )
                if not has_template_for_build:
                    report.setdefault("warnings", []).append(
                        "no template sidecar detected; using legacy no-template mode with forced delay: 1.5 ms"
                    )
                report["prepared_outputs"] = {
                    "base": str(base),
                    "vocals": str(vocals),
                    "bass": str(bass),
                    "drums": str(drums),
                    "melody": str(melody),
                }
                report["prep_folder"] = str(base.parent)

        if action == "build" and copy_to:
            out = Path(report["output_sidecar"])
            if copy_to.exists() and copy_to.is_dir():
                dest = copy_to / out.name
            elif str(copy_to).endswith(".serato-stems"):
                copy_to.parent.mkdir(parents=True, exist_ok=True)
                dest = copy_to
            else:
                copy_to.mkdir(parents=True, exist_ok=True)
                dest = copy_to / out.name
            dest.write_bytes(out.read_bytes())
            report["copied_to"] = str(dest)

        if action == "build":
            final_target = final_output_dir or original_base_path
            final_root = None
            if final_target:
                final_root = final_target.parent if final_target.suffix else final_target

            if final_root:
                final_root.mkdir(parents=True, exist_ok=True)
                out_sidecar = Path(report["output_sidecar"])
                base_src = base
                base_dest = final_root / base_src.name
                sidecar_dest = final_root / out_sidecar.name

                if base_src.resolve() != base_dest.resolve():
                    shutil.copy2(base_src, base_dest)
                if out_sidecar.resolve() != sidecar_dest.resolve():
                    shutil.copy2(out_sidecar, sidecar_dest)

                report["final_outputs"] = {
                    "base": str(base_dest),
                    "sidecar": str(sidecar_dest),
                    "root": str(final_root),
                }

                work_root = _injector_work_root()
                if _is_within(final_root, work_root):
                    report.setdefault("warnings", []).append(
                        "final output root resolved inside temp work root; skipped cleanup to avoid deleting final outputs"
                    )
                else:
                    report["post_build_cleanup"] = _cleanup_after_final_copy(base)
            else:
                report.setdefault("warnings", []).append(
                    "no final output destination provided; skipped final copy/cleanup"
                )

        print(
            json.dumps(
                {
                    "ok": True,
                    "report": report,
                    "report_json": report_to_json(report),
                }
            )
        )
        return 0
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
