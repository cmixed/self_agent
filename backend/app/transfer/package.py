"""导入导出共用的打包工具：导出文件名、UTF-8 JSON、zip 安全校验。"""

from __future__ import annotations

import io
import json
import posixpath
import stat
import zipfile
from datetime import UTC, datetime
from pathlib import PurePosixPath

from app.transfer.errors import ImportPackageError, ImportPackageTooLargeError


def export_filename(prefix: str, suffix: str) -> str:
    """生成带 UTC 时间戳的下载文件名，如 ``presets-20261028-120000.json``。"""
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{prefix}-{stamp}.{suffix.lstrip('.')}"


def decode_json(data: bytes, *, error_message: str = "文件不是有效的 JSON") -> object:
    """按 UTF-8（允许 BOM）解码并解析 JSON。"""
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportPackageError("文件不是 UTF-8 文本") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ImportPackageError(error_message) from exc


def encode_json(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def safe_zip_member(name: str, *, max_length: int = 200) -> str:
    """规范化并校验 zip 内路径，拒绝绝对路径与 ``..`` 穿越。"""
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute():
        raise ImportPackageError(f"压缩包包含绝对路径：{name}")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ImportPackageError(f"压缩包包含非法路径：{name}")
    if len(normalized) > max_length:
        raise ImportPackageError(f"压缩包文件路径过长：{name}")
    return normalized


def is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    return (info.external_attr >> 16) & 0o170000 == stat.S_IFLNK


def open_zip(
    data: bytes,
    *,
    max_bytes: int,
    max_uncompressed_bytes: int,
    max_files: int,
) -> zipfile.ZipFile:
    """打开并做基础安全校验；调用方负责 ``with`` 关闭。"""
    if len(data) > max_bytes:
        raise ImportPackageTooLargeError(f"压缩包超过 {max_bytes // (1024 * 1024)} MB 限制")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportPackageError("上传的文件不是有效的 zip 压缩包") from exc

    infos = [info for info in archive.infolist() if not info.is_dir()]
    try:
        if len(infos) > max_files:
            raise ImportPackageTooLargeError(f"压缩包最多包含 {max_files} 个文件")
        if sum(info.file_size for info in infos) > max_uncompressed_bytes:
            raise ImportPackageTooLargeError("压缩包解压后超过大小限制")
        for info in infos:
            if is_zip_symlink(info):
                raise ImportPackageError(f"压缩包不能包含符号链接：{info.filename}")
            safe_zip_member(info.filename)
    except Exception:
        archive.close()
        raise
    return archive


def zip_dirname(name: str) -> str:
    return posixpath.dirname(name)
