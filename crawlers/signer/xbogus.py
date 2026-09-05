"""X-Bogus 签名算法（纯 Python 自主实现）。

基于抖音 Web 前端 X-Bogus 签名算法的公开原理分析自主实现，不依赖任何
JS 执行环境，仅使用 Python 标准库。

算法核心流程：
    1. 从请求 URL 中提取查询参数串（payload）
    2. 对 payload、表单数据、User-Agent 分别计算双重 MD5 盐值
    3. 组合盐值末字节、时间戳、canvas 码、校验位，构建 19 字节操作数组
    4. 对操作数组重排并经 RC4 流密码加密，得到 21 字节混淆串
    5. 使用自定义字符表进行 Base64 变体编码，输出 28 字符 X-Bogus 值

参考方向（仅参考原理，不 vendoring 代码）：
    - 公开的 X-Bogus 算法逆向分析文档
    - Evil0ctal/Douyin_TikTok_Download_API 项目的设计思路

输入/输出契约：
    - 输入：规范化后的请求 URL（含完整查询参数）+ User-Agent 字符串
    - 输出：28 字符的 X-Bogus 签名字符串
    - 同一输入 + 同一时间戳产生确定输出
"""

from __future__ import annotations

import base64
import hashlib
import time

from crawlers.exceptions import SignError

# 自定义 Base64 变体字符表（65 字符，末位为填充符）
# 来源：抖音 Web 前端 webmssdk.js 中的常量，与标准 Base64 字符表顺序不同
_BOGUS_BASE64_TABLE: str = "Dkdpgh4ZKsQB80/Mfvw36XI1R25-WUAlEi7NLboqYTOPuzmFjJnryx9HVGcaStCe="

# canvas 指纹固定值（抖音前端固定常量）
_CANVAS_CODE: int = 536919696  # 逆向自抖音前端固定 canvas 指纹值

# RC4 流密码密钥
# UA 处理用的密钥：对应抖音前端固定字节 [0x00, 0x01, 0x0C]
_UA_RC4_KEY: bytes = bytes([0, 1, 12])
# 混淆串处理用的密钥：对应抖音前端固定字节 [0xFF]
_GARBLE_RC4_KEY: bytes = bytes([255])

# arr1 固定头部字节（抖音前端固定常量）
_ARR1_HEADER: tuple[int, ...] = (64, 0, 1, 12)

# arr1 校验位固定值（异或校验的初始值）
_ARR1_CHECKSUM_INIT: int = 64


def _rc4(key: bytes, data: bytes) -> bytes:
    """RC4 流密码加密。

    使用密钥调度算法（KSA）初始化 S-Box，再用伪随机生成算法（PRGA）
    生成密钥流与数据逐字节异或。

    参数:
        key: 密钥字节序列。
        data: 待加密数据字节序列。

    返回:
        加密后的字节序列（长度与 data 相同）。
    """
    # KSA: 密钥调度，初始化 S-Box
    s_box = list(range(256))
    j = 0
    key_len = len(key)
    for i in range(256):
        j = (j + s_box[i] + key[i % key_len]) % 256
        s_box[i], s_box[j] = s_box[j], s_box[i]

    # PRGA: 伪随机生成，产生密钥流并异或
    i = 0
    j = 0
    result = bytearray(len(data))
    for k in range(len(data)):
        i = (i + 1) % 256
        j = (j + s_box[i]) % 256
        s_box[i], s_box[j] = s_box[j], s_box[i]
        result[k] = data[k] ^ s_box[(s_box[i] + s_box[j]) % 256]

    return bytes(result)


def _double_md5(data: bytes) -> bytes:
    """计算双重 MD5 哈希（MD5(MD5(data))）。

    参数:
        data: 原始字节序列。

    返回:
        16 字节哈希值。
    """
    return hashlib.md5(hashlib.md5(data).digest()).digest()


def _build_operation_array(payload: str, form: str, user_agent: str, timestamp: int) -> list[int]:
    """构建 19 字节操作数组 arr2。

    将 payload、form、User-Agent 的双重 MD5 盐值末字节与时间戳、canvas 码
    组合为 19 字节 arr1，经异或校验和重排后得到 arr2。

    参数:
        payload: 查询参数串。
        form: 表单数据（GET 请求通常为空字符串）。
        user_agent: User-Agent 字符串。
        timestamp: Unix 时间戳（秒）。

    返回:
        19 字节操作数组。
    """
    # 各输入的双重 MD5 盐值
    salt_payload = _double_md5(payload.encode("utf-8"))
    salt_form = _double_md5(form.encode("utf-8"))

    # User-Agent 经 RC4 加密后再 base64 编码，最后取 MD5
    ua_encrypted = _rc4(_UA_RC4_KEY, user_agent.encode("ISO-8859-1"))
    salt_ua = hashlib.md5(base64.b64encode(ua_encrypted)).digest()

    # arr1: 19 字节（4 固定头 + 6 盐值末字节 + 4 时间戳 + 4 canvas + 1 校验位）
    arr1: list[int] = [
        _ARR1_HEADER[0],
        _ARR1_HEADER[1],
        _ARR1_HEADER[2],
        _ARR1_HEADER[3],
        salt_payload[14],
        salt_payload[15],
        salt_form[14],
        salt_form[15],
        salt_ua[14],
        salt_ua[15],
        (timestamp >> 24) & 0xFF,
        (timestamp >> 16) & 0xFF,
        (timestamp >> 8) & 0xFF,
        timestamp & 0xFF,
        (_CANVAS_CODE >> 24) & 0xFF,
        (_CANVAS_CODE >> 16) & 0xFF,
        (_CANVAS_CODE >> 8) & 0xFF,
        _CANVAS_CODE & 0xFF,
        _ARR1_CHECKSUM_INIT,
    ]

    # 校验位: arr1[1..17] 逐字节异或到 arr1[18]
    for i in range(1, 18):
        arr1[18] ^= arr1[i]

    # arr2: 将 arr1 的偶数位和奇数位交错重排
    arr2 = [
        arr1[0],
        arr1[2],
        arr1[4],
        arr1[6],
        arr1[8],
        arr1[10],
        arr1[12],
        arr1[14],
        arr1[16],
        arr1[18],
        arr1[1],
        arr1[3],
        arr1[5],
        arr1[7],
        arr1[9],
        arr1[11],
        arr1[13],
        arr1[15],
        arr1[17],
    ]

    return arr2


def _build_garbled_string(arr2: list[int]) -> list[int]:
    """构建 21 字节混淆字符串。

    对 arr2 进行重排得到 19 字节序列，经 RC4 加密后前置 [2, 255] 标记字节，
    得到 21 字节混淆字符串。

    参数:
        arr2: 19 字节操作数组。

    返回:
        21 字节混淆字符串。
    """
    # 重排 arr2: 交错取前后半段
    reordered = [
        arr2[0],
        arr2[10],
        arr2[1],
        arr2[11],
        arr2[2],
        arr2[12],
        arr2[3],
        arr2[13],
        arr2[4],
        arr2[14],
        arr2[5],
        arr2[15],
        arr2[6],
        arr2[16],
        arr2[7],
        arr2[17],
        arr2[8],
        arr2[18],
        arr2[9],
    ]

    # RC4 加密 19 字节
    encrypted = _rc4(_GARBLE_RC4_KEY, bytes(reordered))

    # 前置标记字节 [2, 255]
    return [2, 255] + list(encrypted)


def _bogus_base64_encode(data: list[int]) -> str:
    """使用自定义字符表进行 Base64 变体编码。

    每 3 字节为一组，组合为 24 位整数，拆分为 4 个 6 位索引，查表得到 4 字符。
    21 字节 / 3 = 7 组，输出 28 字符。

    参数:
        data: 21 字节待编码数据。

    返回:
        28 字符编码结果。
    """
    result: list[str] = []
    for i in range(0, 21, 3):
        n0 = data[i]
        n1 = data[i + 1]
        n2 = data[i + 2]
        base = (n0 << 16) | (n1 << 8) | n2
        result.append(_BOGUS_BASE64_TABLE[(base & 0xFC0000) >> 18])
        result.append(_BOGUS_BASE64_TABLE[(base & 0x3F000) >> 12])
        result.append(_BOGUS_BASE64_TABLE[(base & 0xFC0) >> 6])
        result.append(_BOGUS_BASE64_TABLE[base & 0x3F])
    return "".join(result)


def _extract_query_string(url: str) -> str:
    """从 URL 中提取查询参数串。

    若 URL 含 '?'，取 '?' 之后的部分；否则视为已是查询参数串。

    参数:
        url: 请求 URL 或查询参数串。

    返回:
        查询参数串。
    """
    if "?" in url:
        return url.split("?", 1)[1]
    return url


class XBogusSigner:
    """X-Bogus 签名算法。

    输入：规范化后的请求 URL（含查询参数）+ User-Agent。
    输出：28 字符的 X-Bogus 签名字符串。

    同一输入 + 同一时间戳产生确定输出。生产环境使用当前时间戳，
    测试时可注入固定时间戳以确保确定性。
    """

    def __init__(self, timestamp: int | None = None) -> None:
        """初始化 X-Bogus 签名器。

        参数:
            timestamp: 固定 Unix 时间戳（秒），用于测试时确保确定性输出。
                None 时使用当前时间戳。
        """
        self._timestamp = timestamp

    def sign(self, url: str, user_agent: str) -> str:
        """生成 X-Bogus 签名。

        参数:
            url: 请求 URL（含完整查询参数）或纯查询参数串。
            user_agent: User-Agent 字符串。

        返回:
            28 字符的 X-Bogus 签名字符串。

        异常:
            SignError: 输入为空或类型无效，或算法计算失败。
        """
        try:
            if not url or not isinstance(url, str):
                raise SignError("URL 不能为空", algorithm="xbogus")
            if not user_agent or not isinstance(user_agent, str):
                raise SignError("User-Agent 不能为空", algorithm="xbogus")

            # 提取查询参数串（不做 URL 解码，与抖音前端保持一致）
            payload = _extract_query_string(url)

            # 表单数据默认为空（GET 请求无表单）
            form = ""

            # 获取时间戳
            ts = self._timestamp if self._timestamp is not None else int(time.time())

            # 构建操作数组
            arr2 = _build_operation_array(payload, form, user_agent, ts)

            # 构建混淆字符串
            garbled = _build_garbled_string(arr2)

            # Base64 变体编码
            return _bogus_base64_encode(garbled)
        except SignError:
            raise
        except Exception as e:
            raise SignError(f"X-Bogus 签名计算失败: {e}", algorithm="xbogus") from e
