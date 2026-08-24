"""抖音 Web API 调用规范常量集中定义。

本模块仅定义常量与字段路径映射，不含任何业务逻辑。当抖音 API 变更
（URL 调整、参数增减、字段路径变化）时，只需修改本模块，不影响
VideoParser / UserHomeCrawler / CookieTester 的业务代码。

对应设计文档 ``docs/structure/05-接口设计文档.md`` 第 3.3、3.4、3.5、7 节
与里程碑计划 ``docs/plans/v0.0.4-视频解析与主页抓取.md`` 第 6 节。

常量分组:
    - 接口 URL 常量（6.2.1）
    - 固定请求参数常量（6.2.2）
    - 请求头常量（6.2.3）
    - 响应字段路径常量（6.2.4，detail / post 两组）
    - 验证 HTML 特征常量（6.2.5）
"""

from __future__ import annotations

# === 6.2.1 接口 URL 常量 ===

# 视频详情接口（VideoParser 使用）
AWEME_DETAIL_URL: str = "https://www.douyin.com/aweme/v1/web/aweme/detail/"

# 主页作品列表接口（UserHomeCrawler 使用）
AWEME_POST_URL: str = "https://www.douyin.com/aweme/v1/web/aweme/post/"

# Cookie 测试推荐接口（CookieTester 主路径）
GENERAL_SEARCH_URL: str = "https://www.douyin.com/aweme/v1/web/general/search/single/"

# Cookie 测试备选接口（获取当前登录用户信息，风控更严）
USER_PROFILE_SELF_URL: str = "https://www.douyin.com/aweme/v1/web/user/profile/self/"


# === 6.2.2 固定请求参数常量 ===

# 所有抖音 Web API 接口共用的固定参数
COMMON_FIXED_PARAMS: dict[str, str] = {
    "aid": "6383",
    "device_platform": "webapp",
    "channel": "channel_pc_web",
    "version_code": "170400",
}

# post 接口每页拉取数量
POST_PAGE_SIZE: int = 20

# Cookie 测试 search 接口的固定分页参数
COOKIE_TEST_SEARCH_KEYWORD: str = "test"
COOKIE_TEST_SEARCH_COUNT: int = 10
COOKIE_TEST_SEARCH_OFFSET: int = 0


# === 6.2.3 请求头常量 ===

# 默认 User-Agent（与 crawlers.signer.DEFAULT_USER_AGENT 保持一致，
# 避免签名 UA 与请求 UA 不匹配导致签名失效）
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

# 默认 Referer
DEFAULT_REFERER: str = "https://www.douyin.com/"

# 默认 Accept
DEFAULT_ACCEPT: str = "application/json, text/plain, */*"


# === 6.2.4 响应字段路径常量 ===

# 注意：FIELD_DETAIL_* 和 FIELD_POST_* 系列常量曾作为字段路径映射定义，
# 但实际提取逻辑已直接硬编码在 video_parser.py 和 user_home_crawler.py 中，
# 这些常量零引用。如需统一字段路径管理，请恢复本段并替换各模块的硬编码路径。


# === 6.2.5 验证 HTML 特征常量 ===

# 滑动验证 HTML 特征字符串元组。
# HttpClient 内部已用同名的 VERIFY_HTML_MARKERS 做拦截（http_client.py:50），
# 本模块的版本是遗留副本，不再使用。如需统一，请同步两处。
