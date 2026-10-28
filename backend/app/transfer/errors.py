"""导入 / 导出共用的领域异常与工具。

所有域（预设、长期记忆、知识库）遵循同一套语义：

- 文件结构不合法 → ``import_package_invalid``（HTTP 422）
- 文件过大 → ``import_package_too_large``（HTTP 413）
- 预览 token 过期 → ``import_preview_expired``（HTTP 409）

具体 HTTP 映射仍由各 API 层完成，服务层只抛领域异常。
"""

from __future__ import annotations


class ImportPackageError(Exception):
    """导入文件内容不合法。"""

    error_type = "import_package_invalid"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class ImportPackageTooLargeError(ImportPackageError):
    """导入文件超过大小 / 数量限制。"""

    error_type = "import_package_too_large"


class ImportPreviewExpiredError(Exception):
    """预览已过期或 token 不存在。"""

    error_type = "import_preview_expired"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
