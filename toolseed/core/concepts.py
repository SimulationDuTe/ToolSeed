"""Small, explicit concept aliases for local bilingual retrieval.

These are retrieval hints, never declarations of compatible tools or authority.
Long-tail vocabulary belongs in an experience's aliases and recognition cues.
"""
from __future__ import annotations

import re
import unicodedata

ALIASES: dict[str, tuple[str, ...]] = {
    "image": ("image", "images", "png", "texture", "textures", "图像", "图片", "贴图"),
    "transparency": ("alpha", "transparency", "transparent", "透明", "阿尔法"),
    "export": ("export", "exports", "exported", "exporting", "导出"),
    "sprite": ("sprite", "sprites", "精灵", "像素角色"),
    "background": ("background", "backgrounds", "底图", "背景", "底色"),
    "opaque_background": ("opaque background", "black background", "black backdrop", "黑底", "黑色底", "不透明背景"),
    "checkerboard": ("checkerboard", "checker board", "棋盘格", "棋盘背景"),
    "timeout": ("timeout", "timeouts", "timed out", "超时"),
    "connection": ("connection", "connectivity", "network", "连接", "网络"),
    "retry": ("retry", "retries", "backoff", "重试", "退避"),
    "permission": ("permission", "permissions", "access denied", "permission denied", "权限", "拒绝访问"),
    "sandbox": ("sandbox", "sandboxed", "沙箱"),
    "dependency": ("dependency", "dependencies", "依赖"),
    "installation": ("install", "installed", "installation", "安装"),
    "configuration": ("configuration", "config", "配置"),
    "migration": ("migration", "migrate", "迁移"),
    "database": ("database", "sqlite", "数据库"),
    "validation": ("validate", "validation", "verification", "验证", "校验"),
}


def _pattern(alias: str) -> re.Pattern[str]:
    if alias.isascii():
        return re.compile(r"(?<![a-z0-9_])" + re.escape(alias).replace(r"\ ", r"[\s_-]+") + r"(?![a-z0-9_])")
    return re.compile(re.escape(alias))


PATTERNS = {concept: tuple(_pattern(alias) for alias in aliases) for concept, aliases in ALIASES.items()}


def concepts(text: str) -> set[str]:
    text = unicodedata.normalize("NFKC", text).casefold()
    return {name for name, patterns in PATTERNS.items() if any(pattern.search(text) for pattern in patterns)}
