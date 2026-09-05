# VideoGetTool 安全审计报告 · 二次提优与落地实施指南（v2.0）

- **依据**：`docs/audit/2026-09-05-security-code-audit.md`（v1 初稿）
- **复核方式**：主代理精读全部被引用代码 + 3 个独立取证子代理交叉核对（`backend/`、`downloader/`、`crawlers/`、`frontend/`、CI、安装器、依赖），所有行号与主张均对照真实源码验证
- **复核结论**：v1 报告的 35 项发现中 **33 项属实（含行号微漂移）**，2 项表述不严谨需修正（见 §2）；另有 **4 项新发现**为 v1 遗漏（见 §3）
- **本指南与 v1 的区别**：剔除空话与过度设计；所有修复附**生产级边界处理代码**（非伪代码）；每项重大改动附**副作用/破坏性变更评估**；给出 **P0/P1/P2 看板 + Definition of Done**，可直接照单实施

---

## 0. 结论速览（一页看板）

| 优先级 | 内容 | 项数 | 落地形态 |
|---|---|---|---|
| **P0（1-2 天热修）** | Host 守卫 + WS Origin/连接上限 + 下载入队校验（download_dir/URL/扩展名白名单）+ URL 解析 host 提取修复 + Cookie 凭据加密 | 5 | 后端代码 + 单测 |
| **P1（核心体验）** | B 站 DASH 403 重解析、分页请求限速、m3u8 播放列表检测中止、ffmpeg 合并超时、孤儿 .part 清理、covers 异步化 + IPv6 崩溃修复、文件锁竞态、会员清晰度降级 | 8 | 后端代码 + 单测 |
| **P2（纵深防御/工程化）** | CSP、capabilities 收窄、custom_sound_url 校验、依赖锁定、安装器对齐、CI 安全门禁、`_safe_int`、WBI TTL、README 合规文案 | 9 | 配置/CI/文档 + 单测 |
| **演进路线（本期不实施）** | 平台适配器注册表、sidecar token 握手、HLS 完整支持、签名 E2E 冒烟基线 | 4 | 设计稿（§9） |

> 关键取舍：**本机进程威胁不是本次修复目标**（同用户进程可直接注入浏览器取 Cookie），本次所有安全修复针对的是**浏览器侧 DNS rebinding / 跨站请求**与**磁盘拷贝泄漏**两个真实攻击面。

---

## 1. 核对方法与证据基线

- 全仓 `subprocess`/`spawn`/`exec` 均为参数数组，**无 shell=True、无字符串拼接**（命令注入：✅ 三项全绿确认，v1 结论成立）
- 全仓 SQL 均参数化；动态拼接仅 3 处（PRAGMA 表名白名单 / ALTER 常量列名 / UPDATE 白名单 SET 子句），无用户输入直达 SQL 文本
- 硬编码凭据扫描：零命中（CORS `allow_credentials`、`msToken` 运行时随机生成均为误报源，已排除）
- “m3u8/HLS/AES/crypto 零匹配”**表述不严谨**：签名器 `xbogus.py`/`abogus.py` 内含 RC4 混淆实现（抖音签名算法，非媒体解密），但**无 HLS/媒体解密代码**的结论为真
- v1 中 `crawler.py:145-147` 的裸 except 实为 **`backend/api/download.py:145-147`**（文件名写错，结论不变）
- v1 中“601 个测试 / 覆盖率 85.68%”与当前工作区不一致（当前 pytest 收集 832 个测试、40 个测试文件；审计时点与当前代码已漂移，不影响发现有效性）

---

## 2. 误报甄别与降级清单（Reality Check）

### 2.1 维持原级（属实且影响成立）

| 项 | 判定 | 说明 |
|---|---|---|
| H1 零鉴权 + 无校验 → DNS rebinding 任意文件写 | ✅ 属实 | CORS 只拦“浏览器读响应”，不拦“请求发送”；`download.py:104` download_dir 直通、`downloader.py:269-271` 扩展名 `len<=5` 即采用均验证属实 |
| H2 WS 无 Origin/无上限 | ✅ 属实 | `ws.py:89` 直接 `accept()`；广播含 aweme_id（`ws.py:153`） |
| H3 Cookie 明文落盘 + WAL 副本 | ✅ 属实 | `database.py:94` `content TEXT`；`cookie.py:61` 明文返回；`bilibili.py:408` B 站 Cookie 明文写 config 表 |
| M1 covers 同步 getaddrinfo | ✅ 属实 | `covers.py:138` `socket.getaddrinfo` 阻塞事件循环；防护三层齐备（协议白名单/主机前缀黑名单/连接期 IP 校验 + `follow_redirects=False` + 20MB + Content-Type 白名单） |
| M2 ws.py 裸 except | ✅ 属实 | `ws.py:165-166` |
| M6 依赖无锁定 | ✅ 属实 | 两个 requirements 全裸下限 |
| M7 扩展名无白名单 | ✅ 属实 | `downloader.py:269-271` |
| M9 userinfo 绕过 + 落地不复检 | ✅ 属实 | `url_parser.py:150` `split(":")[0]`；`follow_redirect` 不校验 Location；B 站版有复检（不一致成立） |
| M10 DASH 403 无重解析 | ✅ 属实 | 重解析仅图集（`downloader.py:1324-1340`），DASH 失败路径 `826-839` 无重解析；url/audio_url 跨会话复用（repositories INSERT 含两列） |
| M11 分页无速率限制 | ✅ 属实 | `user_home_crawler.py:350-430` 与 `bili_user_crawler.py:193-256` 循环内均无 sleep |
| M12 签名指纹固定 | ✅ 属实 | `api_spec.py:42` version_code=170400、`signer/__init__.py:28-32` Chrome/120 UA、`abogus.py:46` `_ENV_FINGERPRINT`、`xbogus.py:36` `_CANVAS_CODE` 均写死 |
| M13 HLS 缺口 + 静默损坏 | ✅ 属实 | 全仓无 m3u8 解析；`downloader.py:921-928` 对异常 Content-Type 仅 warning 不中止 |
| S1 b23.tv 先请求后校验 | ✅ 属实 | `bili_url_parser.py:300` `follow_redirects=True` 后再校验 |
| S2 ffmpeg 无超时 | ✅ 属实 | `downloader.py:748` `proc.communicate()` 无限等待 |
| S3 删除不清理磁盘 | ✅ 属实 | `download.py:352-384` 仅删 DB 行 |
| S5 无安全门禁 | ✅ 属实 | `ci.yml` 无 gitleaks/pip-audit/npm audit/cargo audit |
| S8 int() 防御缺失 | ✅ 属实 | `user_home_crawler.py:368,402`、`cookie_tester.py:192`、`video_parser.py:538` 共 4 处 |

### 2.2 降级或修正（影响被夸大 / 方案不贴合场景）

| 项 | 原级 | 调整 | 理由 |
|---|---|---|---|
| **H2 的“隐私泄露（下载行为画像）”** | 高危 | **中危**（修复优先级不变） | aweme_id 是公开作品 ID，非隐私数据；真正的价值是“轻量 DoS + 跨站实时监听进度”。修复成本极低，仍列 P0，但影响表述应改为 DoS/跨站监听 |
| **H3 的“API 明文返回”** | 高危一部分 | **并入 H1 的 Host 守卫** | `/api/cookie/list` 明文返回只有在“浏览器侧 DNS rebinding 能调用”时才构成泄漏；Host 守卫到位后该通道关闭。API 保持明文可显著降低破坏面（见 §4.5 副作用评估） |
| **M3 CSP** | 中危 | **P2（纵深防御）** | 前端无活跃 XSS 注入点（全量检索确认），是“防御纵深”而非现役漏洞。且 CSP 改错会导致打包版黑屏/功能失效，必须随打包产物验证（见 §6.1 DoD） |
| **M5 custom_sound_url** | 中危 | **P2（顺手修）** | `new Audio(url)` 是 **WebView 客户端请求**，非服务端代拉、响应不可读回，不是经典 SSRF；且当前前端无写入该配置的 UI（仅 useNotificationService 读取）。按 P2 校验即可 |
| **M12 的“CI 定时跑签名冒烟”** | 中危修复项 | **降级为手动脚本 + 发布 checklist** | CI 无真实 Cookie，定时任务需在仓库 secrets 存放真实账号凭据——风险大于收益。改为 `scripts/` 手动冒烟脚本（见 §9 演进） |
| **M13 的完整 HLS 支持** | 中危 | **本期只做“检测中止”** | 双平台（抖音/B 站）当前不依赖 HLS；完整 m3u8+AES 是独立功能开发，列演进路线。但“静默损坏”失败模式必须本期闭合 |
| **S7 的 `_double_md5`/RC4 去重** | 建议 | **只补注释，不动算法** | 签名算法魔数是逆向产物，合并/抽取实现有字节级行为漂移风险，一旦与真实服务端不一致即全链路 461。低收益高风险，本期仅补字节布局注释 |
| **S9 第三方交叉验证向量** | 建议 | **降级为可选增强** | 第二实现若来自同一逆向源，交叉验证价值有限；且引入第三方实现有误导风险。现状“实现自洽”回归至少防重构回归 |
| **§5.1 的 token 握手方案** | 演进 | **降级为可选（P2 远景）** | Host 守卫 + H3 加密后，token 的增量价值仅剩“防本机进程”，而同用户进程本可注入浏览器取 Cookie，防护意义有限；且需改 Rust 壳 + 前端全量请求注入，成本高 |
| **§5.2 的“钉 IP 闭合 TOCTOU”** | 中危修复 | **不做钉 IP** | HTTPS + CDN 多 IP 场景（抖音/B 站 CDN 常态）下钉 IP 会破坏 failover 且需保持 SNI/Host；封面代理 `follow_redirects=False` + Content-Type 白名单下 TOCTOU 残余风险可接受。改为“异步解析 + 校验 + 放行” |
| **§5.1 的 download_dir“必须在允许目录内”** | 高危修复 | **改为“与配置目录严格一致”** | 本产品下载目录只能经“设置页 → config API”变更（前端无“下载到其他目录”UI）；v1 的“allowed_root.parents 检查”既复杂又与产品语义不符。严格一致校验即闭合攻击面且不破坏功能 |

### 2.3 已解决/无需处理

| 项 | 处理 |
|---|---|
| S5 中“版本号提交历史不一致（v0.5.0 vs v0.4.1）” | **已解决**：`f50ad70` 已把版本统一回 0.4.1，当前 HEAD 各处一致；残留的仅是 `f8e75ec` 一条提交信息的标注问题，无需代码改动 |
| M8 的 Inno `[Languages]` 重复 | 属实（`installer.iss:83/85` 重复定义 english 且注释写“简体中文”却未注册），随 P2 修复 |

---

## 3. 新发现（v1 遗漏，本期一并修复）

| # | 位置 | 问题 | 定级 |
|---|---|---|---|
| **N1** | `backend/api/covers.py:113` | **IPv6 封面 URL 触发未捕获 TypeError → 500**：`_is_blocked_ip` 中 `addr in _BENCHMARK_NETWORK`（IPv4 网段）对 `IPv6Address` 抛 `TypeError`，IPv6 主机名（含 `::ffff:` 前缀的 IPv4-mapped 地址）直接崩溃而非拦截 | P1 |
| **N2** | `backend/api/config.py:79-80` | **config API 的 `download_dir` 无校验**：任意进程/跨站可把下载目录改成任意路径（配合下载接口 = 任意路径写），是 H1 的第二个写入点，必须先于/同步 H1 修复 | P0 |
| **N3** | `downloader/downloader.py:658/673/684` | **per-path 锁提前移除的竞态**：锁在 `finally` 中 `pop`，若任务 B 等待锁 L1 期间任务 C 到达（此时 L1 已被 A pop），`setdefault` 会新建 L2，B/C 并发写同一目标文件 | P1 |
| **N4** | `backend/api/ws.py` 设计 | **Tauri 原生 WS 插件连接可能不带 Origin**：Rust 侧 WebSocket 非浏览器实现不自动发送 Origin，v1 的“Origin 不在白名单即拒绝”会把自家前端拒之门外。正确语义：**缺失 Origin 放行（本机原生客户端），存在则必须匹配白名单** | P0（随 H2） |

---

## 4. P0 修复方案（1-2 天热修）

### 4.1 P0-1 sidecar Host 守卫（H1）

**攻击面**：DNS rebinding 页面向 `http://evil.com:18989/...` 发请求，浏览器发出的 `Host` 头为 `evil.com:18989`。校验 Host 头即可在入口处拦截，且不依赖 CORS（CORS 防不了 rebinding）。

```python
# backend/security.py（新增）
"""本地 sidecar 安全中间件：Host 头守卫（DNS rebinding 防护）。

攻击模型：恶意网页通过 DNS rebinding 把 evil.com 解析到 127.0.0.1，
浏览器向 http://evil.com:18989 发请求，Host 头为 evil.com:18989。
本中间件拒绝所有 Host 不在白名单内的请求（默认拒绝）。
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

# 允许的 Host 头（大小写不敏感、允许带/不带端口）
ALLOWED_HOSTS: frozenset[str] = frozenset(
    {
        "127.0.0.1",
        "127.0.0.1:18989",
        "localhost",
        "localhost:18989",
        "::1",
        "[::1]:18989",
    }
)


def is_host_allowed(host: str | None) -> bool:
    """Host 头准入判断（供 HTTP 中间件与 WS 端点共用）。"""
    return (host or "").strip().lower() in ALLOWED_HOSTS


class HostGuardMiddleware(BaseHTTPMiddleware):
    """拒绝 Host 头不在白名单内的 HTTP 请求。"""

    async def dispatch(self, request: Request, call_next):
        if not is_host_allowed(request.headers.get("host")):
            return JSONResponse(status_code=403, content={"detail": "host not allowed"})
        return await call_next(request)
```

```python
# backend/app.py 修改
from backend.security import HostGuardMiddleware

app.add_middleware(HostGuardMiddleware)   # 必须加在 CORSMiddleware 之前（先拦截再谈 CORS）
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

> **边界处理**：① `BaseHTTPMiddleware` 只拦截 HTTP scope，**WebSocket 不会经过它**——WS 端点内自行调用 `is_host_allowed`（§4.2）；② Host 缺失（HTTP/1.0）默认拒绝；③ `[::1]:18989` 兼容 IPv6 回环。

### 4.2 P0-2 WebSocket Origin 校验 + 连接数上限 + 裸 except（H2/M2/N4）

```python
# backend/api/ws.py 修改
_MAX_WS_CONNECTIONS = 16
# 浏览器页面必有 Origin；Tauri 原生插件（Rust 侧）连接无 Origin → 放行。
_WS_ALLOWED_ORIGINS = frozenset(
    {
        "tauri://localhost",
        "http://tauri.localhost",
        "https://tauri.localhost",
        "http://localhost:1420",  # Vite 开发服务器
    }
)


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    from backend.security import is_host_allowed

    if not is_host_allowed(ws.headers.get("host")):
        await ws.close(code=1008, reason="host not allowed")
        return
    origin = ws.headers.get("origin", "")
    if origin and origin not in _WS_ALLOWED_ORIGINS:
        await ws.close(code=1008, reason="origin not allowed")
        return
    if manager.active_count >= _MAX_WS_CONNECTIONS:
        await ws.close(code=1013, reason="too many connections")
        return
    await manager.connect(ws)
    # ... 原逻辑不变
```

M2 顺手修复（`_push_progress_updates` 内）：

```python
        except Exception:
            logger.exception("共享进度推送循环异常")
```

### 4.3 P0-3 下载入队校验：download_dir 严格一致 + URL scheme + 扩展名白名单（H1/M7/N2）

```python
# backend/api/download.py 修改（新增辅助函数）
import os
from urllib.parse import urlsplit

_ALLOWED_DOWNLOAD_SCHEMES = frozenset({"http", "https"})


def _resolve_dir(path: str) -> str:
    """规范化目录：展开用户目录、取绝对路径、统一大小写（Windows）。"""
    return os.path.normcase(os.path.abspath(os.path.expanduser(path.strip())))


def _validate_download_dir(raw: str | None, configured: str) -> str:
    """下载目录准入：仅接受『与配置目录一致』的路径。

    产品语义：下载目录只能经“设置页 → config API”变更；
    入队接口收到的 download_dir 必须与配置一致，否则拒绝。
    这同时封堵 config API 之外的任意路径写（N2 的入队侧）。
    """
    candidate = (raw or configured or "").strip()
    if not candidate:
        raise HTTPException(status_code=400, detail="下载目录为空")
    if configured.strip():
        if _resolve_dir(candidate) != _resolve_dir(configured):
            raise HTTPException(
                status_code=400,
                detail="download_dir 与配置目录不一致，请在设置中修改下载目录",
            )
    return candidate


def _validate_download_url(url: str) -> str:
    """下载直链校验：仅 http/https、必须有 host。"""
    url = (url or "").strip()
    if not url:
        return ""
    parts = urlsplit(url)
    if parts.scheme not in _ALLOWED_DOWNLOAD_SCHEMES or not parts.hostname:
        raise HTTPException(status_code=400, detail=f"非法下载地址: {url[:80]}")
    return url
```

`enqueue_download_items` 内改动：

```python
    download_dir = _validate_download_dir(download_dir, ctx.config_repo.get("download_dir") or "")
    # ... 每个 item：
            media_url = _validate_download_url(item_data.get("no_watermark_url"))
            image_urls = [_validate_download_url(u) for u in (item_data.get("image_urls") or [])]
            item_video_urls = [_validate_download_url(u) for u in (item_data.get("item_video_urls") or [])]
            item_data.get("audio_url")  # B 站 DASH 音频流同样走 _validate_download_url
            item_data.get("url")        # 回退 URL 同样校验
```

```python
# backend/api/config.py 修改（N2：config 写入点同样规范化 + 拒绝空值）
import os

    if req.download_dir is not None:
        raw = req.download_dir.strip()
        if not raw:
            raise HTTPException(status_code=400, detail="下载目录不能为空")
        abs_dir = os.path.abspath(os.path.expanduser(raw))
        ctx.config_repo.set("download_dir", abs_dir)
```

扩展名白名单（`downloader/downloader.py` `_extract_extension`）：

```python
# downloader/constants.py 新增
ALLOWED_MEDIA_EXTENSIONS: frozenset[str] = frozenset(
    {
        # 视频
        ".mp4", ".mov", ".mkv", ".webm", ".flv", ".ts", ".m4s", ".avi",
        # 音频（B 站 DASH 音频流）
        ".mp3", ".m4a", ".aac", ".wav", ".ogg",
        # 图片（图集）
        ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif",
    }
)

# downloader.py 修改
    @staticmethod
    def _extract_extension(url: str, item_type: str, item_subtype: str | None = None) -> str:
        parsed = urlparse(url)
        suffix = Path(parsed.path).suffix.lower()
        if suffix in ALLOWED_MEDIA_EXTENSIONS:
            return suffix
        # 白名单外（含 .bat/.exe/.url/.m3u8/.mpd 等）一律拒绝，走类型默认值
        if item_type == "image_set" and item_subtype != "video":
            return ".jpg"
        return ".mp4"
```

> **副作用评估**：URL 后缀在白名单外时扩展名回退到 `.mp4`/`.jpg` 默认值——**不会改名成危险扩展名**，且内容层由 §5.3 的魔数检测兜底（m3u8 文本不会以 .mp4 静默落盘）。行为变化：极少数带 `.m3u8`/`.mpd` 后缀的直链会以 `.mp4` 命名并随后被 §5.3 拒绝，属预期。

### 4.4 P0-4 URL 解析 host 提取与短链落地复检（M9/S1）

```python
# crawlers/url_parser.py 修改
from urllib.parse import urljoin, urlparse  # 新增 urljoin

    @staticmethod
    def _is_douyin_url(url: str) -> bool:
        """判断 URL 是否属于抖音合法域名（urlparse 提取 host，免疫 userinfo 绕过）。"""
        try:
            host = (urlparse(url).hostname or "").lower().rstrip(".")
        except ValueError:
            return False
        return host in _DOUYIN_DOMAINS

    async def follow_redirect(self, short_url: str) -> str:
        """跟随短链重定向，逐跳校验落地域名（最多 5 跳）。"""
        current = short_url
        for _ in range(5):
            response = await self._http_client.get(current, use_cookie_pool=False)
            location = response.headers.get("location")
            if not location:
                return str(response.url)
            resolved = urljoin(current, location)
            if not self._is_douyin_url(resolved):
                raise InvalidURLFormatError(
                    f"短链重定向到非抖音域名，已拒绝: {resolved[:120]}"
                )
            current = resolved
        raise InvalidURLFormatError("短链重定向次数过多，已拒绝")
```

```python
# crawlers/bilibili/bili_url_parser.py 修改（S1：改手动逐跳跟随，先校验再请求）
from urllib.parse import urljoin, urlparse

    async def _follow_redirect(self, url: str) -> str:
        """手动跟随短链重定向，逐跳校验 host 白名单（先校验后请求）。"""
        current = url
        for _ in range(5):
            try:
                resp = await self._http_client.get(current, follow_redirects=False)
            except Exception:
                return url  # 网络异常：保持原语义回退原 URL
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return url
                resolved = urljoin(current, location)
                if (urlparse(resolved).hostname or "").lower() not in _BILI_DOMAINS:
                    return url  # 未请求任何非白名单主机即中止
                current = resolved
                continue
            return str(resp.url)
        return url
```

> **副作用评估**：`_is_douyin_url` 从“正则 host 提取”改为 urlparse，对 `https://v.douyin.com:443@evil.com/x` 的行为由“放行”变为“拒绝”，**是修复而非破坏**；对正常 URL 判定结果不变。B 站短链从“跟随后再校验”改为“逐跳先校验”，正常 b23.tv → bilibili.com 链路行为不变。

### 4.5 P0-5 Cookie 凭据加密（H3）

**威胁模型（如实声明）**：DPAPI 加密保护的是**磁盘拷贝/备份/同步/跨用户读取**；**不防同用户会话内的恶意进程**（其可注入浏览器进程直接取 Cookie）。这是 Windows 生态的固有边界，DPAPI 是成本最低的最佳实践。

```python
# app/crypto.py（新增）
"""应用本地凭据加密（Windows DPAPI）。

- Windows：CryptProtectData/CryptUnprotectData，仅当前 Windows 用户可解密，无密钥管理
- 非 Windows：明文直通 + 告警日志（本项目为 Windows 桌面工具，非 Windows 仅开发用）
- 存储格式：`v1:dpapi:<base64>`，带版本前缀支持未来迁移与“惰性加密迁移”
"""
from __future__ import annotations

import base64
import ctypes
import logging
import os
from ctypes import wintypes

logger = logging.getLogger(__name__)

_MARKER = "v1:dpapi:"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_bytes(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _protect(plain: bytes) -> bytes:
    in_blob = _DATA_BLOB(
        len(plain),
        ctypes.cast(ctypes.create_string_buffer(plain), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"CryptProtectData failed: {ctypes.get_last_error()}")
    try:
        return _blob_bytes(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _unprotect(enc: bytes) -> bytes:
    in_blob = _DATA_BLOB(
        len(enc),
        ctypes.cast(ctypes.create_string_buffer(enc), ctypes.POINTER(ctypes.c_char)),
    )
    out_blob = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob)
    ):
        raise OSError(f"CryptUnprotectData failed: {ctypes.get_last_error()}")
    try:
        return _blob_bytes(out_blob)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def encrypt_secret(plain: str) -> str:
    """加密明文；空值与非 Windows 直通。"""
    if not plain:
        return plain
    if os.name != "nt":
        logger.warning("非 Windows 环境，凭据将以明文存储（仅开发用途）")
        return plain
    return _MARKER + base64.b64encode(_protect(plain.encode("utf-8"))).decode("ascii")


def decrypt_secret(value: str) -> str:
    """解密存储值；无前缀（旧明文/空值）原样返回，由调用方触发惰性迁移。"""
    if not value or not value.startswith(_MARKER):
        return value
    payload = base64.b64decode(value[len(_MARKER):])
    return _unprotect(payload).decode("utf-8", errors="replace")


def is_encrypted(value: str) -> bool:
    return value.startswith(_MARKER)
```

**接入点**：
1. `app/repositories.py` `CookieRepository`：`add/update_content` 写加密；所有读（`get_all/get_valid/get_by_id/test_all`）统一经 `_decrypt(row)` 解密，并在读到旧明文时**惰性迁移**（就地 update 为密文）。
2. `backend/api/bilibili.py`：`bili_set_cookie` 写 `encrypt_secret`；读 `config_repo.get("bilibili_cookie")` 的三处（:226/:290/:381）经 `decrypt_secret`。
3. `GET /api/cookie/list` **本期保持明文返回**（Host 守卫已封堵远程读取；本地进程本可直接读 DB，加密只对磁盘拷贝生效）——若强制脱敏需改前端展示，属破坏性变更，列为后续可选。

> **副作用/破坏性变更（重要）**：
> - 旧库中已有明文 Cookie：首次读取时惰性迁移为密文，**用户无感**；
> - **降级不可逆**：Windows 加密后的值换到另一台机器/另一 Windows 用户无法解密（DPAPI 用户绑定），DB 迁移/同步场景需提示；
> - 测试环境：内存库测试在 Windows 上会真实调用 DPAPI（可解可加密），Linux CI 下直通明文——**测试必须覆盖两种路径**（注入 fake crypto 或按平台跳过断言）。
> - 若 sidecar 以**服务方式**（非交互用户会话）运行，DPAPI 可能失败——当前 sidecar 由 Tauri 壳以用户会话启动，无此问题；文档注明约束。

---

## 5. P1 修复方案（核心体验）

### 5.1 P1-1 B 站 DASH 直链过期重解析（M10）

`Downloader` 新增可选注入 `bili_reparser`，失败分支（403/404 + bvid/cid）单次重解析后重试：

```python
# downloader/downloader.py 修改
    def __init__(self, ..., bili_reparser=None):
        ...
        self._bili_reparser = bili_reparser  # Callable[[TaskItem], Awaitable[tuple[str,str]|None]]

    async def _download_dash(self, task_item: TaskItem, final_path: Path, _reparsed: bool = False) -> DownloadResult:
        ...
            if not video_result.success:
                reason = video_result.error or "视频流下载失败"
                if (
                    not _reparsed
                    and self._bili_reparser is not None
                    and task_item.bvid
                    and self._is_link_expired(reason)
                ):
                    new_urls = await self._bili_reparser(task_item)
                    if new_urls:
                        task_item.url, task_item.audio_url = new_urls
                        logger.info("B 站 DASH 直链已过期，重新解析后重试 task_item id=%s", task_item.id)
                        return await self._download_dash(task_item, final_path, _reparsed=True)
                self._mark_status(task_item.id, "failed", fail_reason=reason)
                return video_result
            # audio_result 分支同构处理
```

```python
# backend/app.py 装配
    async def _reparse_bili_urls(task_item):
        """B 站 DASH 直链过期重解析：重新调 playurl，返回 (video_url, audio_url)。"""
        if ctx.bili_video_parser is None or not task_item.bvid or not task_item.cid:
            return None
        try:
            cookie = None
            if ctx.config_repo is not None:
                cookie = decrypt_secret(ctx.config_repo.get("bilibili_cookie") or "") or None
            result = await ctx.bili_video_parser.parse_playurl(
                bvid=task_item.bvid, cid=int(task_item.cid), cookie=cookie
            )
        except Exception:
            logger.exception("B 站 DASH 重解析失败 task_item id=%s", task_item.id)
            return None
        if result.dash and result.video_streams and result.audio_streams:
            video = next((s for s in result.video_streams if s.url), None)
            audio = next((s for s in result.audio_streams if s.url), None)
            if video and audio:
                return (video.url, audio.url)
        if result.url:
            return (result.url, "")
        return None
```

> **边界处理**：`_reparsed=True` 防无限递归；`_is_link_expired` 只认 “HTTP 403/404”；重解析失败返回 None 维持原失败结果；cookie 解密失败（非 Windows 明文）不阻断。

### 5.2 P1-2 分页请求限速（M11）

```python
# crawlers/http_client.py 新增（模块级辅助，抖音/B 站爬虫共用）
import random

async def pagination_throttle(min_delay: float = 0.3, max_delay: float = 0.8) -> None:
    """分页请求最小间隔（300-800ms 抖动），防高频脉冲触发风控。"""
    await asyncio.sleep(random.uniform(min_delay, max_delay))
```

调用点：`user_home_crawler.py` 分页循环末尾（`max_cursor = next_cursor_val` 后）、`bili_user_crawler.py` `_collect_pages`/`_fetch_pages` 的 `page += 1` 后。

> **副作用**：单页间隔 0.3-0.8s，订阅模式（30 条/30 分钟）与单次抓取感知不到；仅批量大 max_items 抓取变慢，属预期取舍。

### 5.3 P1-3 m3u8 播放列表检测中止（M13 最低限度）

**双保险**：Content-Type 检查 + 响应体魔数嗅探（CDN 常返回缺失/错误的 Content-Type，魔数探测是必须的）。

```python
# downloader/downloader.py 修改
_SNIFF_BYTES = 512
_PLAYLIST_HINTS = (b"#EXTM3U", b"#EXT-X-TARGETDURATION", b"#EXTM3U8")


class DownloadFailedError(Exception):
    """下载失败（业务原因，不重试）。"""


def _looks_like_playlist(head: bytes) -> bool:
    stripped = head.lstrip()
    return stripped.startswith(b"#EXTM3U") or b"#EXT-X-" in head[: _SNIFF_BYTES]


def _looks_like_m3u8_content_type(content_type: str) -> bool:
    ct = content_type.lower()
    return "mpegurl" in ct or "x-mpegurl" in ct


def _reject_playlist(task_item: TaskItem, detail: str) -> None:
    raise DownloadFailedError(
        f"task_item={task_item.id} 目标为 HLS 播放列表(m3u8)，当前版本不支持: {detail}"
    )
```

`_download_single_file` 内，进入流式接收前（仅从头下载、非续传时嗅探）：

```python
            resp_content_type = response.headers.get("Content-Type", "").lower()
            if _looks_like_m3u8_content_type(resp_content_type):
                # 走失败分支（标记 failed，删除 .part）
                raise DownloadFailedError(
                    f"HTTP {response.status_code} 目标为 HLS 播放列表(m3u8)，当前版本不支持"
                )
```

`_stream_to_file` 增加嗅探（修改签名，`_download_single_file` 传入回调）：

```python
    async def _stream_to_file(self, response, part_path, task_item, downloaded_bytes,
                              total_bytes, report_progress=True, sniff_guard=None):
        mode = "wb" if downloaded_bytes == 0 else "ab"
        sniffed: bytearray | None = bytearray() if (sniff_guard and downloaded_bytes == 0) else None
        try:
            with open(part_path, mode) as f:
                async for chunk in response.aiter_bytes(CHUNK_SIZE):
                    if sniffed is not None:
                        sniffed.extend(chunk[: _SNIFF_BYTES - len(sniffed)])
                        if len(sniffed) >= _SNIFF_BYTES:
                            sniff_guard(bytes(sniffed))
                            sniffed = None
                    f.write(chunk)
                    ...
        except asyncio.CancelledError:
            self._persist_progress(...)
            raise
        # 流结束但不足 _SNIFF_BYTES（小响应）也要检查
        if sniffed is not None:
            sniff_guard(bytes(sniffed))
        ...
```

调用点（`_download_single_file` 内构造 `sniff_guard`）：

```python
            def _guard(head: bytes) -> None:
                if _looks_like_playlist(head):
                    # 清掉已写部分
                    if part_path.exists():
                        part_path.unlink()
                    _reject_playlist(task_item, "响应体为 m3u8 文本")
```

并在 `except` 链捕获 `DownloadFailedError` → 标记 failed + 返回 `DownloadResult(success=False, error=...)`（**不重试**，`_should_retry` 不涉及该分支）。

> **副作用**：仅新增失败分支，正常媒体下载路径零变化；极端情况（合法二进制恰好以 `#EXTM3U` 开头，概率≈0）会误拒，可接受。

### 5.4 P1-4 ffmpeg 合并超时（S2）

```python
# downloader/downloader.py 修改
FFMPEG_MERGE_TIMEOUT_SECONDS: float = 600.0  # 10 分钟，-c copy 流拷贝通常数秒

    async def _merge_dash_streams(self, video_path, audio_path, output_path) -> None:
        ...
        proc = await asyncio.create_subprocess_exec(...)
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=FFMPEG_MERGE_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            if output_path.exists():
                output_path.unlink(missing_ok=True)
            raise RuntimeError(
                f"ffmpeg 合并超时（>{FFMPEG_MERGE_TIMEOUT_SECONDS:.0f}s），已终止并清理输出"
            )
```

> **边界处理**：超时后 `kill()`（Windows 即 TerminateProcess）+ 清理半成品输出，避免残留损坏文件；10 分钟对 4K/长视频保守，超时多为 ffmpeg 挂死而非慢。

### 5.5 P1-5 孤儿 `.part` 清理 + 删除任务清理磁盘（S3）

**启动清理**（只清“久未触碰”的孤儿临时文件，不影响断点续传）：

```python
# downloader/downloader.py 新增
ORPHAN_PART_MAX_AGE_SECONDS: float = 7 * 24 * 3600  # 7 天

    def cleanup_orphan_part_files(self, roots: list[Path]) -> int:
        """清理下载目录下超过 7 天未修改的 *.part* 文件。

        断点续传中的 .part 会被持续写入，不会超龄；
        超龄 .part 只可能是崩溃/删除残留，删除仅损失部分进度。
        """
        removed = 0
        cutoff = time.time() - ORPHAN_PART_MAX_AGE_SECONDS
        for root in roots:
            try:
                for p in root.rglob("*"):
                    if p.is_file() and p.name.endswith(".part"):
                        try:
                            if p.stat().st_mtime < cutoff:
                                p.unlink()
                                removed += 1
                                logger.info("清理孤儿 .part: %s", p)
                        except OSError:
                            continue
            except OSError:
                continue
        return removed
```

接入：`app.py` lifespan 在 `restore_pending_tasks()` 后调用一次（根目录 = 配置 download_dir）。

**删除任务/任务项时清理文件**（`backend/api/download.py`，best-effort + 目录包含性防护）：

```python
def _safe_remove_output(path: str | None, download_dir: str) -> None:
    """在下载目录范围内删除产物（防越界误删）。"""
    if not path:
        return
    try:
        abs_path = os.path.abspath(path)
        abs_root = os.path.abspath(download_dir)
        if os.path.commonpath([abs_path, abs_root]) != abs_root:
            logger.warning("跳过删除（不在下载目录内）: %s", path)
            return
        if os.path.isfile(abs_path):
            os.remove(abs_path)
        elif os.path.isdir(abs_path):
            import shutil

            shutil.rmtree(abs_path, ignore_errors=True)
        part = abs_path + ".part"
        if os.path.isfile(part):
            os.remove(part)
    except OSError:
        logger.warning("清理产物失败: %s", path, exc_info=True)
```

`delete_task_item`：删除前取 `item.local_path` 与所属 task 的 download_dir，删行后调用 `_safe_remove_output`。`delete_task`：先取所有 item 的 local_path，删行后逐个清理。`clear_completed`：**保持只删记录不删文件**（“清除已完成”是记录清理语义，避免误删用户保留的成品）。

> **破坏性变更（需前端知晓）**：删除任务/任务项现在会**物理删除产物文件**，语义从“只删记录”变为“删记录+删文件”。若未来需要“保留文件”，需前端增加选项（本期不做，文档注明）。

### 5.6 P1-6 covers 异步化 + IPv6 崩溃修复（M1/N1）

```python
# backend/api/covers.py 修改
    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host:
            port = request.url.port or (443 if request.url.scheme == "https" else 80)
            loop = asyncio.get_running_loop()
            try:
                addrinfos = await loop.getaddrinfo(
                    host, port, type=socket.SOCK_STREAM
                )
            except OSError as exc:
                raise httpx.ConnectError(f"DNS resolution failed for {host}: {exc}") from exc
            for info in addrinfos:
                ip = info[4][0]
                if _is_blocked_ip(ip):
                    raise httpx.ConnectError(f"blocked target ip {ip} for host {host}")
        return await super().handle_async_request(request)
```

`_is_blocked_ip` 修复（N1：IPv6 不再抛 TypeError）：

```python
def _is_blocked_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    # 仅同版本才做基准网段放行比较（IPv6 恒为禁止路径，走下方分支）
    if isinstance(addr, ipaddress.IPv4Address) and addr in _BENCHMARK_NETWORK:
        return False
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )
```

> **说明**：不做“钉 IP 闭合 TOCTOU”（CDN 多 IP + HTTPS SNI 副作用），残余 TOCTOU 由 `follow_redirects=False` + Content-Type 白名单 + 20MB 上限兜底（v1 §5.2 注明的取舍，本指南采纳“异步解析 + 校验 + 放行”）。

### 5.7 P1-7 文件锁竞态（N3）

```python
# downloader/downloader.py 修改
# 锁生命周期：**不 pop**。pop 会造成“等待者仍持有旧锁、新任务拿到新锁”的并发窗口
# （竞态：任务 B 等锁期间任务 C 到达 → C 新建锁 → B/C 并发写同一目标）。
# 代价是每条唯一路径的锁随会话累积（桌面工具单会话目标数有限，可接受）。
            async with lock:
                # 移除 finally 中的 self._file_locks.pop(...)（三处：图集/DASH/单文件）
```

### 5.8 P1-8 B 站会员清晰度降级 + 空流跳过（S4）

```python
# backend/api/bilibili.py 修改（bili_playurl 端点）
    try:
        playurl = await ctx.bili_video_parser.parse_playurl(
            bvid=req.bvid, cid=req.cid, quality=req.quality, cookie=cookie
        )
    except BiliAPIError as e:
        # 会员清晰度无权限（-403）→ 降级到 1080P（qn=80）重试一次
        if req.quality > 80 and ("403" in str(e.message) or "登录" in str(e.message)):
            logger.info("请求 qn=%d 无权限（%s），降级到 qn=80 重试", req.quality, e.message)
            playurl = await ctx.bili_video_parser.parse_playurl(
                bvid=req.bvid, cid=req.cid, quality=80, cookie=cookie
            )
        else:
            raise HTTPException(status_code=400, detail=f"B 站 API 错误: {e.message}") from e
```

```python
# crawlers/bilibili/bili_video_parser.py _parse_playurl_response 修改（S4 空流）
        if dash_data:
            for v in dash_data.get("video") or []:
                if not isinstance(v, dict):
                    continue
                url = v.get("base_url") or ""
                backup = v.get("backup_url") or []
                if not url and not backup:
                    continue  # 空流跳过
                if not url:
                    url = backup[0] or ""
                if not url:
                    continue
                video_streams.append(BiliStream(id=..., url=url, base_url=backup[0] if backup else None, ...))
        # 解析完成后：
        if not video_streams and not single_url and dash_data:
            raise VideoNotFoundError(f"无可用的视频播放流: bvid={bvid}, cid={cid}")
```

---

## 6. P2 修复方案（纵深防御与工程化）

### 6.1 P2-1 CSP（M3）

```jsonc
// frontend/src-tauri/tauri.conf.json
"security": {
  "csp": "default-src 'self' http://tauri.localhost; connect-src 'self' http://127.0.0.1:18989 ws://127.0.0.1:18989; img-src 'self' http://127.0.0.1:18989 data: blob:; media-src 'self' http: https: file: data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; script-src 'self'",
  "devCsp": null
}
```

> - `devCsp: null`：开发模式（Vite HMR 需要内联/WS）不受影响，只给生产加 CSP；
> - `media-src` 放宽到 `http: https: file:` 是为兼容自定义提示音（`new Audio(远程URL/本地文件)`）；
> - **DoD 必须含**：执行一次完整 `npm run build` + `tauri build` 打包冒烟，确认封面图、WS、音效、样式均正常；任何 CSP 报错按“阻断发布”处理（CSP 误配的代价是黑屏，高于它防的威胁）。

### 6.2 P2-2 capabilities 收窄 + window-state（M4）

```jsonc
// frontend/src-tauri/capabilities/default.json
"permissions": [
  // ...原有项...
  {
    "identifier": "websocket:default",
    "allow": [
      { "url": "ws://127.0.0.1:18989" },
      { "url": "ws://localhost:18989" }
    ]
  }
  // 删除 "window-state:allow-restore-state"
]
```

```rust
// frontend/src-tauri/src/lib.rs：StateFlags 去掉 VISIBLE | FULLSCREEN
.with_state_flags(StateFlags::SIZE | StateFlags::POSITION | StateFlags::MAXIMIZED)
```

> **副作用**：窗口不再恢复“全屏/可见”标志（避免钓鱼式窗口状态恢复）；**DoD 含一次打包验证**——capabilities 语法错误会导致打包失败，需真实构建确认。

### 6.3 P2-3 custom_sound_url 校验（M5）

```python
# backend/api/config.py 修改
from urllib.parse import urlsplit

_SOUND_EXTENSIONS = (".mp3", ".wav", ".ogg", ".m4a", ".aac")

def _validate_sound_url(value: str) -> None:
    """custom_sound_url 准入：http(s)/file URL 或本地绝对路径，且为音频扩展名。"""
    if not value:
        return
    lower = value.lower()
    if not lower.endswith(_SOUND_EXTENSIONS):
        raise HTTPException(status_code=400, detail="custom_sound_url 仅支持音频文件（mp3/wav/ogg/m4a/aac）")
    parts = urlsplit(value)
    if parts.scheme in ("http", "https", "file") and parts.hostname:
        return
    if os.path.isabs(value):  # Windows 盘符路径或 UNC 路径
        return
    raise HTTPException(status_code=400, detail="custom_sound_url 格式不允许（仅 http(s)/file URL 或本地路径）")
```

> 兼容性：前端 `custom`（远程 mp3）/`custom_wav`（本地 wav）两种用法均放行；当前无写入 UI，不存在破坏存量配置的问题。

### 6.4 P2-4 依赖锁定（M6）

```text
# requirements.txt（按当前验证通过的版本精确锁定）
fastapi==0.141.1
uvicorn==0.52.1
httpx[http2]==0.28.1
curl_cffi==0.16.2
Pillow==12.3.0

# requirements-dev.txt（新增锁文件，首行引入运行依赖）
-r requirements.txt
pytest==9.1.1
pytest-asyncio==1.4.0
pytest-cov==7.1.0
respx==0.23.1
ruff==0.16.1
black==26.5.1
pip-audit==2.9.0        # CI 安全门禁用（见 6.6）
```

> **DoD**：锁定后必须在本机（Python 3.14 当前环境）与 CI（Python 3.11）各跑通一次全量测试与构建；`curl_cffi` 是平台相关 wheel，锁定版本需在 CI 验证可安装。

### 6.5 P2-5 安装器对齐（M8）

`installer.iss` 修复 [Languages]（注册真实简体中文 + 去掉重复）：

```ini
[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
```

权限对齐：若 Inno 仍是发布产物之一，`DefaultDirName={localappdata}\Programs\VideoGetTool` + `PrivilegesRequired=lowest` 对齐 NSIS `currentUser`；若 Inno 已废弃（release.yml 走 Tauri NSIS），则**删除 installer.iss 或在文件头标注 deprecated**，避免“两套安装器策略”长期分裂。**以 release.yml 实际产线为准**（本期核对后选择：保留文件 + 修语言重复 + 头注释标注“Tauri NSIS 为当前发布通道”）。

### 6.6 P2-6 CI 安全门禁（S5）

`.github/workflows/ci.yml` 增量：
- **gitleaks**（防密钥泄漏）：`gitleaks/gitleaks-action@v2`，PR/push 全跑（硬门禁）；
- **pip-audit**（Python 供应链 CVE）：lint-test job 末尾 `pip install pip-audit && pip-audit`，**先以 `continue-on-error: true` 落地**（本机镜像源不可用未建立基线），基线清理后翻转为硬门禁（注释注明）；
- **npm audit**：frontend-check job 末尾 `npm audit --audit-level=high`（GitHub Actions 默认 registry 可正常执行；本地镜像源 404 属环境问题，CI 不受影响）；
- **cargo audit**：当前 CI 无 Rust job（Rust 仅在 release.yml 出现），**不新增**——在 guide 中注明“引入 Rust job 时补 cargo audit”。

### 6.7 P2-7 `_safe_int` 统一（S8）

```python
# crawlers/utils.py（新增）
def safe_int(value, default: int = 0) -> int:
    """防御性 int 转换：None/空/非数字字符串 → default。"""
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default
```

替换 4 处：`user_home_crawler.py:368,402`、`cookie_tester.py:192`、`video_parser.py:538`。注意 `user_home_crawler.py:406` 的 `next_cursor` 已有 try/except 包装（保留语义），仅替换无包装处。

### 6.8 P2-8 WBI TTL 缩短（S10）

`crawlers/bilibili/constants.py:101` `WBI_KEY_CACHE_TTL: int = 86400` → `43200`（12h）。低风险低收益，顺手改。

### 6.9 P2-9 README 合规文案（S6）

README 顶部“简介”改为“抖音短视频/B 站视频数据抓取（下载）的 Windows 桌面工具”，并新增“合理使用声明”（仅个人学习研究、尊重平台条款与版权、勿用于商业抓取/批量牟利），与 THIRD-PARTY-NOTICES 的合规说明呼应。

### 6.10 P2-10 签名器注释（S7 裁剪版）

- `xbogus.py:36` `_CANVAS_CODE` 与 `abogus.py:46` `_ENV_FINGERPRINT` 补“字节布局/来源”注释（仅注释，不动魔数）；
- `bili_signer.py:256-259` buvid3 的 `random` → `secrets`（反爬关联性，非安全必需）；
- **不做** `_double_md5`/RC4 去重（§2.2 降级理由）。

---

## 7. 破坏性变更与副作用总表

| 改动 | 破坏性变更 | 影响面 |
|---|---|---|
| P0-1 Host 守卫 | 无（正常前端 Host 恒为 127.0.0.1:18989） | 仅异常工具链（自定义 Host 的调试代理）需注意 |
| P0-2 WS Origin/上限 | **Tauri 原生 WS 连接无 Origin → 已放行**；连接数上限 16 远超单前端连接数 | 几乎无感 |
| P0-3 入队校验 | download_dir 必须与配置一致：**绕过设置直接指定其他目录的调用将 400**（当前前端无此用法） | 低 |
| P0-3 扩展名白名单 | 白名单外后缀回落默认扩展名 | 低（内容层有魔数检测兜底） |
| P0-4 URL 解析 | `userinfo@` 恶意 URL 由“放行”变“拒绝”（修复）；B 站短链行为不变 | 低 |
| P0-5 Cookie 加密 | ① 旧明文自动惰性迁移；② **加密值绑定 Windows 用户**，换用户/换机不可读；③ 非 Windows 明文直通 | 中（需在更新说明中告知） |
| P1-1 DASH 重解析 | 仅新增“403 后重试一次”路径 | 低 |
| P1-2 限速 | 批量抓取变慢 0.3-0.8s/页 | 低 |
| P1-3 m3u8 检测 | 目标为 m3u8 时从“静默保存坏文件”变“明确失败” | 低（行为是修正） |
| P1-4 ffmpeg 超时 | 挂死的合并 10 分钟后被终止（此前永久卡死） | 低（修正） |
| P1-5 删除清理 | **删除任务/任务项将物理删除产物文件**（此前只删记录） | **中——需前端/更新说明同步语义** |
| P1-5 孤儿清理 | 7 天未触碰的 .part 被删（仅损失部分进度） | 低 |
| P1-6 covers | 无 | 低 |
| P1-7 锁不 pop | 内存中锁对象随会话累积（目标路径数量级，可接受） | 低 |
| P1-8 清晰度降级 | 无会员时 qn>80 自动降到 80（此前直接失败） | 低（修正） |
| P2-1 CSP | 打包产物安全策略收紧；**必须打包验证**，误配=黑屏 | 中（验证后低） |
| P2-2 capabilities | 窗口不再恢复全屏/可见标志 | 低 |

---

## 8. P0/P1/P2 任务看板（含 DoD）

### P0（1-2 天热修）

| ID | 任务 | 文件 | DoD（验收标准） |
|---|---|---|---|
| P0-1 | Host 守卫中间件 | `backend/security.py`（新）、`backend/app.py` | 恶意 Host（`evil.com:18989`/缺失）→ 403；正常 `127.0.0.1:18989` → 放行；有单测覆盖 |
| P0-2 | WS Origin 校验 + 连接上限 + 裸 except 修复 | `backend/api/ws.py` | 非白名单 Origin → 1008 关闭；连接数 ≥16 → 1013；无 Origin 放行；`except: pass` 改为 `log.exception`；单测覆盖 |
| P0-3 | 下载入队校验（download_dir/URL scheme/扩展名白名单）+ config download_dir 规范化 | `backend/api/download.py`、`backend/api/config.py`、`downloader/constants.py`、`downloader/downloader.py` | 任意路径 download_dir → 400；`file://`/无 scheme URL → 400；`.bat/.exe/.url` 后缀不再采用；正常下载路径行为不变；单测覆盖 |
| P0-4 | URL host 提取修复 + 短链落地复检（抖音/B 站） | `crawlers/url_parser.py`、`crawlers/bilibili/bili_url_parser.py` | `userinfo@` 绕过用例被拒；跨域重定向被拒；正常短链解析不变；单测覆盖 |
| P0-5 | Cookie/B 站 Cookie 加密（DPAPI）+ 惰性迁移 | `app/crypto.py`（新）、`app/repositories.py`、`backend/api/bilibili.py` | 磁盘无明文 Cookie（含 config 表 bilibili_cookie）；旧明文读取即迁移；解密-加密往返一致；非 Windows 直通；单测覆盖两种路径 |
| P0-6 | 回归：全量测试 + ruff/black | — | `pytest`（832 项）通过且覆盖率 ≥80%；`ruff check .`、`black --check .` 通过 |

### P1（核心体验）

| ID | 任务 | 文件 | DoD |
|---|---|---|---|
| P1-1 | B 站 DASH 403 重解析（单次、防递归） | `downloader/downloader.py`、`backend/app.py` | 模拟 403 → 触发重解析并成功重试；重解析失败维持原失败；无死循环；单测覆盖 |
| P1-2 | 分页请求限速（抖音/B 站） | `crawlers/http_client.py`、`user_home_crawler.py`、`bili_user_crawler.py` | 分页循环相邻请求间隔 ≥0.3s；单测覆盖（mock sleep） |
| P1-3 | m3u8 播放列表检测中止 | `downloader/downloader.py` | Content-Type=mpegurl 或响应头 512B 含 `#EXTM3U` → 明确失败、.part 清理；正常下载不变；单测覆盖 |
| P1-4 | ffmpeg 合并超时 | `downloader/downloader.py` | 合并 >600s → 终止 + 清理输出 + 失败原因明确；单测覆盖（mock communicate 超时） |
| P1-5 | 孤儿 .part 清理 + 删除任务清理磁盘 | `downloader/downloader.py`、`backend/api/download.py`、`backend/app.py` | 启动清理超龄 .part；删除任务/项删除目录内产物、越界路径跳过；clear-completed 不删文件；单测覆盖 |
| P1-6 | covers 异步化 + IPv6 修复 | `backend/api/covers.py` | 慢 DNS 不再阻塞事件循环；IPv6 目标 → 拒绝而非 500；单测覆盖 |
| P1-7 | 文件锁竞态修复 | `downloader/downloader.py` | 锁不再提前 pop；并发同名目标串行写入；单测覆盖 |
| P1-8 | B 站清晰度降级 + 空流跳过 | `backend/api/bilibili.py`、`bili_video_parser.py` | qn>80 无权限 → 自动降级 80；空 URL 流跳过、全空报错；单测覆盖 |
| P1-9 | 回归：全量测试 + lint | — | 同 P0-6 |

### P2（纵深防御/工程化）

| ID | 任务 | 文件 | DoD |
|---|---|---|---|
| P2-1 | CSP（生产生效 + devCsp null） | `frontend/src-tauri/tauri.conf.json` | 打包产物冒烟：封面/WS/音效/样式正常；CSP 报错视为阻断 |
| P2-2 | capabilities WS scope + window-state 收窄 | `capabilities/default.json`、`src-tauri/src/lib.rs` | 打包验证通过；无 restore-state |
| P2-3 | custom_sound_url 校验 | `backend/api/config.py` | 非法值 400；合法 http/file/本地路径放行；单测 |
| P2-4 | 依赖锁定 | `requirements.txt`、`requirements-dev.txt` | 本机 + CI（3.11）测试通过；可复现安装 |
| P2-5 | 安装器语言与权限对齐 | `installer.iss` | 无重复语言；文件头标注发布通道 |
| P2-6 | CI 安全门禁 | `.github/workflows/ci.yml` | gitleaks 硬门禁；pip-audit/npm audit 落地（基线注明） |
| P2-7 | `_safe_int` 统一 | `crawlers/utils.py`（新）+ 4 调用点 | 非数字字符串不再抛 ValueError；单测 |
| P2-8 | WBI TTL 12h | `crawlers/bilibili/constants.py` | 常量值变更 + 注释 |
| P2-9 | README 合规文案 | `README.md` | 简介含 B 站；合理使用声明置顶 |
| P2-10 | 签名器注释 + buvid3 secrets | `signer/xbogus.py`、`abogus.py`、`bili_signer.py` | 仅注释/`secrets` 替换，无算法行为变化；签名向量测试通过 |
| P2-11 | 回归：全量测试 + lint + 前端 tsc | — | 同 P0-6 + `npx tsc --noEmit` 通过 |

---

## 9. 演进路线（本期不实施，仅设计定位）

| 演进 | 内容 | 触发条件 |
|---|---|---|
| 演进 1 | 平台适配器注册表（Extractor registry）：统一 `ParseResult` 契约、按平台注册 URLParser/VideoParser/HTTPClient/Referer，终结 `bvid/audio_url` 字段特判与 `app.py` 逐组件手工装配 | 接入第三平台（小红书/YouTube）前 |
| 演进 2 | sidecar token 握手（Rust 生成随机 token → 环境变量 → `Authorization: Bearer`）+ Cookie API 脱敏 | 若未来引入“以服务方式运行 sidecar”或多实例隔离需求 |
| 演进 3 | HLS/m3u8 完整支持：`#EXT-X-KEY` AES-128 CBC 解密（pycryptodome）+ 分段并发 + ffmpeg 合并；ffmpeg `-c copy` 失败 fallback 重编码；无 ffmpeg 时“仅下载流”选项 | 平台出现强制 HLS 内容且用户需求成立 |
| 演进 4 | 签名 E2E 冒烟基线：`scripts/signer_live_smoke.py`（手动/发布前运行，用开发者自备 Cookie 打一次 detail 接口），把 A4“算法过期无感知”从 CI 不可行改为发布流程 checklist | 发布流程固化时 |

---

## 10. 验证清单（发布前人工确认）

- [ ] `python -m pytest` 全量通过、覆盖率 ≥80%（832 项基线）
- [ ] `ruff check .` / `black --check .` 通过
- [ ] 手工冒烟：正常抖音/B 站下载、暂停/恢复、图集、订阅扫描不受影响
- [ ] `GET /api/cookie/list` 在恶意 Host 下 403；正常前端可访问
- [ ] 升级后旧 Cookie 自动迁移为密文（检查 data.db 无明文）
- [ ] 打包版冒烟（P2-1/P2-2 DoD）
- [ ] 删除任务后磁盘产物被清理（P1-5 语义变更已同步前端文案）

---

*本指南由 v1 审计报告经全量代码复核后重写；所有修复均附边界处理与副作用评估，P0/P1 本期实施，P2 按看板执行，演进路线留待后续版本。*
