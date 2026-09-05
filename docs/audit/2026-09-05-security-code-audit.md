# VideoGetTool 深度代码审查与安全审计报告

- **审查对象**：`Cat-Drink/VideoGetTool`（工作区 `D:\Program\VideoGetTool`，v0.4.1）
- **审查日期**：2026-09-05
- **审查方式**：全量源码只读审查（Python sidecar / Rust Tauri 壳 / React 前端 / 测试 / CI / 打包脚本），并行子代理独立交叉审计
- **架构概况**：Tauri 2 (Rust) 桌面壳 + React 19 前端 + Python FastAPI sidecar（绑定 127.0.0.1:18989，无鉴权）；抖音（curl_cffi + XBogus/ABogus 签名）与 B 站（httpx + WBI 签名、DASH 下载 + ffmpeg 合并）双平台。

---

## 1. 风险评级摘要

### 🔴 高危（应立即修复）

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| H1 | `backend/app.py:272-284`、`backend/api/download.py:25-31,104-112`、`downloader/downloader.py:187,213-219,255-271` | **本地 sidecar 零鉴权 + 下载接口无 SSRF/路径/扩展名校验 → DNS rebinding 可形成任意文件写原语**。CORS 白名单只拦"浏览器同源读"，不拦请求发送也不防 DNS rebinding；攻击者域名解析到 127.0.0.1 后浏览器将其视为同源，可读取 Cookie/配置（`/api/cookie/list`）、写入任意 `download_dir` 并以 URL 后缀（`.bat`/`.exe`/`.url`，`len(suffix)<=5` 即采用，无白名单）落盘任意内容 | 窃取账号 Cookie、向启动目录写入可执行文件（重启后 RCE 前置）；本机任意进程同样可全量调用 |
| H2 | `backend/api/ws.py:82-119,122-168` | **WebSocket 无 Origin 校验、无连接数上限，广播含 aweme_id**。WebSocket 握手不受 CORS 约束，任意网页可 `new WebSocket("ws://127.0.0.1:18989/api/ws")` 实时窃听下载进度/状态/失败原因（含 aweme_id → 还原用户下载行为画像），并可开大量 socket 拖垮后端 | 隐私泄露（下载行为画像）、轻度 DoS；修复成本最低，应最先修 |
| H3 | `app/database.py:91-102`（cookies 表）、`backend/api/cookie.py:52-70`、`backend/api/bilibili.py:408` | **账号 Cookie 明文落盘且经 API 明文返回**。`%APPDATA%/VideoGetTool/data.db` 无任何加密（全仓无 crypto/DPAPI 代码），WAL 模式下 `data.db-wal` 还保留明文副本；B 站 Cookie 明文写入 config 表 `bilibili_cookie` 键；`GET /api/cookie/list` 直接返回完整 Cookie 串 | 与本机恶意进程/跨站链叠加时直接泄露登录会话凭据，可接管抖音/B 站账号（Cookie 池与 `use_saved_cookie` 会自动复用被窃 Cookie） |

### 🟠 中危

| # | 位置 | 问题 | 影响 |
|---|------|------|------|
| M1 | `backend/api/covers.py:133-145` | **SSRF 防护存在 TOCTOU 与事件循环阻塞**：`socket.getaddrinfo` 为同步阻塞调用（慢 DNS 可阻塞整个 FastAPI 事件循环 = DoS）；校验后 `super().handle_async_request` 会再次解析域名，两次解析窗口存在 DNS rebinding 绕过可能 | covers 代理被慢 DNS 拖垮；极端条件下 SSRF 绕过（防护已优于多数实现，但未闭合） |
| M2 | `backend/api/ws.py:165-166` | **裸 `except Exception: pass` 吞异常**：`_push_progress_updates` 每秒循环内任何异常被静默吞掉 | 广播通道故障无任何可观测性，排查困难 |
| M3 | `frontend/src-tauri/tauri.conf.json:29` | **CSP 显式关闭（`"csp": null`）**。前端无活跃 XSS 注入点，但一旦未来引入富文本/外链渲染，WebView 内脚本无任何兜底，可滥用 `open_link`/`play_wav_sound`/`log_ws_diag` 等本地能力 | 纵深防御缺失，XSS 一旦出现即升级为本地能力滥用 |
| M4 | `frontend/src-tauri/capabilities/default.json:26` | **`websocket:default` 无 URL 作用域**（`allow-connect` 无预置 scope，capability 也未配置），WebView JS 可连接任意 WebSocket 端点；`window-state:allow-restore-state` 恢复 VISIBLE/FULLSCREEN 标志 | 注入代码后可外连任意端点做信息外带；窗口钓鱼放大面 |
| M5 | `backend/api/config.py:100-101`、`frontend/src/lib/sound.ts:126-136` | **`custom_sound_url` 无协议/扩展名校验**：`new Audio(url)` 会对配置的内网/元数据地址发起客户端请求（客户端请求伪造），`play_wav_sound` 直通任意本地路径 | 配置被污染时探测内网端口、命中云元数据地址；非经典 SSRF（无服务端代拉、响应不可读回），但应校验 |
| M6 | `requirements.txt` / `requirements-dev.txt` | **依赖完全无版本锁定**（`fastapi>=0.115` 等裸下限；dev 依赖 `ruff`/`black`/`pytest` 完全裸奔） | 供应链漂移、构建不可复现、CI 与本地环境不一致风险 |
| M7 | `downloader/downloader.py:255-271` | **文件扩展名取自 URL 后缀且无白名单**（`len(suffix)<=5` 即采用） | 与 H1 组合构成任意文件写原语；独立看是防御纵深缺口 |
| M8 | `installer.iss:50,73` vs `tauri.conf.json:47` | **两套安装器策略冲突**：Inno 脚本要求管理员（`{autopf}`），Tauri NSIS 用 `currentUser`。另有 `[Languages]` 重复定义 `english` | 权限模型不一致，文档与产物行为分裂 |
| M9 | `crawlers/url_parser.py:147-151,269-298` | **域名白名单可用 `userinfo@` 语法绕过，且抖音短链跳转未复检落地域名**（F1）。`_is_douyin_url` 用 `split(":")[0]` 提取 host：`https://v.douyin.com:443@evil.com/x` 可通过白名单，随后 `follow_redirect` 对 `evil.com` 发起真实请求；`Location` 落地 URL 也不校验（B 站版 `bili_url_parser.py:302` 用 `urlparse(...).hostname` 复检，两处不一致） | 构造特制 URL 可令 sidecar 向任意 https 主机发起请求（有限 SSRF：http/https、不带 Cookie、响应不反射）；影响面有限但真实存在 |
| M10 | `downloader/downloader.py:361-363,1219-1272` | **B 站 DASH 直链过期（403）无重解析机制**（B3）。`_should_retry` 对 4xx（非 461/412）一律不重试；图集重解析仅针对抖音 image_set；`url/audio_url` 落库跨会话复用过期 URL | 隔天续传/订阅任务的 B 站视频大面积失败，失败信息仅"HTTP 403" |
| M11 | `crawlers/user_home_crawler.py:350-430`、`crawlers/bilibili/bili_user_crawler.py:193-256` | **分页循环无请求间隔/速率限制**（D3）。信号量只限制并发数，不限制单位时间请求率；翻页间隔仅依赖网络 RTT，配合 Cookie 池轮换仍属高频脉冲 | 触发抖音 461/412、B 站 -412 封号/风控风险；Cookie 池熔断只能事后止损 |
| M12 | `crawlers/signer/abogus.py:46-53`、`crawlers/signer/xbogus.py:36`、`crawlers/signer/__init__.py:116-126` | **签名环境指纹固定 + 固定参数与真实服务端一致性无端到端验证**（A1/A4）。`_ENV_FINGERPRINT`/`_CANVAS_CODE` 为固定常量，全部流量可聚类识别；`Chrome/120 + version_code=170400` 等固定参数过期即全链路 461/412 | 抖音算法轮换是本项目最现实的功能失效点，且无法通过 CI 提前感知 |
| M13 | `downloader/downloader.py:918-971`（全仓无 m3u8/AES） | **HLS/m3u8/AES-128 协议兼容缺口，且失败模式是静默损坏**（C1）。下载器是纯字节流下载，Content-Type 异常仅 `logger.warning` 不中止 → 若拿到 m3u8 播放列表会把**文本当媒体文件保存**（扩展名判成 `.m3u8`） | 协议兼容短板；一旦平台对部分内容强制 HLS，用户得到"看似成功实则损坏"的文件 |

### 🟡 建议

| # | 位置 | 问题 |
|---|------|------|
| S1 | `crawlers/bilibili/bili_url_parser.py:285-309` | b23.tv 短链 `follow_redirects=True` 先由 httpx 跟随（可能已访问中间跳转主机）再校验最终 host，存在先请求后校验窗口 |
| S2 | `downloader/downloader.py:733-753` | ffmpeg 合并无超时（`proc.communicate()` 无限等待），ffmpeg 挂起会永久卡死任务 |
| S3 | `backend/api/download.py:352-384` | 删除任务/任务项仅删数据库行，**不清理磁盘上的 `.part`/成品文件**；孤儿 `.part` 文件无启动清理机制，磁盘垃圾累积 |
| S4 | `crawlers/bilibili/bili_video_parser.py:306-314,347,365` | 会员清晰度（qn=112/120）无会员 Cookie 时返回 -403 不做降级重试；`backup_url` 空列表回退 `""`、空流不跳过 |
| S5 | `frontend/src-tauri/tauri.conf.json` / CI | 无 `cargo audit` / `npm audit` / bandit / gitleaks 门禁；版本号提交历史不一致（commit 标注 v0.5.0 而版本文件为 v0.4.1） |
| S6 | `README.md:11` | README 自述"抖音数据抓取"但已支持 B 站，宣传文案滞后；免责/合理使用提示主要在 THIRD-PARTY-NOTICES，README 应显式补充 |
| S7 | `crawlers/bilibili/bili_signer.py:256-261`、`crawlers/signer/*` | buvid3 用 `random` 而非 `secrets`（A5，仅影响风控关联性）；xbogus/abogus 魔数数组缺逐字节布局注释、`_double_md5`/RC4 重复实现（A3，维护成本）；`_RC4` 位置 `xbogus.py:121-168` |
| S8 | `crawlers/video_parser.py:538`、`user_home_crawler.py:368,402`、`cookie_tester.py:192` | 防御性 `int(status_code or 0)` 遇非数字字符串抛未捕获 ValueError（D4），应统一 `_safe_int` |
| S9 | `tests/data/known_signer_vectors.json` | 测试向量是"实现自洽"回归（README 声明独立生成），算法逆向有误时测试永远通过（G1）；建议补充与第三方公开实现的交叉验证向量 |
| S10 | `crawlers/bilibili/bili_signer.py:101` | `WBI_KEY_CACHE_TTL=86400` 偏长，B 站轮换密钥时可缩短至 12h（B4） |

---

## 2. 架构设计与代码质量

### 2.1 模块分层：总体清晰，扩展性欠奉（未严格满足开闭原则）

分层是健康的：

```
frontend (React/TS) ── REST/WS ──> backend/api (FastAPI 路由)
                                      │
                    backend/state.ctx（全局装配）＋ backend/services（订阅扫描器）
                                      │
          crawlers/{url_parser, video_parser, user_home_crawler, http_client, signer}
          crawlers/bilibili/{bili_*_parser, bili_http_client, bili_signer}   ← 平台子包
                                      │
          downloader/{scheduler, downloader, progress_reporter, constants}
                                      │
          app/{config, database, models, repositories, logger}                ← 数据层
```

**问题（不满足开闭原则）**：新增平台需要改动至少 5 处，且存在硬编码平台特判：

1. `backend/app.py:96-109`：每个平台组件在 lifespan 中**逐个手动 import 并装配**（抖音 7 个组件、B 站 4 个组件各写一段）。
2. `downloader/downloader.py:396-424`：`_is_bilibili_item()` 通过 `task_item.bvid or task_item.audio_url` 字段**特判平台**决定 Referer；DASH 合并逻辑 `_download_dash` 也是平台强耦合。
3. `backend/api/download.py:149-190`：`item_type == "image_set"`、`bvid/cid/audio_url` 透传等平台语义硬编码在通用入队逻辑里。
4. `backend/api/bilibili.py` 与 `backend/api/crawler.py`：抖音与 B 站各有一套解析/主页/播放流路由，接口契约不统一（如 `ParsedURLResponse` vs `BiliParseResult`）。
5. `downloader/constants.py`、`crawlers/api_spec.py`：常量跨层 import（crawlers 反向依赖 downloader.constants），依赖方向有倒挂。

**结论**：作为 v0.4 双平台状态可接受，但第三个平台（小红书/YouTube）接入时，这些特判会成为维护泥潭。演进方案见 §6。

### 2.2 错误处理：整体优秀，个别裸 catch-all

做得好的：
- 异常层次完整（`crawlers/exceptions.py`：CookieInvalidError / RateLimitedError / VerifyRequiredError / NetworkError / SignError…），HTTP 461/412/429 有专门分类与优雅降级。
- 重试策略完善：指数退避 2^retry（`downloader/downloader.py:365-373`、`crawlers/http_client.py:273-322`）、尊重 `Retry-After`（`http_client.py:332-348`）、Cookie 池失效自动切换（`http_client.py:350-382`）、重试上限 3 次；461/412/验证页**不**盲目重试。
- B 站侧 `BiliHttpClient._handle_response`（403→CookieInvalid、412→RateLimited）分类正确；`BiliSigner.get_raw` 签名失败自动刷新密钥重签（`bili_http_client.py:145-152`，自愈闭环）。
- `crawlers/` 目录**无任何裸 `except: pass`**（经全仓检索确认）。

问题点：
- **M2**：`backend/api/ws.py:165-166` `except Exception: pass`（每秒循环）。
- `backend/api/crawler.py:145-147`（下载入队二次解析失败 `except Exception: pass`，失败信息直接丢失）。
- `backend/app.py:127,144,162,180,214`：WS 广播回调全部 `except Exception: log.exception`——有日志可接受。
- `sidecar_launcher.py:27` `except Exception: pass`（stdin 监视线程，刻意为之，可接受）。

### 2.3 并发与资源管理：受控良好，清理机制有缺口

做得好的：
- 全局并发信号量（`scheduler.py:108`，clamp 1–10）、分片信号量（`downloader.py:556`）、解析信号量（`crawler.py:22`、`bilibili.py:198`）三重限流。
- 进度节流器（`progress_reporter.py`，500ms 批量上报）避免高频回调；SQLite 进度持久化按 5s/1MB 节流。
- DASH 合并的临时流文件在 `finally` 中保证清理（`downloader.py:840-844`）；分片失败/回退时清理 `.part.{i}`（`downloader.py:583-599`）。
- 图集并发下载共享同一信号量；同名目标文件/目录有 per-path asyncio.Lock 防并发写冲突（`downloader.py:164,652-684`）。
- `_stream_to_file` 捕获 CancelledError 时持久化进度后重抛（`downloader.py:1065-1068`），暂停/恢复语义正确。

问题点：**S3** —— `.part` 与成品文件在"任务删除""永久失败"后无清理策略，长期使用磁盘垃圾累积；ffmpeg 合并无超时（S2）；分页无速率控制（M11）。

---

## 3. 核心功能与流媒体健壮性

### 3.1 协议兼容

- **抖音**：web API（aweme detail / user post list）+ 无水印直链下载，`curl_cffi impersonate="chrome"` 伪造 TLS 指纹绕过 Janus 风控（`http_client.py:157-162`），XBogus/ABogus/msToken/verifyFp 四合一签名（`signer/__init__.py:70-138`）。当前链路健壮。
- **B 站**：VIEW + PLAYURL（`fnval=4048` 请求 DASH/4K/HDR）→ DASH 音视频流分离下载 → ffmpeg `-c copy` 合并（`downloader.py:711-753`）。WBI 签名实现正确（密钥 24h 缓存、MD5 签名、`!'()*` 过滤），buvid3/4 指纹生成。
- **未覆盖 HLS/m3u8（M13）**：项目**完全没有 m3u8/MPD 解析器**（全仓 `m3u8|HLS|AES|crypto` 检索零匹配）。当前平台不依赖 m3u8 故无功能缺陷，但：
  1. 一旦接入使用 HLS 的站点（大量短视频站/直播回放用 HLS + AES-128 分段加密），需从零实现分段下载、`#EXT-X-KEY` AES-128 CBC 解密、动态 header 续传；
  2. 更紧迫的是**失败模式**：下载器是纯字节流下载，对 Content-Type 异常仅 `logger.warning` 不中止——若拿到 m3u8 文本会把播放列表当媒体保存（扩展名被 `_extract_extension` 判成 `.m3u8`），产生"看似成功实则损坏"的静默错误。**最低限度应检测播放列表文本并中止报错**（修复见 §5.10）。
- **防盗链**：B 站 CDN 强制 Referer（`downloader.py:422-424` 处理正确，有测试覆盖）；抖音 CDN 需 UA/Referer（`scheduler.py:50-57`）；封面代理带浏览器 UA + B 站 Referer；Referer 全部为硬编码常量，**不存在"从用户 URL 提取 host 拼 Referer/BaseUrl"的反模式**（正面）；DASH 流 URL 由服务端签发（含签名参数原样透传），行为正确。

### 3.2 音视频合并（FFmpeg）

- **入参规范**：`asyncio.create_subprocess_exec` 参数数组（无 shell、无命令注入），`-c copy` 流拷贝不重编码（`downloader.py:733-747`）。
- **FFmpeg 缺失检测**：`_find_ffmpeg()` 按 注入路径 → `resources/ffmpeg/ffmpeg.exe` → `shutil.which("ffmpeg")` 三级查找；找不到抛 `RuntimeError("未找到 ffmpeg…")` 并标记任务失败（`downloader.py:688-729`）；README 有完整安装引导。**缺兜底方案**：无"仅下载音视频流不合并"的降级选项（用户无法在无 ffmpeg 时先拿到音视频流）。
- **缺口**：合并无超时（S2）；失败后无自动换码（`-c copy` 对部分 m4s 容器不兼容时无 fallback 到重编码）；B 站 DASH 直链过期无重解析（M10）。

### 3.3 防封禁与反爬适配

- 频率控制：爬虫侧 3 并发信号量 + 指数退避；B 站批量解析 5 并发上限（`bilibili.py:22`）。**缺单位时间速率限制（M11）**：主页抓取分页循环无请求间隔，高 max_items 主页抓取仍可能触发风控。
- Cookie/Session 生命周期：Cookie 池（valid 轮询最久未用、fail_count≥3 置 invalid、461/412 自动切换、全池失效抛异常）实现成熟（`http_client.py:386-456`）。
- 动态加密参数反混淆：`crawlers/signer/`（xbogus/abogus）是**纯逆向魔数实现**，维护成本集中在"抖音改算法就要重逆向"（A3），但模块边界清晰（`Signer` 组合四个子算法，失效时替换子模块，调用方无需改动），测试向量独立生成有据可查。**最大风险不是算法错而是算法过期且无自动感知（A4）**：固定参数（Chrome/120、version_code=170400、固定 env 指纹）与真实服务端一致性没有任何端到端验证，抖音任何一次前端升级都可能让全部请求 461/412，且 CI 无法提前发现（修复见 §5.11）。

---

## 4. 安全性审查（关键）

### 4.1 命令注入 —— ✅ 未发现

全仓 `subprocess`/`spawn`/`exec` 调用均为参数数组形式：

- ffmpeg：`asyncio.create_subprocess_exec(ffmpeg, "-y", "-i", str(video_path), …)`（`downloader.py:733-747`）——无 shell、无字符串拼接。
- sidecar：Rust `app.shell().sidecar("backend-sidecar").args(["--host","127.0.0.1","--port","18989"]).spawn()`，固定参数数组；`externalBin` 白名单仅含 backend-sidecar。
- 文件名虽由"作者-标题"拼接，但 `_build_base_name` 清洗了 `<>:"/\|?*` 与控制字符（`downloader.py:234-239`）且有单测覆盖——即使拼进参数数组也无注入面。

### 4.2 SSRF 与任意文件覆盖

- **covers 代理**：三层防护（协议白名单 + 主机前缀黑名单 `covers.py:43-75` + 连接阶段解析 IP 再校验 `_SSRFGuardTransport` + `follow_redirects=False` + 20MB 上限 + Content-Type 白名单），**已优于绝大多数同类实现**。残余问题 M1（同步 getaddrinfo 阻塞事件循环 + TOCTOU）。
- **H1（核心风险）**：`POST /api/download/start` 的 `items[].no_watermark_url` 与 `download_dir` **完全无校验**，下载器 httpx 客户端 `follow_redirects=True`（`scheduler.py:113`）且无 SSRF guard（与 covers 的严谨形成反差）。攻击面：
  1. 本机任意进程直接调用（sidecar 无鉴权）；
  2. 浏览器侧经 DNS rebinding（攻击者域名 → 127.0.0.1）绕过 CORS 后，任意网页可读 Cookie、写任意路径文件（扩展名由 URL 后缀决定，可 `.bat`/`.url`/`.exe`）。
- **M9（域名白名单绕过）**：`url_parser.py:147-151` 用 `host_match.group(1).split(":")[0]` 提取 host，`https://v.douyin.com:443@evil.com/x` 可通过白名单（urlparse 解析出的真实 host 是 evil.com），随后对 evil.com 发起请求；`follow_redirect` 对 Location 落地 URL 也不复检（B 站版有复检，两处不一致）。
- **B 站短链**：有落地域名白名单，但先请求后校验（S1，httpx 已跟随再检查 `resp.url`）。

### 4.3 凭据泄漏

- **硬编码凭据：✅ 未发现**。全仓扫描（`api_key|secret|token|password|SESSDATA|authorization` 等模式）零命中；`.env.example` 仅占位符；`.gitignore` 覆盖 `.env`/`*.db`/sidecar 二进制。
- **Cookie 明文存储（H3）**：抖音登录 Cookie 与 B 站 Cookie 明文落盘 SQLite（`%APPDATA%/VideoGetTool/data.db` + WAL 副本），无任何加密（全仓 crypto/DPAPI 检索零匹配）。`%APPDATA%` 默认 ACL 允许同账号下所有进程读取，备份/同步工具常同步该目录。
- 测试向量 `tests/data/known_signer_vectors.json`：仅合成输入（假 aweme_id、公开 UA、固定时间戳），**不含真实敏感数据**（正面，但见 S9 自洽性问题）。

### 4.4 其他

- SQL 注入：全仓参数化查询，动态 SET 子句来自白名单字段（`repositories.py:810-839`），✅。
- 日志注入：`log_ws_diag` 将任意字符串写入日志（低危）。
- 前端 XSS：全量检索 `frontend/src/**` 无 `dangerouslySetInnerHTML`/`innerHTML`/`eval`/`new Function`；所有封面/预览图统一经 covers 代理 `<img src>`；Toast/通知文案纯文本。**当前无活跃 XSS 注入点**（M3 是纵深防御缺口而非现役漏洞）。

---

## 5. 代码级修改方案（核心问题）

### 5.1 H1/H2 修复：sidecar 鉴权 + Host 校验 + WebSocket Origin 校验

**问题分析**：sidecar 是"本地可信服务"模型，但信任边界仅靠 CORS（浏览器机制，防不住 DNS rebinding 与本机进程）。最小修复 = 三层：① 校验 `Host` 头必须为 127.0.0.1:18989；② WebSocket 校验 `Origin`；③ 下载入队时对 `download_dir` 规范化并限定在允许目录内、扩展名白名单。

**修改前（backend/app.py:272-284）**：
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**修改后（新增 Host 校验中间件）**：
```python
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

ALLOWED_HOSTS = {"127.0.0.1:18989", "localhost:18989"}

class HostGuardMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.headers.get("host", "") not in ALLOWED_HOSTS:
            return JSONResponse(status_code=403, content={"detail": "host not allowed"})
        return await call_next(request)

app.add_middleware(HostGuardMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```
> 更彻底：壳启动时生成随机 token（Rust `rand`）→ 环境变量传给 sidecar → 所有请求要求 `Authorization: Bearer <token>`（前端经 `invoke` 获取），彻底摆脱对 CORS/Host 的依赖（见 §6 演进 2）。

**修改前（backend/api/ws.py:82-89）**：
```python
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
```

**修改后（Origin 白名单 + 连接数上限）**：
```python
_MAX_WS_CONNECTIONS = 16
_WS_ALLOWED_ORIGINS = {"tauri://localhost", "http://tauri.localhost", "http://localhost:1420"}

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    if ws.headers.get("origin", "") not in _WS_ALLOWED_ORIGINS:
        await ws.close(code=1008, reason="origin not allowed")
        return
    if manager.active_count >= _MAX_WS_CONNECTIONS:
        await ws.close(code=1013, reason="too many connections")
        return
    await manager.connect(ws)
```

**修改前（backend/api/download.py:104-113，download_dir 直通）**：
```python
download_dir = download_dir or ctx.config_repo.get("download_dir") or ""
```

**修改后（规范化 + 白名单约束）**：
```python
import os
from pathlib import Path

download_dir = download_dir or ctx.config_repo.get("download_dir") or ""
if download_dir:
    p = Path(os.path.abspath(download_dir))
    allowed_root = Path(os.path.abspath(ctx.config_repo.get("download_dir") or ""))
    if not (str(p) == str(allowed_root) or allowed_root in p.parents):
        raise HTTPException(status_code=400, detail="download_dir 不在允许目录内")
```

**修改前（downloader/downloader.py:255-271，URL 后缀直用）**：
```python
suffix = Path(parsed.path).suffix.lower()
if suffix and len(suffix) <= 5:
    return suffix
```

**修改后（扩展名白名单）**：
```python
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".flv", ".ts", ".m4s",
                       ".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}

suffix = Path(parsed.path).suffix.lower()
if suffix in _ALLOWED_EXTENSIONS:
    return suffix
```

### 5.2 M1 修复：covers SSRF guard 异步化 + 闭合 TOCTOU

**问题分析**：`socket.getaddrinfo` 同步阻塞事件循环；且校验与建连是两次独立解析。

**修改前（backend/api/covers.py:133-145）**：
```python
async def handle_async_request(self, request):
    host = request.url.host
    if host:
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        try:
            addrinfos = socket.getaddrinfo(host, port)
        except OSError as exc:
            raise httpx.ConnectError(...)
        for info in addrinfos:
            ip = info[4][0]
            if _is_blocked_ip(ip):
                raise httpx.ConnectError(f"blocked target ip {ip} for host {host}")
    return await super().handle_async_request(request)
```

**修改后（异步解析 + 连接钉在已校验 IP）**：
```python
async def handle_async_request(self, request):
    host = request.url.host
    if host:
        loop = asyncio.get_running_loop()
        port = request.url.port or (443 if request.url.scheme == "https" else 80)
        try:
            addrinfos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise httpx.ConnectError(f"DNS resolution failed for {host}: {exc}") from exc
        if not addrinfos:
            raise httpx.ConnectError(f"no address for {host}")
        ips = [info[4][0] for info in addrinfos]
        if any(_is_blocked_ip(ip) for ip in ips):
            raise httpx.ConnectError(f"blocked target ip for host {host}")
        # 闭合 TOCTOU：将连接目标钉在已校验 IP，Host 头保留原域名
        request = request.copy()
        request.url = request.url.copy_with(host=ips[0])
        request.headers["Host"] = host
    return await super().handle_async_request(request)
```
> 说明：钉 IP 方案在 HTTPS 下需保持 SNI/Host；若 CDN 域名多 IP（抖音/B 站 CDN 常态），可退化为"异步解析 + 校验 + 放行"（已显著优于现状）。

### 5.3 M9 修复：URL 解析 hostname 提取与落地域名复检

**问题分析**：`split(":")[0]` 可被 `userinfo@` 绕过；抖音短链落地 URL 不复检。

**修改前（crawlers/url_parser.py:147-151 与 269-298）**：
```python
host = host_match.group(1).split(":")[0]
return host in _DOUYIN_DOMAINS
...
# follow_redirect 内
location = response.headers.get("location")
if location:
    return location
```

**修改后（统一 urlparse + 落地域名复检）**：
```python
from urllib.parse import urlparse

@staticmethod
def _is_douyin_url(url: str) -> bool:
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    return host in _DOUYIN_DOMAINS
...
# follow_redirect 内
location = response.headers.get("location")
if location and self._is_douyin_url(location):
    return location
raise InvalidURLFormatError("短链重定向到非抖音域名，已拒绝")
```
> B 站侧同步：`bili_url_parser.py:302` 已用 `urlparse(...).hostname` 复检，保留即可。

### 5.4 M3 修复：启用 CSP

**修改前（frontend/src-tauri/tauri.conf.json:28-30）**：
```json
"security": { "csp": null }
```

**修改后**：
```json
"security": {
  "csp": "default-src 'self' http://tauri.localhost; connect-src 'self' http://127.0.0.1:18989 ws://127.0.0.1:18989; img-src 'self' http://127.0.0.1:18989 data:; style-src 'self' 'unsafe-inline'; script-src 'self'"
}
```

### 5.5 M4 修复：capabilities 收窄

**修改前（frontend/src-tauri/capabilities/default.json:26）**：
```json
"websocket:default",
```
**修改后（URL 作用域）**：
```json
{
  "identifier": "websocket:default",
  "allow": [{ "url": "ws://127.0.0.1:18989/**" }]
}
```
`window-state` 的 `StateFlags` 去掉 `VISIBLE | FULLSCREEN`（lib.rs:107-115），避免恢复窗口可见性/全屏。

### 5.6 M5 修复：custom_sound_url 校验

**修改前（backend/api/config.py:100-101）**：
```python
if req.custom_sound_url is not None:
    ctx.config_repo.set("custom_sound_url", req.custom_sound_url)
```

**修改后（协议/扩展名白名单）**：
```python
import re
if req.custom_sound_url is not None:
    value = req.custom_sound_url.strip()
    if value and not (
        re.match(r"^[A-Za-z]:[\\/].+\.(mp3|wav)$", value, re.I)
        or re.match(r"^https?://[^\s]+\.(mp3|wav)$", value, re.I)
    ):
        raise HTTPException(status_code=400, detail="custom_sound_url 格式不允许")
    ctx.config_repo.set("custom_sound_url", value)
```

### 5.7 M2 修复：移除裸 catch-all

**修改前（backend/api/ws.py:165-166）**：
```python
        except Exception:
            pass
```
**修改后**：
```python
        except Exception:
            logger.exception("共享进度推送循环异常")
```

### 5.8 M6 修复：依赖锁定

**修改前（requirements.txt）**：`fastapi>=0.115`、`httpx[http2]>=0.28` …
**修改后（精确锁定）**：
```text
fastapi==0.115.12
uvicorn==0.34.2
httpx[http2]==0.28.1
curl_cffi==0.16.0
Pillow==10.4.0
```
并为 dev 依赖生成 `requirements-dev.lock`（pip-tools）或统一 `uv lock`，CI 以锁文件安装。

### 5.9 H3 修复：Cookie 加密存储（DPAPI）

**问题分析**：登录 Cookie 即账号会话凭据，明文落盘 + WAL 副本 + `%APPDATA%` 可读。**不要**用项目内固定密钥做"混淆式加密"（密钥随源码分发等于没加密）。

**修改前（app/database.py:91-102 cookies 表明文 content）**：
```python
CREATE_COOKIES_SQL = """CREATE TABLE IF NOT EXISTS cookies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content TEXT NOT NULL, ...
)"""
```

**修改后（写时加密、读时解密；Windows DPAPI 或系统钥匙串）**：
```python
# app/crypto.py（新增，Windows DPAPI 封装）
import ctypes
from ctypes import wintypes

def _dpapi_protect(plain: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    # CryptProtectData: 仅当前 Windows 用户可解密，无需密钥管理
    ...

def encrypt_secret(plain: str) -> str:   # 返回 base64
    ...
def decrypt_secret(enc: str) -> str:
    ...

# repositories.py CookieRepository.add / get_all 中：
#   content = encrypt_secret(cookie.content)  # 写
#   content = decrypt_secret(row["content"])  # 读
```
> 非 Windows 开发环境回退：`keyring` 或提示不支持。同时建议：限制 `data.db*` 文件 ACL 为当前用户、提示用户 APPDATA 目录含敏感凭据。

### 5.10 M13 修复：下载前 m3u8 播放列表检测（最低限度）

**问题分析**：下载器对 Content-Type 异常仅 warning 不中止，播放列表文本会被当媒体保存。

**修改前（downloader/downloader.py:918-971 流式下载头部处理）**：
```python
async with self._http_client.stream("GET", url, headers=headers) as resp:
    ...
    # Content-Type 异常仅 logger.warning
```

**修改后（检测播放列表文本并中止）**：
```python
content_type = resp.headers.get("content-type", "").lower()
if "mpegurl" in content_type or "application/vnd.apple.mpegurl" in content_type:
    raise DownloadFailedError("目标为 HLS 播放列表(m3u8)，当前版本不支持，请等待格式支持")
```
完整方案（演进 3）：m3u8 解析 + `#EXT-X-KEY` AES-128 CBC 解密（pycryptodome）+ 分段并发下载 + ffmpeg 合并，与现有 DASH 共用下载原语。

### 5.11 M12/M11 修复：签名失效自动感知 + 请求速率控制

**修改前（无端到端验证、无速率限制）**：
- `crawlers/signer/__init__.py:70-138` 签名参数与真实服务端一致性无验证；
- `user_home_crawler.py:350-430` 分页循环无请求间隔。

**修改后**：
```python
# 1) 签名端到端冒烟测试（新增 tests/test_signer_live_smoke.py，integration marker）
#    用测试 Cookie 打一次 detail 接口，断言 status_code == 0；
#    失败即输出"签名参数已过期，请更新 version_code/UA/指纹常量"。
#    在 CI 定时任务（schedule）与每次发布前手动执行。

# 2) 最小请求间隔（crawlers/http_client.py 新增）
_async def _throttle(self):
    delay = random.uniform(0.3, 0.8)          # 300-800ms 抖动
    await asyncio.sleep(delay)
# 在 get() 每次实际发请求前调用；分页循环内同样生效。

# 3) 指纹随机化（A1，保持字节长度约束）
#    _ENV_FINGERPRINT 中分辨率/时区等可观测字段按真实环境随机化注入，
#    并将 version_code/UA 提升为集中配置，失效时无需改代码。
```

### 5.12 M10 修复：B 站 DASH 直链过期重解析

**修改前（downloader.py:361-363，4xx 一律不重试）**：
```python
if resp.status_code in RATE_LIMITED_STATUS_CODES:      # 461/412 才重试
    return True
return False
```

**修改后（B 站 403/404 走 playurl 重解析一次）**：
```python
# _download_dash 的 except 分支中：
except DownloadFailedError as exc:
    if task_item.bvid and task_item.cid and self._is_link_expired(str(exc)):
        new_urls = await self._reparse_bili_stream_urls(task_item)   # 重新 parse_playurl
        if new_urls:
            return await self._download_dash(task_item, *new_urls)   # 单次重试
    raise
```

---

## 6. 架构优化演进路线

### 演进 1：平台适配器化（Extractor 注册表）—— 解决开闭原则

将"平台"抽象为统一接口，终结 `bvid/audio_url` 字段特判与逐组件手工装配，**对齐 yt-dlp 的 extractor 模式**：

```python
# crawlers/registry.py（示意）
@dataclass
class PlatformAdapter:
    name: str
    url_parser: URLParser
    video_parser: VideoParser
    http_client: HTTPClient
    def match(self, task_item: TaskItem) -> bool: ...
    def referer(self) -> str: ...

REGISTRY: dict[str, PlatformAdapter] = {}
def register(adapter: PlatformAdapter) -> None: REGISTRY[adapter.name] = adapter
```

- `Downloader` 改为 `adapter = REGISTRY.get(task_item.platform)`，Referer/DASH 合并/分片策略从适配器读取，删掉 `_is_bilibili_item` 等硬编码分支。
- 入队逻辑按 `adapter` 统一处理 `image_set/audio_url` 语义；`backend/app.py` 的 lifespan 装配改为注册表 `register()` 一行。
- 新增平台 = 新目录 + `register()`，不动核心链路。同时统一抖音/B 站两套 REST 契约（`ParsedURLResponse` / `BiliParseResult`）为一个 `ParseResult` 模型。

### 演进 2：sidecar 安全边界正式化（token 握手 + 敏感数据加密）

- 壳启动时生成随机 token（Rust `rand`），经环境变量/启动参数传给 sidecar；所有 REST/WS 请求要求 `Authorization: Bearer <token>`（Tauri 前端经 `invoke` 取 token 注入），彻底摆脱 CORS/Host 依赖，H1/H2 从根上闭合。
- Cookie 落库用 Windows DPAPI（见 §5.9）加密；API 返回时前端侧解密或仅展示前缀。
- 本机多实例/端口冲突时 token 还天然隔离不同用户会话。

### 演进 3：流媒体协议扩展（HLS/DASH 通用解析器 + 合并兜底）

- 引入通用 HLS 解析器（m3u8 主/子清单、`#EXT-X-KEY` AES-128 解密、`#EXT-X-MAP` fMP4 init 段、动态 headers 继承），对齐 yt-dlp 的 `M3U8` 实现思路。
- 下载器抽出"流列表下载"原语（segment 列表 → 并发下载 → 本地 m3u8 重写 → ffmpeg 合并），与现有 DASH 双流合并共用。
- ffmpeg 合并增加超时与降级：`-c copy` 失败自动 fallback `-c:v libx264 -c:a aac` 重编码；无 ffmpeg 时提供"仅下载音视频流"选项。
- 签名失效自愈：把 A4 的端到端冒烟验证纳入 CI schedule，算法过期第一时间告警而非用户批量报 461。

---

## 7. 做得好的地方（正面结论）

1. **命令注入/SQL 注入/硬编码凭据：三项全绿**。所有系统调用参数数组化，全部 SQL 参数化（含表名白名单），全仓凭据扫描零命中。
2. **下载引擎工程质量高**：断点续传（Range + .part）、分片并发（上限 8）、指数退避重试、进度节流、per-path 锁防冲突、DASH 临时文件 finally 清理、暂停/恢复语义正确，且有完整单测（601 个测试函数 / 37 个文件，覆盖率 85.68%）。
3. **风控对抗体系完整**：TLS 指纹伪造、四合一签名、WBI 自愈刷新（sign 失败自动刷新密钥重签）、Cookie 池生命周期（轮询取用/熔断/全池失效）、461/412/429/验证页分类——反爬适配是加分项而非短板。
4. **covers 代理 SSRF 防护优于多数实现**（三层校验 + 不跟随重定向 + 大小上限 + Content-Type 白名单），说明安全基线意识在。
5. **合规与工程化**：Apache-2.0 迁移有完整说明、第三方归属清晰、B 站合规与 ffmpeg GPL 依赖声明到位；CI（ruff/black/pytest/tsc/构建）+ 发布流水线（版本一致性校验、产物校验）完整；`package-lock.json`/`Cargo.lock` 已入库；crawlers 层零裸 except；Cookie 值从不写日志。
6. **文件名清洗与 Windows 兼容**：非法字符清洗、长度截断、路径用 pathlib，均有测试；Referer 全为常量无"用户 URL 提取 host"反模式；ID 提取后仅作固定 API 参数、不改请求目标主机（SSRF 放大面有限）。

---

*本报告基于 v0.4.1 工作区全量源码只读审查（主代理 + 两个独立子代理交叉验证）；风险评级按【严重/高危/中危/建议】四档。未见"严重"级可直接利用的 RCE 链，但 H1/H2/H3 的组合攻击面（无鉴权本地 API + 任意文件写 + 明文凭据）是本项目当前最需优先治理的风险。*
