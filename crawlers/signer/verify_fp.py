"""verify_fp / s_v_web_id 生成模块。

verify_fp 与 s_v_web_id 是抖音 Web 前端生成的设备标识/校验参数，
格式形如 ``verify_xxxxxxxx_xxxxxxxx_xxxx_xxxx_xxxx_xxxxxxxxxxxx``。

实现方式：基于时间戳与密码学安全随机数生成，格式对齐抖音前端样本。
每次调用产生不同的值。

输入/输出契约：
    - 输入：无（基于时间戳与随机数生成）
    - 输出：verify_fp 字符串（含 ``verify_`` 前缀）
    - 每次调用产生不同的值
"""

from __future__ import annotations

import secrets
import string

from crawlers.exceptions import SignError

# verify_fp / s_v_web_id 前缀
_VERIFY_FP_PREFIX: str = "verify_"

# 随机小写字母段长度
_RANDOM_LOWER_LEN: int = 8

# UUID 风格字符串各段长度：8-4-4-4-12
_UUID_SEGMENTS: tuple[int, ...] = (8, 4, 4, 4, 12)

# 字符集
_LOWER_LETTERS: str = string.ascii_lowercase
_ALPHANUM: str = string.ascii_letters + string.digits


def _random_string(length: int, charset: str) -> str:
    """生成指定长度的随机字符串。

    参数:
        length: 字符串长度。
        charset: 字符集。

    返回:
        随机字符串。
    """
    return "".join(secrets.choice(charset) for _ in range(length))


def _build_uuid_like() -> str:
    """构建 UUID 风格字符串（8-4-4-4-12 格式）。

    返回:
        UUID 风格字符串，如 ``dtOkZ4fO_5jE9_4dlp_9bj7_GWF0F7uMSTAr``。
    """
    segments = [_random_string(seg_len, _ALPHANUM) for seg_len in _UUID_SEGMENTS]
    return "_".join(segments)


class VerifyFpGenerator:
    """verify_fp / s_v_web_id 生成器。

    按抖音前端算法生成 ``verify_`` 前缀的设备标识参数。
    格式：``verify_<8位随机小写字母>_<UUID风格字符串>``

    每次调用产生不同的值，基于时间戳与密码学安全随机数。
    """

    def __init__(self) -> None:
        """初始化 verify_fp 生成器。"""

    def generate(self) -> str:
        """生成 verify_fp 参数值。

        返回:
            verify_fp 字符串（含 ``verify_`` 前缀，约 45 字符）。

        异常:
            SignError: 生成失败。
        """
        try:
            # 8 位随机小写字母
            random_lower = _random_string(_RANDOM_LOWER_LEN, _LOWER_LETTERS)

            # UUID 风格字符串
            uuid_like = _build_uuid_like()

            return f"{_VERIFY_FP_PREFIX}{random_lower}_{uuid_like}"
        except Exception as e:
            raise SignError(f"verify_fp 生成失败: {e}", algorithm="verify_fp") from e

    def generate_s_v_web_id(self) -> str:
        """生成 s_v_web_id 参数值。

        s_v_web_id 与 verify_fp 格式相同，复用 generate() 逻辑。

        返回:
            s_v_web_id 字符串（含 ``verify_`` 前缀）。

        异常:
            SignError: 生成失败。
        """
        return self.generate()
