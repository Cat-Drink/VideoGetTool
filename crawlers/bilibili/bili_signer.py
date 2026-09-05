"""B 站 WBI 签名器 + buvid3 指纹生成器。

WBI 签名是 B 站用于 API 鉴权的签名机制，替代旧版签名。算法：
    1. 从 /x/web-interface/nav（未登录 code=-101 时仍返回 data.wbi_img）获取
       img_url / sub_url，取文件 basename 作为 img_key / sub_key
    2. 混合密钥: mix_key = "".join((img_key + sub_key)[i] for i in MIXIN_KEY_ENC_TAB)[:32]
    3. 参数过滤 '!'()*' 特殊字符，按 key 升序排序并 urlencode
    4. w_rid = MD5(query_string + mix_key)；wts = 当前 Unix 时间戳

buvid3 是 B 站客户端指纹，用于标识设备，需通过 Cookie 或请求头发送。

参考方向:
    - SocialSisterYi/bilibili-API-collect（已归档）的 WBI 签名文档
    - 各开源 B 站下载器的公开实现
"""

from __future__ import annotations

import hashlib
import secrets
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse

import httpx

from crawlers.bilibili.constants import (
    DEFAULT_HEADERS,
    NAV_URL,
    WBI_KEY_CACHE_TTL,
)
from crawlers.exceptions import SignError

# B 站官方 WBI 混合密钥置换表（64 项，0~63）
# 将 (img_key + sub_key) 按该表重排后取前 32 位作为 mix_key
MIXIN_KEY_ENC_TAB: list[int] = [
    46,
    47,
    18,
    2,
    53,
    8,
    23,
    32,
    15,
    50,
    10,
    31,
    58,
    3,
    45,
    35,
    27,
    43,
    5,
    49,
    33,
    9,
    42,
    19,
    29,
    28,
    14,
    39,
    12,
    38,
    41,
    13,
    37,
    48,
    7,
    16,
    24,
    55,
    40,
    61,
    26,
    17,
    0,
    1,
    60,
    51,
    30,
    4,
    22,
    25,
    54,
    21,
    56,
    59,
    6,
    63,
    57,
    62,
    11,
    36,
    20,
    34,
    44,
    52,
]

# 签名时需从值中剔除的特殊字符（B 站官方 WBI 算法）
_WBI_FILTER_CHARS: str = "!'()*"


def _derive_key_from_url(url: str) -> str:
    """从 wbi_img.img_url / sub_url 中提取文件 basename（不含扩展名）。"""
    return Path(urlparse(url).path).stem


class BiliSigner:
    """B 站 WBI 签名器。

    管理 WBI 密钥的获取、缓存与使用，为请求参数添加 w_rid 和 wts 签名。
    同时提供 buvid3 指纹生成。

    线程安全：所有状态读写发生在单线程协程环境。
    """

    def __init__(self) -> None:
        self._img_key: str = ""
        self._sub_key: str = ""
        self._mix_key: str = ""
        self._key_updated_at: float = 0.0

    # === WBI 密钥管理 ===

    @property
    def _keys_expired(self) -> bool:
        """密钥是否已过期。"""
        if not self._img_key or not self._sub_key:
            return True
        elapsed = time.time() - self._key_updated_at
        return elapsed >= WBI_KEY_CACHE_TTL

    async def refresh_keys(self, http_client: httpx.AsyncClient | None = None) -> None:
        """从 /x/web-interface/nav 刷新 WBI 密钥。

        参数:
            http_client: httpx 异步客户端；为 None 时内部创建临时客户端。

        异常:
            SignError: 密钥获取失败。
        """
        close_client = False
        if http_client is None:
            http_client = httpx.AsyncClient(
                headers=DEFAULT_HEADERS,
                timeout=httpx.Timeout(connect=10.0, read=10.0),
            )
            close_client = True

        try:
            resp = await http_client.get(NAV_URL)
            resp.raise_for_status()
            payload = resp.json()

            # nav 未登录时 code=-101，但仍返回 data.wbi_img；此处只要求拿到密钥
            wbi_img = (payload.get("data") or {}).get("wbi_img") or {}
            img_url = wbi_img.get("img_url") or ""
            sub_url = wbi_img.get("sub_url") or ""

            if not img_url or not sub_url:
                raise SignError("WBI 密钥响应中缺少 img_url 或 sub_url")

            self._img_key = _derive_key_from_url(img_url)
            self._sub_key = _derive_key_from_url(sub_url)
            if not self._img_key or not self._sub_key:
                raise SignError("WBI 密钥响应中的 img_url/sub_url 无法解析出密钥")

            # 混合密钥: 按 MIXIN_KEY_ENC_TAB 置换后取前 32 位
            raw = self._img_key + self._sub_key
            self._mix_key = "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]
            self._key_updated_at = time.time()

        except httpx.HTTPError as e:
            raise SignError(f"WBI 密钥获取网络失败: {e}") from e
        finally:
            if close_client:
                await http_client.aclose()

    def _ensure_keys(self) -> None:
        """确保密钥已加载，未加载时抛异常。

        异常:
            SignError: 密钥未加载，需先调用 refresh_keys()。
        """
        if self._keys_expired:
            raise SignError("WBI 密钥未加载或已过期，请先调用 refresh_keys()")

    # === 签名 ===

    def sign(self, params: dict | None = None) -> dict:
        """为参数字典追加 WBI 签名参数（w_rid + wts）。

        参数:
            params: 原始请求参数字典；为 None 时视为空字典。

        返回:
            含原始参数 + w_rid + wts 的新字典。

        异常:
            SignError: 密钥未加载。
        """
        self._ensure_keys()

        params = dict(params or {})
        # 1. 添加时间戳
        wts = int(time.time())
        params["wts"] = wts

        # 2. 过滤 w_rid/wts 之外的参数值中的特殊字符 !'()*（官方算法）
        #    同时把过滤后的值写回返回结果，保证请求参数与签名内容完全一致
        query: dict[str, str] = {}
        for k, v in params.items():
            if k in ("w_rid", "wts"):
                continue
            filtered = "".join(ch for ch in str(v) if ch not in _WBI_FILTER_CHARS)
            query[k] = filtered
            params[k] = filtered

        # 3. 按 key 升序排序 + urlencode
        enc = urlencode(sorted(query.items()))

        # 4. 计算 w_rid = MD5(query_string + &wts= + mix_key)
        sign_str = enc + f"&wts={wts}" + self._mix_key
        w_rid = hashlib.md5(sign_str.encode("utf-8")).hexdigest()

        params["w_rid"] = w_rid
        return params

    # === buvid3 生成 ===

    @staticmethod
    def generate_buvid3() -> str:
        """生成 buvid3 指纹字符串。

        B 站 buvid3 格式为:
            XY{timestamp}-{random_hex}-{app_id}-{device_id}infoc

        其中:
            - X: 随机大写字母
            - Y: 随机大写字母
            - timestamp: 当前本地时间 YYYYMMDDHHMMSS（B 站按本地时间语义校验）
            - random_hex: 6 位随机十六进制
            - app_id: 固定值 (1)
            - device_id: UUID 的简短形式

        返回:
            buvid3 字符串（如 "XX20260825120000-ab12cd-1-uuidinfoc"）。
        """
        # 审计 S7：随机字母/hex 用 secrets（加密安全随机）替代 random，
        # 降低同批次 buvid3 可聚类性（风控关联；非安全必须项）。
        prefix = secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") + secrets.choice(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        )
        now = datetime.now()
        timestamp = now.strftime("%Y%m%d%H%M%S")
        rand_hex = format(secrets.randbelow(0xFFFFFF), "06x")
        device_id = uuid.uuid4().hex[:8]
        return f"{prefix}{timestamp}-{rand_hex}-1-{device_id}infoc"

    @staticmethod
    def generate_buvid4() -> str:
        """生成 buvid4 字符串（新版本指纹）。

        返回:
            buvid4 字符串。
        """
        return uuid.uuid4().hex.upper()

    @staticmethod
    def generate_buvid_fp() -> str:
        """生成 _uuid / buvid_fp 字符串。

        返回:
            UUID 格式字符串。
        """
        return str(uuid.uuid4()).upper()
