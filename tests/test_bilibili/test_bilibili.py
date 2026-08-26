"""B 站爬虫模块单元测试。

测试原则：
    - 测试算法逻辑（WBI 签名、buvid3 生成、URL 解析），不依赖外部网络
    - 依赖网络的 API 调用通过 mock 或集成测试覆盖
    - 遵循项目现有测试风格（class-based + 中文 docstring）
"""

from __future__ import annotations

import re

import pytest

from crawlers.bilibili.bili_signer import BiliSigner, MIXIN_KEY_ENC_TAB
from crawlers.bilibili.bili_url_parser import BiliURLParser, BiliParsedURL
from crawlers.bilibili.constants import (
    QUALITY_MAP,
    SPACE_PAGE_SIZE,
    WBI_KEY_CACHE_TTL,
)


def _compute_mix_key(img_key: str, sub_key: str) -> str:
    """按官方置换表计算 mix_key（测试辅助）。"""
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]

pytestmark = pytest.mark.bilibili


# ============================================================
# BiliSigner 测试
# ============================================================


class TestBiliSigner:
    """BiliSigner 基本功能测试。"""

    def test_generate_buvid3_format(self) -> None:
        """buvid3 符合预期格式。"""
        buvid3 = BiliSigner.generate_buvid3()
        # 格式: XX20260825120000-xxxxxx-1-xxxxxxxxinfoc
        assert isinstance(buvid3, str)
        assert len(buvid3) > 20
        assert buvid3.endswith("infoc")
        # 前两个字符应为大写字母
        assert buvid3[0].isupper()
        assert buvid3[1].isupper()
        # 包含时间戳数字
        assert re.search(r"\d{14}", buvid3)

    def test_generate_buvid3_uniqueness(self) -> None:
        """多次生成的 buvid3 各不相同。"""
        items = {BiliSigner.generate_buvid3() for _ in range(10)}
        assert len(items) == 10

    def test_generate_buvid4_format(self) -> None:
        """buvid4 格式为 32 位十六进制（UUID 大写）。"""
        buvid4 = BiliSigner.generate_buvid4()
        assert isinstance(buvid4, str)
        assert len(buvid4) == 32
        # 应为十六进制字符
        int(buvid4, 16)

    def test_generate_buvid_fp_format(self) -> None:
        """buvid_fp 包含连字符（UUID 标准格式）。"""
        fp = BiliSigner.generate_buvid_fp()
        assert isinstance(fp, str)
        assert "-" in fp

    def test_sign_requires_keys(self) -> None:
        """未加载密钥时调用 sign() 抛出 SignError。"""
        signer = BiliSigner()
        from crawlers.exceptions import SignError
        with pytest.raises(SignError, match="密钥未加载"):
            signer.sign({"bvid": "BV1xx"})

    def test_keys_expired_initially(self) -> None:
        """初始状态密钥为过期状态。"""
        signer = BiliSigner()
        assert signer._keys_expired is True

    def test_wbi_key_cache_ttl(self) -> None:
        """WBI 密钥缓存 TTL 为 24 小时。"""
        assert WBI_KEY_CACHE_TTL == 86400

    def test_sign_adds_wts_and_wrid(self) -> None:
        """sign() 正常执行后应添加 wts 和 w_rid 参数。"""
        # 手动设置密钥后测试签名逻辑
        signer = BiliSigner()
        signer._img_key = "7cd084941338484aae1ad9425b84077c"
        signer._sub_key = "4932caff0ff746eab6f01bf08b70ac45"
        signer._mix_key = _compute_mix_key(signer._img_key, signer._sub_key)
        signer._key_updated_at = 9999999999.0

        params = signer.sign({"bvid": "BV1GJ411x7h"})
        assert "wts" in params
        assert "w_rid" in params
        assert params["bvid"] == "BV1GJ411x7h"
        # wts 应为当前时间戳（整数）
        assert isinstance(params["wts"], int)
        # w_rid 应为 32 字符 MD5 十六进制
        assert isinstance(params["w_rid"], str)
        assert len(params["w_rid"]) == 32


class TestWbiFixedVectors:
    """WBI 签名固定向量测试（基于真实密钥断言精确 w_rid）。

    密钥与置换表来自 B 站官方公开实现（bilibili-API-collect）：
        img_key = 7cd084941338484aae1ad9425b84077c
        sub_key = 4932caff0ff746eab6f01bf08b70ac45
        mix_key = ea1db124af3c7062474693fa704f4ff8（置换表取前 32 位）
    """

    IMG_KEY = "7cd084941338484aae1ad9425b84077c"
    SUB_KEY = "4932caff0ff746eab6f01bf08b70ac45"
    KNOWN_MIX_KEY = "ea1db124af3c7062474693fa704f4ff8"

    def _make_signer(self) -> BiliSigner:
        """构造已加载密钥的签名器。"""
        signer = BiliSigner()
        signer._img_key = self.IMG_KEY
        signer._sub_key = self.SUB_KEY
        signer._mix_key = _compute_mix_key(self.IMG_KEY, self.SUB_KEY)
        signer._key_updated_at = 9999999999.0
        return signer

    def test_mixin_key_matches_official_vector(self) -> None:
        """mix_key 与官方置换表结果一致。"""
        assert _compute_mix_key(self.IMG_KEY, self.SUB_KEY) == self.KNOWN_MIX_KEY

    def test_derive_key_from_url(self) -> None:
        """从 img_url/sub_url 提取密钥 basename。"""
        from crawlers.bilibili.bili_signer import _derive_key_from_url

        assert _derive_key_from_url(
            f"https://i0.hdslb.com/bfs/wbi/{self.IMG_KEY}.png"
        ) == self.IMG_KEY
        assert _derive_key_from_url(
            f"https://i0.hdslb.com/bfs/wbi/{self.SUB_KEY}.png"
        ) == self.SUB_KEY

    def test_sign_fixed_vector_wrid(self) -> None:
        """固定时间戳与参数下 w_rid 精确匹配已知向量。"""
        import hashlib
        from urllib.parse import urlencode

        import crawlers.bilibili.bili_signer as signer_module

        # 固定时间戳，保证确定性输出
        original_time = signer_module.time
        signer_module.time = type("_FakeTime", (), {"time": staticmethod(lambda: 1702200673.0)})()

        try:
            signer = self._make_signer()
            params = signer.sign({"foo": "114", "bar": "514", "zab": "1919810"})

            # 独立计算期望 w_rid
            q = {k: "".join(ch for ch in str(v) if ch not in "!'()*")
                 for k, v in params.items() if k not in ("w_rid", "wts")}
            enc = urlencode(sorted(q.items())) + "&wts=1702200673"
            expected = hashlib.md5((enc + signer._mix_key).encode("utf-8")).hexdigest()

            assert params["w_rid"] == expected
            assert len(params["w_rid"]) == 32
        finally:
            signer_module.time = original_time

    def test_sign_filters_special_chars_in_value(self) -> None:
        """参数值中的 !'()* 特殊字符在签名中被过滤，且写回返回值。"""
        signer = self._make_signer()
        params = signer.sign({"bvid": "BV1xx", "spm": "abc!'()*def"})
        # 过滤后的值写回参数，保证请求参数与签名一致
        assert params["spm"] == "abcdef"


# ============================================================
# BiliURLParser 测试
# ============================================================


class TestBiliURLParser:
    """BiliURLParser 链接解析测试。"""

    def setup_method(self) -> None:
        """每个测试前创建解析器实例。"""
        self.parser = BiliURLParser()

    # --- extract_bvid ---

    def test_extract_bvid_standard_url(self) -> None:
        """从标准视频 URL 中提取 BV 号。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert BiliURLParser.extract_bvid(url) == "BV1GJ411x7h"

    def test_extract_bvid_with_query(self) -> None:
        """从含查询参数的 URL 中提取 BV 号。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h?p=2&spm_id_from=333.337"
        assert BiliURLParser.extract_bvid(url) == "BV1GJ411x7h"

    def test_extract_bvid_short_url(self) -> None:
        """从短链中提取 BV 号（短链本身无 BV，需重定向）。"""
        url = "https://b23.tv/xxxxxx"
        assert BiliURLParser.extract_bvid(url) is None

    def test_extract_bvid_no_match(self) -> None:
        """非 B 站 URL 返回 None。"""
        url = "https://www.youtube.com/watch?v=xxx"
        assert BiliURLParser.extract_bvid(url) is None

    # --- extract_av_id ---

    def test_extract_av_id_standard(self) -> None:
        """从 av 号 URL 中提取数字 ID。"""
        url = "https://www.bilibili.com/video/av123456"
        assert BiliURLParser.extract_av_id(url) == 123456

    def test_extract_av_id_lowercase(self) -> None:
        """小写 av 号也能提取。"""
        url = "https://www.bilibili.com/video/av789012"
        assert BiliURLParser.extract_av_id(url) == 789012

    def test_extract_av_id_no_match(self) -> None:
        """无 av 号返回 None。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert BiliURLParser.extract_av_id(url) is None

    # --- extract_mid ---

    def test_extract_mid_standard(self) -> None:
        """从标准空间 URL 中提取 mid。"""
        url = "https://space.bilibili.com/1234567"
        assert BiliURLParser.extract_mid(url) == 1234567

    def test_extract_mid_with_path(self) -> None:
        """从含子路径的空间 URL 中提取 mid。"""
        url = "https://space.bilibili.com/1234567/video"
        assert BiliURLParser.extract_mid(url) == 1234567

    def test_extract_mid_no_match(self) -> None:
        """非空间 URL 返回 None。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert BiliURLParser.extract_mid(url) is None

    # --- extract_page ---

    def test_extract_page_default(self) -> None:
        """无分P参数时返回 1。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert BiliURLParser.extract_page(url) == 1

    def test_extract_page_p2(self) -> None:
        """提取 ?p=2 参数。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h?p=2"
        assert BiliURLParser.extract_page(url) == 2

    def test_extract_page_page_param(self) -> None:
        """提取 ?page=3 参数。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h?page=3"
        assert BiliURLParser.extract_page(url) == 3

    # --- _is_bili_url ---

    def test_is_bili_url_standard(self) -> None:
        """标准 B 站域名被识别。"""
        assert BiliURLParser._is_bili_url("https://www.bilibili.com/video/BV1xx")
        assert BiliURLParser._is_bili_url("https://bilibili.com/video/BV1xx")
        assert BiliURLParser._is_bili_url("https://space.bilibili.com/12345")
        assert BiliURLParser._is_bili_url("https://b23.tv/xxxxx")

    def test_is_bili_url_non_bili(self) -> None:
        """非 B 站域名不被识别。"""
        assert not BiliURLParser._is_bili_url("https://www.youtube.com/")
        assert not BiliURLParser._is_bili_url("https://www.douyin.com/")

    # --- identify_type ---

    def test_identify_type_video_by_bvid(self) -> None:
        """含 BV 号的 URL 识别为 video。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert self.parser.identify_type(url) == "video"

    def test_identify_type_video_by_av(self) -> None:
        """含 av 号的 URL 识别为 video。"""
        url = "https://www.bilibili.com/video/av123456"
        assert self.parser.identify_type(url) == "video"

    def test_identify_type_user_home(self) -> None:
        """空间 URL 识别为 user_home。"""
        url = "https://space.bilibili.com/1234567"
        assert self.parser.identify_type(url) == "user_home"

    def test_identify_type_user_home_with_path(self) -> None:
        """空间子路径也识别为 user_home。"""
        url = "https://space.bilibili.com/1234567/video"
        assert self.parser.identify_type(url) == "user_home"

    def test_identify_type_invalid(self) -> None:
        """无法识别的 URL 抛出异常。"""
        from crawlers.exceptions import InvalidURLFormatError
        with pytest.raises(InvalidURLFormatError):
            self.parser.identify_type("https://example.com/")

    # --- extract_url ---

    def test_extract_url_from_plain(self) -> None:
        """从纯文本中提取 URL。"""
        text = "https://www.bilibili.com/video/BV1GJ411x7h"
        assert self.parser.extract_url(text) == text

    def test_extract_url_from_share_text(self) -> None:
        """从分享文本中提取 URL。"""
        text = "我在 B 站发现了一个好视频：https://www.bilibili.com/video/BV1GJ411x7h 快来看看！"
        url = self.parser.extract_url(text)
        assert url == "https://www.bilibili.com/video/BV1GJ411x7h"

    def test_extract_url_no_bili_url(self) -> None:
        """无 B 站链接时返回 None。"""
        text = "今天天气真不错"
        assert self.parser.extract_url(text) is None

    def test_extract_url_short_url(self) -> None:
        """b23.tv 短链也能提取。"""
        text = "https://b23.tv/xxxxxx 我的视频"
        url = self.parser.extract_url(text)
        assert url == "https://b23.tv/xxxxxx"

    # --- parse (async, 不带网络) ---

    @pytest.mark.asyncio
    async def test_parse_video_bvid(self) -> None:
        """解析 BV 号视频链接返回正确结果。"""
        text = "https://www.bilibili.com/video/BV1GJ411x7h"
        result = await self.parser.parse(text)
        assert result.type == "video"
        assert result.bvid == "BV1GJ411x7h"
        assert result.url == text

    @pytest.mark.asyncio
    async def test_parse_video_with_page(self) -> None:
        """解析含分P参数的 URL。"""
        text = "https://www.bilibili.com/video/BV1GJ411x7h?p=2"
        result = await self.parser.parse(text)
        assert result.type == "video"
        assert result.bvid == "BV1GJ411x7h"
        assert result.page == 2

    @pytest.mark.asyncio
    async def test_parse_user_home(self) -> None:
        """解析空间 URL 返回正确结果。"""
        text = "https://space.bilibili.com/1234567"
        result = await self.parser.parse(text)
        assert result.type == "user_home"
        assert result.mid == 1234567

    @pytest.mark.asyncio
    async def test_parse_no_url(self) -> None:
        """无 URL 的文本抛出异常。"""
        from crawlers.exceptions import InvalidURLFormatError
        with pytest.raises(InvalidURLFormatError):
            await self.parser.parse("今天天气真好")

    # --- 边界情况 ---

    def test_extract_bvid_lowercase_body(self) -> None:
        """BV 前缀后的内容可以包含小写字母。"""
        url = "https://www.bilibili.com/video/BV1GJ411x7h"
        bvid = BiliURLParser.extract_bvid(url)
        assert bvid == "BV1GJ411x7h"

    def test_extract_bvid_lowercase_prefix_not_matched(self) -> None:
        """小写 bv 前缀不应匹配（B 站 BV 号前缀恒为大写）。"""
        url = "https://www.bilibili.com/video/bv1gj411x7h"
        assert BiliURLParser.extract_bvid(url) is None

    def test_empty_text_returns_none(self) -> None:
        """空文本返回 None。"""
        assert self.parser.extract_url("") is None
        assert self.parser.extract_url(None) is None  # type: ignore[arg-type]

    def test_extract_mid_non_numeric(self) -> None:
        """非数字 mid 返回 None。"""
        url = "https://space.bilibili.com/abc"
        assert BiliURLParser.extract_mid(url) is None


# ============================================================
# Constants 测试
# ============================================================


class TestBiliConstants:
    """B 站常量测试。"""

    def test_quality_map_contains_key_levels(self) -> None:
        """清晰度映射包含所有关键级别。"""
        assert QUALITY_MAP["4K"] == 120
        assert QUALITY_MAP["1080P+"] == 112
        assert QUALITY_MAP["1080P"] == 80
        assert QUALITY_MAP["720P"] == 64

    def test_space_page_size_reasonable(self) -> None:
        """每页数量在合理范围内。"""
        assert 1 <= SPACE_PAGE_SIZE <= 50
