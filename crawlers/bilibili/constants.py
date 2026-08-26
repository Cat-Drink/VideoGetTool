"""B 站 API 常量与调用规范。

集中定义 B 站所有 API 端点、固定参数、请求头常量。
当 B 站 API 变更时只需修改本模块，不影响业务代码。
"""

from __future__ import annotations

# === API 接口域名 ===

API_BASE_URL: str = "https://api.bilibili.com"
WWW_BASE_URL: str = "https://www.bilibili.com"


# === 视频信息接口 ===

# 视频基本信息（无需签名）
# GET ?bvid=xxx 或 ?aid=xxx
# 返回: 标题、作者、分P列表、统计等
VIEW_URL: str = f"{API_BASE_URL}/x/web-interface/view"

# 视频播放流地址（需 WBI 签名）
# GET ?bvid=xxx&cid=xxx&qn=80 (qn=清晰度 80=1080P, 64=720P, 32=480P, 16=360P)
# 返回: DASH 音视频流 URL 列表
PLAYURL_URL: str = f"{API_BASE_URL}/x/player/wbi/playurl"

# 播放流 V2（新版，需 WBI 签名）
PLAYURL_V2_URL: str = f"{API_BASE_URL}/x/player/wbi/playurl/v2"


# === 用户空间接口 ===

# 用户投稿列表（需 WBI 签名）
# GET ?mid=xxx&ps=30&pn=1 (ps=每页数量, pn=页码)
# 返回: 视频列表 + 分页信息
SPACE_ARC_SEARCH_URL: str = f"{API_BASE_URL}/x/space/wbi/arc/search"

# 用户基本信息
# GET ?mid=xxx
SPACE_INFO_URL: str = f"{API_BASE_URL}/x/space/wbi/acc/info"


# === 认证与签名接口 ===

# WBI 密钥获取（无需签名）
# 返回: {data: {wbi_img: {img_url, sub_url}}}
# 注意：密钥取自 img_url/sub_url 的文件 basename，而非 img_key/sub_key 字段
WBI_INDEX_URL: str = f"{API_BASE_URL}/x/web-interface/wbi/index"

# 登录状态检测（Cookie 测试用）
# 返回: {data: {isLogin, uname, wbi_img: {img_url, sub_url}}}
# 未登录（code=-101）时仍返回 data.wbi_img，可同时作为 WBI 密钥来源
NAV_URL: str = f"{API_BASE_URL}/x/web-interface/nav"


# === 请求头常量 ===

DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_REFERER: str = "https://www.bilibili.com/"

DEFAULT_ACCEPT: str = "application/json, text/plain, */*"

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": DEFAULT_USER_AGENT,
    "Referer": DEFAULT_REFERER,
    "Accept": DEFAULT_ACCEPT,
    "Accept-Language": "zh-CN,zh;q=0.9",
}


# === 清晰度定义 ===

# B 站视频清晰度 qn 参数
QUALITY_MAP: dict[str, int] = {
    "4K": 120,
    "1080P+": 112,       # 大会员
    "1080P": 80,
    "720P": 64,
    "480P": 32,
    "360P": 16,
}

DEFAULT_QUALITY: int = 80  # 1080P


# === 其他常量 ===

# 用户投稿每页数量
SPACE_PAGE_SIZE: int = 30

# 请求超时（秒）
REQUEST_TIMEOUT_CONNECT: float = 10.0
REQUEST_TIMEOUT_READ: float = 30.0

# WBI 密钥缓存有效期（秒）
WBI_KEY_CACHE_TTL: int = 86400  # 24 小时
