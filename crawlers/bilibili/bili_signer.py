"""B 站 WBI 签名器 + buvid3 指纹生成器。

WBI 签名是 B 站用于 API 鉴权的签名机制，替代旧版签名。算法：
    1. 从 /x/web-interface/wbi/index 获取 img_key 和 sub_key
    2. 混合密钥: mix_key = sub_key[:4] + img_key[:4]
    3. 参数按 key 升序排列，拼接为 query string
    4. w_rid = MD5(query_string + mix_key)
    5. wts = 当前 Unix 时间戳

buvid3 是 B 站客户端指纹，用于标识设备，需通过 Cookie 或请求头发送。

参考方向:
    - SocialSisterYi/bilibili-API-collect（已归档）的 WBI 签名文档
    - 各开源 B 站下载器的公开实现
"""

from __future__ import annotations

import hashlib
import random
import string
import time
import uuid
from datetime import datetime, timezone

import httpx

from crawlers.bilibili.constants import (
    DEFAULT_HEADERS,
    DEFAULT_USER_AGENT,
    WBI_INDEX_URL,
    WBI_KEY_CACHE_TTL,
)
from crawlers.exceptions import SignError


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
        """从 /x/web-interface/wbi/index 刷新 WBI 密钥。

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
            resp = await http_client.get(WBI_INDEX_URL)
            resp.raise_for_status()
            data = resp.json()

            if data.get("code") != 0:
                raise SignError(f"WBI 密钥获取失败: {data.get('message', '未知错误')}")

            wbi_img = data.get("data", {}).get("wbi_img", {})
            self._img_key = wbi_img.get("img_key", "")
            self._sub_key = wbi_img.get("sub_key", "")

            if not self._img_key or not self._sub_key:
                raise SignError("WBI 密钥响应中缺少 img_key 或 sub_key")

            # 混合密钥: sub_key[:4] + img_key[:4]
            self._mix_key = self._sub_key[:4] + self._img_key[:4]
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

        # 2. 按 key 升序排列
        sorted_params = sorted(params.items(), key=lambda x: x[0])

        # 3. 拼接为 query string（不编码，保持原始值）
        query_string = "&".join(f"{k}={v}" for k, v in sorted_params)

        # 4. 计算 w_rid = MD5(query_string + mix_key)
        sign_str = query_string + self._mix_key
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
            - timestamp: 当前时间 YYYYMMDDHHMMSS
            - random_hex: 6 位随机十六进制
            - app_id: 固定值 (1)
            - device_id: UUID 的简短形式

        返回:
            buvid3 字符串（如 "XX20260825120000-ab12cd-1-uuidinfoc"）。
        """
        prefix = random.choice(string.ascii_uppercase) + random.choice(string.ascii_uppercase)
        now = datetime.now(timezone.utc)
        timestamp = now.strftime("%Y%m%d%H%M%S")
        rand_hex = format(random.randint(0, 0xFFFFFF), "06x")
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
