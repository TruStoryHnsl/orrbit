"""
Thumbnail generation for orrbit.

Generates preview thumbnails for videos, images, PDFs, and EPUBs.
Caches thumbnails in DATA_DIR/thumbs/
"""

import hashlib
import json
import logging
import os
import subprocess
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Cache directory — initialized by init_thumb_cache()
THUMB_CACHE: Optional[Path] = None

# Thumbnail sizes
THUMB_WIDTH = 320
THUMB_HEIGHT = 180

# Check for required tools
FFMPEG_BIN = shutil.which('ffmpeg')
FFPROBE_BIN = shutil.which('ffprobe')


def init_thumb_cache(data_dir: str):
    """Initialize the thumbnail cache directory."""
    global THUMB_CACHE
    THUMB_CACHE = Path(data_dir) / 'thumbs'
    THUMB_CACHE.mkdir(parents=True, exist_ok=True)


def get_thumb_path(file_path: Path) -> Path:
    """Get cached thumbnail path for a file."""
    # Use hash of path + mtime for cache key
    stat = file_path.stat()
    cache_key = f"{file_path}:{stat.st_mtime}"
    hash_name = hashlib.md5(cache_key.encode()).hexdigest()
    return THUMB_CACHE / f"{hash_name}.jpg"


def has_thumbnail(file_path: Path) -> bool:
    """Check if a cached thumbnail exists."""
    if not THUMB_CACHE:
        return False
    thumb_path = get_thumb_path(file_path)
    return thumb_path.exists()


def generate_video_thumbnail(file_path: Path) -> Optional[Path]:
    """Generate thumbnail from video at 10% duration."""
    if not FFMPEG_BIN or not THUMB_CACHE:
        return None

    thumb_path = get_thumb_path(file_path)
    if thumb_path.exists():
        return thumb_path

    try:
        # Get video duration
        duration = get_video_duration(file_path)
        if duration is None:
            seek_time = "00:00:05"  # Default to 5 seconds
        else:
            # Seek to 10% of duration
            seek_seconds = max(1, int(duration * 0.1))
            seek_time = f"{seek_seconds // 3600:02d}:{(seek_seconds % 3600) // 60:02d}:{seek_seconds % 60:02d}"

        cmd = [
            FFMPEG_BIN,
            '-ss', seek_time,
            '-i', str(file_path),
            '-vframes', '1',
            '-vf', f'scale={THUMB_WIDTH}:-2',
            '-q:v', '3',
            '-y',
            str(thumb_path)
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and thumb_path.exists():
            return thumb_path
    except (subprocess.TimeoutExpired, Exception) as e:
        logger.warning("Error generating video thumb: %s", e)

    return None


def get_video_duration(file_path: Path) -> Optional[float]:
    """Get video duration in seconds using ffprobe."""
    if not FFPROBE_BIN:
        return None

    try:
        cmd = [
            FFPROBE_BIN,
            '-v', 'quiet',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, Exception):
        pass
    return None


def get_video_metadata(file_path: Path) -> dict:
    """Get video metadata (duration, resolution) for display labels."""
    metadata = {'duration': None, 'width': None, 'height': None}

    if not FFPROBE_BIN:
        return metadata

    try:
        cmd = [
            FFPROBE_BIN,
            '-v', 'quiet',
            '-show_entries', 'format=duration:stream=width,height',
            '-select_streams', 'v:0',
            '-of', 'json',
            str(file_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            data = json.loads(result.stdout)

            if 'format' in data and 'duration' in data['format']:
                metadata['duration'] = float(data['format']['duration'])

            if 'streams' in data and data['streams']:
                stream = data['streams'][0]
                metadata['width'] = stream.get('width')
                metadata['height'] = stream.get('height')
    except Exception as e:
        logger.warning("Error getting video metadata: %s", e)

    return metadata


def format_duration(seconds: Optional[float]) -> str:
    """Format duration as H:MM:SS or M:SS."""
    if seconds is None:
        return ""
    seconds = int(seconds)
    if seconds >= 3600:
        return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def generate_image_thumbnail(file_path: Path) -> Optional[Path]:
    """Generate thumbnail from image using ffmpeg."""
    if not FFMPEG_BIN or not THUMB_CACHE:
        return None

    thumb_path = get_thumb_path(file_path)
    if thumb_path.exists():
        return thumb_path

    try:
        cmd = [
            FFMPEG_BIN,
            '-i', str(file_path),
            '-vf', f'scale={THUMB_WIDTH}:-2',
            '-q:v', '3',
            '-y',
            str(thumb_path)
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if result.returncode == 0 and thumb_path.exists():
            return thumb_path
    except Exception as e:
        logger.warning("Error generating image thumb: %s", e)

    return None


def generate_pdf_thumbnail(file_path: Path) -> Optional[Path]:
    """Generate thumbnail from first page of PDF using pdftoppm or convert."""
    if not THUMB_CACHE:
        return None

    thumb_path = get_thumb_path(file_path)
    if thumb_path.exists():
        return thumb_path

    # Try pdftoppm first (from poppler-utils)
    pdftoppm = shutil.which('pdftoppm')
    if pdftoppm:
        try:
            cmd = [
                pdftoppm,
                '-jpeg',
                '-f', '1', '-l', '1',
                '-scale-to', str(THUMB_WIDTH),
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and result.stdout:
                thumb_path.write_bytes(result.stdout)
                return thumb_path
        except Exception as e:
            logger.warning("pdftoppm error: %s", e)

    # Fallback to ImageMagick convert
    convert = shutil.which('convert')
    if convert:
        try:
            cmd = [
                convert,
                '-density', '150',
                f'{file_path}[0]',
                '-resize', f'{THUMB_WIDTH}x{THUMB_HEIGHT}',
                '-quality', '85',
                str(thumb_path)
            ]
            result = subprocess.run(cmd, capture_output=True, timeout=30)
            if result.returncode == 0 and thumb_path.exists():
                return thumb_path
        except Exception as e:
            logger.warning("convert error: %s", e)

    return None


def generate_epub_thumbnail(file_path: Path) -> Optional[Path]:
    """Extract cover from EPUB file."""
    if not THUMB_CACHE:
        return None

    thumb_path = get_thumb_path(file_path)
    if thumb_path.exists():
        return thumb_path

    try:
        with zipfile.ZipFile(file_path, 'r') as epub:
            cover_patterns = ['cover.jpg', 'cover.jpeg', 'cover.png', 'Cover.jpg', 'Cover.jpeg', 'Cover.png']

            for name in epub.namelist():
                name_lower = name.lower()
                if any(p.lower() in name_lower for p in cover_patterns) or 'cover' in name_lower and name_lower.endswith(('.jpg', '.jpeg', '.png')):
                    cover_data = epub.read(name)
                    temp_path = THUMB_CACHE / f"temp_{thumb_path.name}"
                    temp_path.write_bytes(cover_data)

                    if FFMPEG_BIN:
                        cmd = [
                            FFMPEG_BIN,
                            '-i', str(temp_path),
                            '-vf', f'scale={THUMB_WIDTH}:-1',
                            '-q:v', '3',
                            '-y',
                            str(thumb_path)
                        ]
                        subprocess.run(cmd, capture_output=True, timeout=10)
                        temp_path.unlink()

                        if thumb_path.exists():
                            return thumb_path
                    else:
                        temp_path.rename(thumb_path)
                        return thumb_path
                    break
    except Exception as e:
        logger.warning("EPUB error: %s", e)

    return None


def generate_comic_thumbnail(file_path: Path) -> Optional[Path]:
    """Extract first image from CBZ/CBR comic archive."""
    if not THUMB_CACHE:
        return None

    thumb_path = get_thumb_path(file_path)
    if thumb_path.exists():
        return thumb_path

    suffix = file_path.suffix.lower()

    try:
        if suffix == '.cbz':
            with zipfile.ZipFile(file_path, 'r') as cbz:
                image_files = sorted([
                    n for n in cbz.namelist()
                    if n.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
                    and not n.startswith('__MACOSX')
                ])
                if image_files:
                    img_data = cbz.read(image_files[0])
                    temp_path = THUMB_CACHE / f"temp_{thumb_path.name}"
                    temp_path.write_bytes(img_data)

                    if FFMPEG_BIN:
                        cmd = [
                            FFMPEG_BIN,
                            '-i', str(temp_path),
                            '-vf', f'scale={THUMB_WIDTH}:-1',
                            '-q:v', '3',
                            '-y',
                            str(thumb_path)
                        ]
                        subprocess.run(cmd, capture_output=True, timeout=10)
                        temp_path.unlink()
                        if thumb_path.exists():
                            return thumb_path
                    else:
                        temp_path.rename(thumb_path)
                        return thumb_path

        elif suffix == '.cbr':
            unrar = shutil.which('unrar')
            if unrar:
                with tempfile.TemporaryDirectory() as tmpdir:
                    list_cmd = [unrar, 'lb', str(file_path)]
                    result = subprocess.run(list_cmd, capture_output=True, text=True, timeout=10)
                    if result.returncode == 0:
                        image_files = sorted([
                            n for n in result.stdout.strip().split('\n')
                            if n.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))
                        ])
                        if image_files:
                            extract_cmd = [unrar, 'e', '-o+', str(file_path), image_files[0], tmpdir]
                            subprocess.run(extract_cmd, capture_output=True, timeout=30)

                            extracted = Path(tmpdir) / Path(image_files[0]).name
                            if extracted.exists() and FFMPEG_BIN:
                                cmd = [
                                    FFMPEG_BIN,
                                    '-i', str(extracted),
                                    '-vf', f'scale={THUMB_WIDTH}:-1',
                                    '-q:v', '3',
                                    '-y',
                                    str(thumb_path)
                                ]
                                subprocess.run(cmd, capture_output=True, timeout=10)
                                if thumb_path.exists():
                                    return thumb_path
    except Exception as e:
        logger.warning("Comic error: %s", e)

    return None


def generate_thumbnail(file_path: Path, file_type: str, mime: str) -> Optional[Path]:
    """Generate thumbnail based on file type."""
    if file_type == 'video':
        return generate_video_thumbnail(file_path)
    elif file_type == 'image':
        return generate_image_thumbnail(file_path)
    elif file_type == 'pdf':
        return generate_pdf_thumbnail(file_path)
    elif file_type == 'epub' or mime == 'application/epub+zip':
        return generate_epub_thumbnail(file_path)
    elif file_type == 'comic' or mime in ('application/vnd.comicbook+zip', 'application/vnd.comicbook-rar'):
        return generate_comic_thumbnail(file_path)
    return None


def get_directory_view_mode(items: list) -> str:
    """
    Determine the best view mode for a directory based on its contents.

    Returns: 'video', 'image', 'document', or 'list'
    """
    if not items:
        return 'list'

    type_counts = {'video': 0, 'image': 0, 'pdf': 0, 'epub': 0, 'text': 0, 'other': 0, 'dir': 0}
    for item in items:
        if item.is_dir:
            type_counts['dir'] += 1
        elif item.file_type in type_counts:
            type_counts[item.file_type] += 1
        elif item.mime == 'application/epub+zip' or (hasattr(item, 'path') and item.path.endswith('.epub')):
            type_counts['epub'] += 1
        else:
            type_counts['other'] += 1

    total_files = sum(type_counts.values()) - type_counts['dir']
    if total_files == 0:
        return 'list'

    threshold = total_files * 0.7

    if type_counts['video'] >= threshold:
        return 'video'
    elif type_counts['image'] >= threshold:
        return 'image'
    elif type_counts['pdf'] + type_counts['epub'] >= threshold:
        return 'document'

    return 'list'
