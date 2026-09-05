"""爬虫层通用小工具。

审计 S8：抖音接口常用 ``int(status_code or 0)`` 做防御性转换，但若
接口返回非数字字符串（如 ``"未知"``）会抛未捕获 ValueError 中断整个
抓取循环。统一收敛为 ``safe_int``。
"""

from __future__ import annotations


def safe_int(value, default: int = 0) -> int:
    """防御性 int 转换：None/空串/非数字字符串一律返回 default。

    参数:
        value: 待转换值（int/str/float/None 等）。
        default: 转换失败时的兜底值，默认 0。

    返回:
        转换成功的 int，失败返回 default（不抛 ValueError/TypeError）。
    """
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
