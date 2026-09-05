#!/usr/bin/env python3
"""签名端到端冒烟测试（审计 M12 / A4）。

背景：抖音签名参数（Chrome UA、version_code=170400、固定 env 指纹）过期时，
全部 Web API 请求会返回 461/412/验证页，且 CI 无法提前感知。本脚本用开发者
自备的 Cookie 对 detail 接口发起一次**真实请求**，断言服务端正常返回业务
JSON 且 ``status_code == 0``，从而验证"签名参数当前仍被服务端接受"。

使用方式（手动 / 发布前 / CI workflow_dispatch 手动触发）::

    # 方式一：环境变量提供 Cookie（推荐，避免 Cookie 出现在 shell 历史）
    DOUYIN_TEST_COOKIE="sessionid=..." python scripts/signer_live_smoke.py

    # 方式二：--cookie 参数提供
    python scripts/signer_live_smoke.py --cookie "sessionid=..." --aweme-id 7433722704643820875

退出码约定:
    0  通过 —— 签名链路有效，detail 接口正常返回业务 JSON
    1  失败 —— 签名/风控异常（461/412/验证页/网络错误）或业务错误，需要更新
       版本常量（crawlers/api_spec.py / crawlers/signer/*）及 UA
    2  跳过 —— 未提供 Cookie（CI 无凭据时允许跳过）

设计依据：docs/audit/2026-09-05-security-code-audit.md §5.11 (M12)、
docs/audit/2026-09-05-security-audit-refined-guide.md §9 演进 4。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

# 脚本可独立运行：将项目根目录加入 sys.path（与 scripts/ 下其他脚本一致）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import get_memory_connection  # noqa: E402
from app.repositories import CookieRepository  # noqa: E402
from crawlers import api_spec  # noqa: E402
from crawlers.exceptions import (  # noqa: E402
    CookieInvalidError,
    NetworkError,
    RateLimitedError,
    SignError,
    VerifyRequiredError,
)
from crawlers.http_client import HttpClient  # noqa: E402
from crawlers.signer import Signer  # noqa: E402

# 默认冒烟用作品 ID（公开作品，可用作 A4 冒烟基线）
DEFAULT_AWEME_ID = "7433722704643820875"

# 环境变量名（CI secret 建议用同名）
ENV_COOKIE = "DOUYIN_TEST_COOKIE"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="抖音签名端到端冒烟测试：验证签名参数当前仍被服务端接受。",
    )
    parser.add_argument(
        "--cookie",
        default=os.environ.get(ENV_COOKIE, ""),
        help=f"抖音登录 Cookie（默认读环境变量 {ENV_COOKIE}）",
    )
    parser.add_argument(
        "--aweme-id",
        default=DEFAULT_AWEME_ID,
        help="用于冒烟的抖音作品 ID（默认公开作品）",
    )
    return parser.parse_args(argv)


async def _run_smoke(cookie: str, aweme_id: str) -> int:
    """执行一次真实 detail 请求并判定签名链路状态。"""
    conn = get_memory_connection()
    cookie_repo = CookieRepository(conn)
    signer = Signer()
    http_client = HttpClient(cookie_repo, signer)
    try:
        try:
            params = {"aweme_id": aweme_id, **api_spec.COMMON_FIXED_PARAMS}
            response = await http_client.get(
                api_spec.AWEME_DETAIL_URL,
                params=params,
                use_cookie_pool=False,  # 冒烟用显式 Cookie，不走池
                cookie=cookie,
            )
        except (CookieInvalidError, RateLimitedError, VerifyRequiredError) as e:
            # 461/412/验证页：签名参数或 Cookie 已不被服务端接受
            print(f"[FAIL] 签名链路被服务端拒绝: {e}")
            print("提示: 请更新 crawlers/api_spec.py 的 version_code/固定参数、")
            print("      crawlers/signer/* 的环境指纹常量，以及 DEFAULT_USER_AGENT。")
            return 1
        except (NetworkError, SignError) as e:
            print(f"[FAIL] 网络/签名错误: {e}")
            return 1

        try:
            payload = response.json()
        except ValueError as e:
            print(f"[FAIL] 响应非 JSON（疑似被风控拦截或空 body）: {e}")
            return 1

        status_code = payload.get("status_code")
        if status_code == 0:
            aweme_id_raw = _safe_extract_aweme_id(payload)
            print(f"[PASS] 签名链路有效: detail 接口正常返回 (aweme_id={aweme_id_raw or aweme_id})")
            return 0

        print(
            f"[FAIL] 业务错误 status_code={status_code} " f"msg={payload.get('status_msg') or '无'}"
        )
        if status_code in (80001, 22001):
            print("提示: 作品可能已删除/私密，换一个公开作品 ID 重试（签名本身可能正常）。")
        return 1
    finally:
        await http_client.close()
        conn.close()


def _safe_extract_aweme_id(payload: dict) -> str | None:
    """从 detail 响应中提取 aweme_id（字段路径异常时返回 None）。"""
    try:
        aweme = payload.get("aweme_detail") or {}
        return str(aweme.get("aweme_id") or aweme.get("awemeId") or "")
    except (AttributeError, TypeError):
        return None


def main(argv: list[str] | None = None) -> int:
    """入口：无 Cookie 时跳过（exit 2），否则执行冒烟。"""
    args = parse_args(argv)
    cookie = (args.cookie or "").strip()
    if not cookie:
        print(
            f"[SKIP] 未提供 Cookie（环境变量 {ENV_COOKIE} 或 --cookie），跳过真实请求。"
            "CI 中通过 workflow_dispatch 手动触发并配置同名 secret 后生效。"
        )
        return 2
    print(f"[INFO] 签名冒烟: aweme_id={args.aweme_id} (cookie 长度={len(cookie)})")
    return asyncio.run(_run_smoke(cookie, args.aweme_id))


if __name__ == "__main__":
    sys.exit(main())
