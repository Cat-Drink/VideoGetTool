"""B 站视频解析器模块。

分两步调用 B 站 API：
    1. VIEW: /x/web-interface/view → 获取视频基本信息、分 P 列表
    2. PLAYURL: /x/player/wbi/playurl → 获取 DASH 音视频流地址

接口依赖:
    - VIEW 接口无需签名（public API）
    - PLAYURL 接口需要 WBI 签名（由 BiliSigner 处理）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.logger import get_logger
from crawlers.bilibili.bili_http_client import BiliHttpClient
from crawlers.bilibili.bili_signer import BiliSigner
from crawlers.bilibili.constants import DEFAULT_QUALITY, PLAYURL_URL, VIEW_URL
from crawlers.exceptions import VideoNotFoundError

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


def _normalize_cover_url(url: str) -> str:
    """归一化封面图片地址为 HTTPS。

    B 站 view 接口返回的 pic 字段常为 http:// 地址；在 Tauri 打包后的
    WebView 中 http 子资源会被当作混合内容拦截，导致封面不显示。
    https 变体经实测可用（同一资源，字节一致），因此统一替换为 https。
    """
    if url and url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


# === 数据结构 ===


@dataclass(frozen=True)
class BiliPage:
    """B 站视频分 P 信息。

    一个视频（BVxxx）可能包含多个分 P（P1, P2, ...），
    每个分 P 有独立的 cid 和时长。
    """

    cid: int
    page: int
    title: str
    duration: int  # 秒


@dataclass(frozen=True)
class BiliVideoInfo:
    """B 站视频基本信息（不含播放流地址）。

    由 VIEW 接口返回，包含标题、作者、分 P 列表、统计等。
    """

    bvid: str
    aid: int
    title: str
    author: str
    author_mid: int
    cover_url: str
    duration: int  # 秒（所有分P总时长或单P时长）
    description: str
    tags: list[str]
    pages: list[BiliPage]
    # 统计
    view_count: int
    danmaku_count: int
    reply_count: int
    favorite_count: int
    coin_count: int
    share_count: int
    # 发布时间（Unix 秒）
    pubdate: int
    # 原始 JSON（持久化用）
    raw_json: dict = field(default_factory=dict)


@dataclass(frozen=True)
class BiliStream:
    """B 站视频流单元（DASH 中的一条音视频流）。

    属性:
        id: 流 ID（如 30280=高清视频, 30216=音频）。
        url: 流 URL。
        base_url: 备用 URL。
        bandwidth: 带宽（bps）。
        mime_type: MIME 类型（如 "video/mp4"、"audio/mp4"）。
        codecs: 编码（如 "avc1.640028"、"mp4a.40.2"）。
        width: 视频宽度（视频流，音频流为 0）。
        height: 视频高度（视频流，音频流为 0）。
    """

    id: int
    url: str
    base_url: str | None = None
    bandwidth: int = 0
    mime_type: str = ""
    codecs: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class BiliPlayUrl:
    """B 站视频播放流地址。

    高质量视频（720P+）通常为 DASH 格式，音视频流分离；
    低质量视频可能为单一 MP4 文件。

    DASH 格式时:
        - video_streams: 多个视频流（不同清晰度）
        - audio_streams: 多个音频流（不同编码/语言）
        - dash: True

    非 DASH 格式时:
        - url: 单一 MP4 直链
        - dash: False
    """

    bvid: str
    cid: int
    quality: int  # 实际清晰度（120/112/80/64/32/16）
    quality_name: str  # "4K" / "1080P+" / "1080P" / ...
    dash: bool = True
    # DASH 格式
    video_streams: list[BiliStream] = field(default_factory=list)
    audio_streams: list[BiliStream] = field(default_factory=list)
    # 非 DASH 格式（单一 MP4）
    url: str = ""
    # 视频时长（秒）
    duration: int = 0
    # 文件大小（字节，近似值）
    file_size: int = 0


# === 视频解析器 ===


class BiliVideoParser:
    """B 站视频解析器。

    通过 BiliHttpClient 调用 VIEW 和 PLAYURL 接口，提取视频信息与播放流。

    使用方式:
        parser = BiliVideoParser(http_client, signer)
        info = await parser.parse_video("BV1GJ411x7h")
        playurl = await parser.parse_playurl("BV1GJ411x7h", cid=123456)
    """

    def __init__(self, http_client: BiliHttpClient, signer: BiliSigner) -> None:
        """初始化视频解析器。

        参数:
            http_client: BiliHttpClient 实例。
            signer: BiliSigner 实例（用于 WBI 签名）。
        """
        self._http_client = http_client
        self._signer = signer

    # === 视频基本信息 ===

    async def parse_video(
        self,
        bvid: str | None = None,
        aid: int | None = None,
        cookie: str | None = None,
    ) -> BiliVideoInfo:
        """调用 VIEW 接口获取视频基本信息。

        参数:
            bvid: B 站视频 BV 号（与 aid 二选一）。
            aid: 视频 av 号（与 bvid 二选一）。
            cookie: 本次请求使用的 B 站 Cookie（可选），仅当前请求生效。

        返回:
            BiliVideoInfo 实例。

        异常:
            VideoNotFoundError: 视频不存在或已删除。
            BiliAPIError: 接口返回业务错误。
            NetworkError: 网络异常。
        """
        params = {}
        if bvid:
            params["bvid"] = bvid
        elif aid is not None:
            params["aid"] = aid
        else:
            raise ValueError("bvid 和 aid 必须至少提供一个")

        # VIEW 接口不需要 WBI 签名
        data = await self._http_client.get_json(VIEW_URL, params, signed=False, cookie=cookie)

        if not data:
            raise VideoNotFoundError(f"B 站视频不存在: bvid={bvid}, aid={aid}")

        return self._parse_view_response(data, bvid or "", aid or 0)

    @staticmethod
    def _parse_view_response(data: dict, bvid: str, aid: int) -> BiliVideoInfo:
        """解析 VIEW 接口响应为 BiliVideoInfo。"""
        # 视频基本信息
        bvid = data.get("bvid") or bvid or ""
        aid = data.get("aid") or aid or 0
        title = data.get("title") or ""
        desc = data.get("desc") or ""
        cover_url = _normalize_cover_url(data.get("pic") or "")
        duration = data.get("duration") or 0  # 秒

        # 作者信息
        owner = data.get("owner") or {}
        author = owner.get("name") or ""
        author_mid = owner.get("mid") or 0

        # 统计
        stat = data.get("stat") or {}
        view_count = stat.get("view") or 0
        danmaku_count = stat.get("danmaku") or 0
        reply_count = stat.get("reply") or 0
        favorite_count = stat.get("favorite") or 0
        coin_count = stat.get("coin") or 0
        share_count = stat.get("share") or 0

        # 发布时间
        pubdate = data.get("pubdate") or 0

        # 标签（从 tname 或 tid 获取）
        tags = []
        tname = data.get("tname") or ""
        if tname:
            tags.append(tname)

        # 分 P 列表
        pages_raw = data.get("pages") or []
        pages: list[BiliPage] = []
        for p in pages_raw:
            if not isinstance(p, dict):
                continue
            pages.append(
                BiliPage(
                    cid=int(p.get("cid", 0)),
                    page=int(p.get("page", 1)),
                    title=p.get("part", "") or "",
                    duration=int(p.get("duration", 0)),
                )
            )

        return BiliVideoInfo(
            bvid=bvid,
            aid=aid,
            title=title,
            author=author,
            author_mid=author_mid,
            cover_url=cover_url,
            duration=duration,
            description=desc,
            tags=tags,
            pages=pages,
            view_count=view_count,
            danmaku_count=danmaku_count,
            reply_count=reply_count,
            favorite_count=favorite_count,
            coin_count=coin_count,
            share_count=share_count,
            pubdate=pubdate,
            raw_json=data,
        )

    # === 播放流地址 ===

    async def parse_playurl(
        self,
        bvid: str,
        cid: int,
        quality: int = DEFAULT_QUALITY,
        cookie: str | None = None,
    ) -> BiliPlayUrl:
        """调用 PLAYURL 接口获取视频播放流地址。

        需要 WBI 签名。高质量视频返回 DASH 格式（音视频分离），
        低质量视频可能返回单一 MP4 直链。

        参数:
            bvid: B 站视频 BV 号。
            cid: 分 P 的 cid（通过 VIEW 接口获取）。
            quality: 请求的清晰度，默认 80（1080P）。
            cookie: 本次请求使用的 B 站 Cookie（可选），仅当前请求生效。

        返回:
            BiliPlayUrl 实例。

        异常:
            BiliAPIError: 接口返回业务错误（如 -412 风控、-404 不存在）。
            NetworkError: 网络异常。
        """
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": quality,
            # 请求 DASH 格式 (1=MP4, 2=FLV, 16=DASH, 256=HDR, 512=4K, 2048=杜比视界, 4048=综合)
            "fnval": 4048,
            "fnver": 0,
            "fourk": 1,  # 允许 4K
        }

        data = await self._http_client.get_json(PLAYURL_URL, params, signed=True, cookie=cookie)

        if not data:
            raise VideoNotFoundError(f"B 站播放流获取失败: bvid={bvid}, cid={cid}")

        return self._parse_playurl_response(data, bvid, cid, quality)

    @staticmethod
    def _parse_playurl_response(data: dict, bvid: str, cid: int, quality: int) -> BiliPlayUrl:
        """解析 PLAYURL 接口响应为 BiliPlayUrl。"""
        # 实际返回的清晰度
        actual_quality = data.get("quality") or quality
        # 清晰度名称
        quality_name = data.get("quality_name") or ""
        # 时长
        duration = data.get("timelength") or 0
        duration_sec = duration // 1000

        # DASH 格式
        dash_data = data.get("dash") or {}
        video_streams: list[BiliStream] = []
        audio_streams: list[BiliStream] = []

        if dash_data:
            # 视频流
            for v in dash_data.get("video") or []:
                if not isinstance(v, dict):
                    continue
                video_streams.append(
                    BiliStream(
                        id=v.get("id", 0),
                        url=v.get("base_url") or v.get("backup_url", [""])[0] or "",
                        base_url=(
                            (v.get("backup_url") or [None])[0] if v.get("backup_url") else None
                        ),
                        bandwidth=v.get("bandwidth", 0),
                        mime_type=v.get("mime_type", ""),
                        codecs=v.get("codecs", ""),
                        width=v.get("width", 0),
                        height=v.get("height", 0),
                    )
                )
            # 音频流
            for a in dash_data.get("audio") or []:
                if not isinstance(a, dict):
                    continue
                audio_streams.append(
                    BiliStream(
                        id=a.get("id", 0),
                        url=a.get("base_url") or a.get("backup_url", [""])[0] or "",
                        base_url=(
                            (a.get("backup_url") or [None])[0] if a.get("backup_url") else None
                        ),
                        bandwidth=a.get("bandwidth", 0),
                        mime_type=a.get("mime_type", ""),
                        codecs=a.get("codecs", ""),
                        width=0,
                        height=0,
                    )
                )
        # 非 DASH：单一 MP4 直链
        single_url = ""
        durl = data.get("durl") or []
        if durl and isinstance(durl, list) and len(durl) > 0:
            single_url = durl[0].get("url") or ""

        return BiliPlayUrl(
            bvid=bvid,
            cid=cid,
            quality=actual_quality,
            quality_name=quality_name,
            dash=bool(dash_data),
            video_streams=video_streams,
            audio_streams=audio_streams,
            url=single_url,
            duration=duration_sec,
            file_size=0,
        )
