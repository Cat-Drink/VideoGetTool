"""爬虫层异常类层次结构。

本模块定义项目所有自定义异常的根（VideoGetToolError）、爬虫层异常基类
（CrawlerError）以及签名相关异常（SignError）。同时预定义 Cookie 失效、
限流、作品不存在、网络异常等爬虫层通用异常，供后续里程碑直接使用。

完整异常层次图（含后续里程碑将补充的异常）：

    Exception
    └── VideoGetToolError                    # 项目所有自定义异常的根
        ├── CrawlerError                      # 爬虫层异常基类
        │   ├── InvalidURLFormatError         # 链接格式无法识别
        │   ├── CookieInvalidError            # Cookie 失效或被风控
        │   ├── RateLimitedError              # 触发限流（HTTP 429）
        │   ├── VideoNotFoundError            # 作品已删除/私密
        │   ├── UserNotFoundError             # 用户主页不存在
        │   ├── VerifyRequiredError           # 触发滑块验证
        │   ├── NetworkError                  # 网络异常（连接超时/DNS 失败）
        │   └── SignError                     # 签名生成失败
        └── DownloaderError                   # 下载引擎异常基类（v0.0.6 补充）
            ├── DownloadFailedError           # 下载失败（重试耗尽）
            ├── DiskFullError                 # 磁盘空间不足
            └── FileIOError                   # 文件读写错误

各异常的触发场景、用户提示、上层行为见模块内各异常类的文档字符串。
"""

from __future__ import annotations


class VideoGetToolError(Exception):
    """项目所有自定义异常的根基类。

    所有自定义异常均继承自此，便于上层 ``except VideoGetToolError`` 统一兜底。
    本类不直接抛出，触发场景为未知错误时由顶层 ``except`` 捕获并提示
    "发生未知错误"。
    """

    pass


class CrawlerError(VideoGetToolError):
    """爬虫层异常基类。

    本类不直接抛出，上层按子类分别处理。
    """

    pass


class InvalidURLFormatError(CrawlerError):
    """链接格式无法识别。

    触发场景:
        - URLParser.extract_url 未在文本中找到抖音链接
        - URLParser.identify_type 无法从 URL 路径/参数识别类型

    用户提示:
        "无法识别该链接，请确认是抖音视频/主页链接"

    上层行为:
        标记解析失败，输入框下方红字提示。
    """

    pass


class CookieInvalidError(CrawlerError):
    """Cookie 失效或被风控。

    触发场景:
        - HTTP 461/412 响应
        - Cookie 池无可用 Cookie
        - "测试 Cookie" 返回非 0 status_code

    用户提示:
        "Cookie 已失效，抖音需要重新登录验证"

    上层行为:
        跳转 Cookie 配置页。
    """

    pass


class RateLimitedError(CrawlerError):
    """触发抖音限流。

    触发场景:
        - HTTP 429 响应
        - 风控限流响应

    用户提示:
        "请求过于频繁，请稍后重试"

    上层行为:
        该项标记失败，原因提示等待。
    """

    pass


class VideoNotFoundError(CrawlerError):
    """作品已删除/设为私密。

    触发场景:
        aweme/detail 返回 status_code 非 0 且错误码表明作品不存在。

    用户提示:
        "该作品已被删除或设为私密，无法下载"

    上层行为:
        跳过该项。
    """

    pass


class UserNotFoundError(CrawlerError):
    """用户主页不存在或不可见。

    触发场景:
        主页抓取时返回用户不存在。

    用户提示:
        "该用户主页不存在或不可见"

    上层行为:
        跳过该项。
    """

    pass


class VerifyRequiredError(CrawlerError):
    """触发抖音滑块/安全验证。

    触发场景:
        响应 HTML 含滑动验证特征（如 ``captcha_verify``）。

    用户提示:
        "抖音要求安全验证，暂时无法下载此作品"

    上层行为:
        该项标记失败。本应用不实现自动验证绕过。
    """

    pass


class NetworkError(CrawlerError):
    """网络异常。

    触发场景:
        httpx.ConnectTimeout / httpx.ConnectError / httpx.ReadTimeout 等。

    用户提示:
        "网络连接失败，请检查网络后重试"

    上层行为:
        交给下载引擎重试逻辑。
    """

    pass


class SignError(CrawlerError):
    """签名生成失败。

    触发场景:
        签名算法内部异常（参数缺失、计算失败、算法不支持的输入等）。

    用户提示:
        "请求签名生成失败"

    上层行为:
        标记失败，记录详情供开发者排查。

    属性:
        algorithm: 失败的具体签名算法标识，如 ``'xbogus'`` / ``'abogus'`` /
            ``'mstoken'`` / ``'verify_fp'``。None 表示未标识具体算法。
    """

    def __init__(self, message: str, algorithm: str | None = None) -> None:
        """初始化签名异常。

        参数:
            message: 异常描述信息。
            algorithm: 失败的签名算法标识，便于日志定位。
        """
        super().__init__(message)
        self.algorithm = algorithm
