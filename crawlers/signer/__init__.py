"""签名算法模块聚合入口。

组合 XBogusSigner / ABogusSigner / MsTokenGenerator / VerifyFpGenerator
四个子算法，对外暴露稳定的签名接口。算法失效时只需替换子模块实现，
调用方代码不变。

使用方式::

    from crawlers.signer import Signer

    signer = Signer()
    sign_params = signer.sign("https://www.douyin.com/aweme/v1/web/aweme/detail/",
                               {"aweme_id": "123", "aid": "6383"})
    # sign_params 含 X-Bogus / a_bogus / msToken / verifyFp 四个键
"""

from __future__ import annotations

import urllib.parse

from crawlers.exceptions import SignError
from crawlers.signer.abogus import ABogusSigner
from crawlers.signer.mstoken import MsTokenGenerator
from crawlers.signer.verify_fp import VerifyFpGenerator
from crawlers.signer.xbogus import XBogusSigner

# 默认 User-Agent（PC Chrome，与接口设计文档第 7.1 节"必需请求头"格式一致）
DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "Signer",
    "XBogusSigner",
    "ABogusSigner",
    "MsTokenGenerator",
    "VerifyFpGenerator",
]


class Signer:
    """签名算法模块聚合入口。

    内部组合 XBogusSigner / ABogusSigner / MsTokenGenerator / VerifyFpGenerator
    四个子算法，对外暴露稳定接口。算法失效时只需替换子模块实现。

    属性:
        DEFAULT_USER_AGENT: 模块级默认 User-Agent 常量。
    """

    # 类级常量，便于外部以 Signer.DEFAULT_USER_AGENT 方式引用
    DEFAULT_USER_AGENT: str = DEFAULT_USER_AGENT

    def __init__(self, user_agent: str | None = None) -> None:
        """初始化签名器。

        参数:
            user_agent: 默认 User-Agent 字符串。sign() 调用时若未显式传入，
                则使用此默认值。None 时使用模块内置的 PC Chrome 默认 UA。
        """
        self._user_agent = user_agent if user_agent is not None else DEFAULT_USER_AGENT
        self._xbogus_signer = XBogusSigner()
        self._abogus_signer = ABogusSigner()
        self._mstoken_generator = MsTokenGenerator()
        self._verify_fp_generator = VerifyFpGenerator()

    def sign(
        self,
        url: str,
        params: dict,
        user_agent: str | None = None,
    ) -> dict:
        """为请求生成完整的签名参数集合。

        参数:
            url: 请求 URL（不含查询参数）。
            params: 业务请求参数（query / form 数据）。
            user_agent: 本次请求的 User-Agent。None 时使用构造函数传入的默认值。

        返回:
            需要追加到请求中的签名参数字典，包含::

                {
                    'X-Bogus': str,
                    'a_bogus': str,
                    'msToken': str,
                    'verifyFp': str,
                }

            调用方将这些参数合并到原 params 后发起请求。

        异常:
            SignError: 任一子算法签名失败（含 algorithm 标识）。
        """
        try:
            # 步骤 1：确定 User-Agent
            ua = user_agent if user_agent is not None else self._user_agent
            if not ua:
                raise SignError("User-Agent 不能为空", algorithm=None)

            # 步骤 2：msToken（随机生成，需先于 X-Bogus）
            # msToken 必须参与 X-Bogus 计算，否则签名会被服务端拒绝
            ms_token = self._mstoken_generator.generate()

            # 步骤 3：verifyFp（随机生成）
            verify_fp = self._verify_fp_generator.generate()

            # 步骤 4：将 msToken 加入 params，构造用于签名的完整参数串
            # 使用 urllib.parse.urlencode 编码，与真实请求的 query string 一致
            # 注意：X-Bogus 和 a_bogus 必须基于同一编码后的字符串计算，
            # 否则当 msToken 含 base64 字符（+ / =）时签名输入不一致，
            # 即使算法正确也可能被服务端拒绝（461 间歇性原因之一）
            sign_params = {**params, "msToken": ms_token}
            # 按字典插入顺序编码，与 a_bogus 的 _serialize_params 一致
            encoded_str = urllib.parse.urlencode(sign_params)

            # 步骤 5：X-Bogus（基于编码后的 query string + UA）
            x_bogus = self._xbogus_signer.sign(encoded_str, ua)

            # 步骤 6：a_bogus（基于参数字典 + UA）
            # a_bogus 内部调用 _serialize_params 做 urlencode，
            # 但为保证一致性，这里也传编码后的字符串
            a_bogus = self._abogus_signer.sign(sign_params, ua)

            # 步骤 7：组装返回
            return {
                "X-Bogus": x_bogus,
                "a_bogus": a_bogus,
                "msToken": ms_token,
                "verifyFp": verify_fp,
            }
        except SignError:
            raise
        except Exception as e:
            raise SignError(f"签名生成失败: {e}") from e

    def generate_ms_token(self) -> str:
        """生成 msToken 参数值。

        返回:
            msToken 字符串（base64 编码，约 170+ 字符）。

        异常:
            SignError: 生成失败。
        """
        return self._mstoken_generator.generate()

    def generate_verify_fp(self) -> str:
        """生成 verify_fp 参数值。

        返回:
            verify_fp 字符串（含 ``verify_`` 前缀）。

        异常:
            SignError: 生成失败。
        """
        return self._verify_fp_generator.generate()
