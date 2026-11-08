"""Decode images and inspect browser-compatible MP4s before moderation."""
import io
import json
import math
import os
import platform
from pathlib import Path
import shutil
import subprocess
import tempfile

from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError


def check_dimensions(width, height, target_width, target_height):
    if width < 320 or height < 180 or width * height > 16_000_000:
        raise HTTPException(422, 'Resolusi materi harus minimal 320×180 dan maksimal 16 megapiksel')
    if abs(width / height - target_width / target_height) > 0.04:
        raise HTTPException(422, f'Rasio materi harus sesuai layar {target_width}×{target_height}')


def validate_media(data, mime, width, height):
    if mime.startswith('image/'):
        try:
            with Image.open(io.BytesIO(data)) as original:
                check_dimensions(*original.size, width, height)
                original.verify()
            with Image.open(io.BytesIO(data)) as original:
                image = ImageOps.exif_transpose(original).convert('RGB')
                check_dimensions(*image.size, width, height)
                output = io.BytesIO()
                image.save(output, format='PNG' if mime == 'image/png' else 'JPEG')
                return output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(422, 'Gambar rusak atau tidak dapat dibaca')
    with tempfile.NamedTemporaryFile(suffix='.mp4') as file:
        file.write(data)
        file.flush()
        metadata = probe_video(file.name)
    try:
        streams = [stream for stream in metadata.get('streams', []) if stream.get('codec_type') == 'video']
        duration = float(metadata.get('format', {}).get('duration', 0))
        if not streams or streams[0].get('codec_name') != 'h264' or not math.isfinite(duration) or duration <= 0 or metadata.get('playable') is False:
            raise ValueError('Unsupported video')
        stream = streams[0]
        width_px, height_px = int(stream['width']), int(stream['height'])
        rotations = [entry.get('rotation',0) for entry in stream.get('side_data_list', [])]
        rotation = float(rotations[0] if rotations else stream.get('tags', {}).get('rotate',0))
        if abs(rotation) % 180 == 90:
            width_px, height_px = height_px, width_px
        check_dimensions(width_px, height_px, width, height)
    except (ValueError, KeyError, TypeError, OverflowError):
        raise HTTPException(422, 'Video harus berupa MP4 H.264 yang valid dan dapat diputar')
    return data


def _metadata(output):
    try:
        # Native frameworks may emit diagnostic text before their JSON output.
        decoded = output.decode('utf-8', errors='replace')
        result = json.loads(decoded[decoded.index('{'):])
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise HTTPException(503, 'Validator video tidak memberikan hasil yang valid; hubungi operator')


def probe_video(path):
    binary = os.getenv('FFPROBE_PATH') or shutil.which('ffprobe')
    unavailable = not binary
    if binary:
        try:
            result = subprocess.run([binary,'-v','error','-show_streams','-show_format','-of','json',path], capture_output=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            unavailable = True
        else:
            if result.returncode == 0:
                return _metadata(result.stdout)
            errors = result.stderr.decode('utf-8', errors='replace').lower()
            unavailable = result.returncode < 0 or any(marker in errors for marker in ('library not loaded','error while loading shared libraries','dyld[','symbol not found','bad cpu type'))
            if not unavailable:
                raise HTTPException(422, 'File MP4 tidak dapat dibaca. Periksa file video atau ekspor ulang sebagai H.264.')
    if unavailable and platform.system() == 'Darwin' and shutil.which('swift'):
        cache = Path(tempfile.gettempdir()) / ('lamia-video-probe-' + str(os.getuid()))
        cache.mkdir(mode=0o700, exist_ok=True)
        try:
            result = subprocess.run([shutil.which('swift'),'-module-cache-path',str(cache),str(Path(__file__).parent/'video_probe_macos.swift'),path], capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            raise HTTPException(503, 'Pemeriksaan video belum tersedia. Hubungi operator untuk memperbaiki validator server.')
        if result.returncode == 0:
            return _metadata(result.stdout)
    raise HTTPException(503, 'Validator video pada server tidak dapat dijalankan. Hubungi operator; file Anda belum dinyatakan tidak valid.')
