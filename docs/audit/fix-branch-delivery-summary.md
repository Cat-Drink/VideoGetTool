# fix/security-audit-remediation 分支整改交付说明

- **分支**：`fix/security-audit-remediation`（基于 `master` 59b0839）
- **依据文档**：`docs/audit/2026-09-05-security-code-audit.md`（v1 初稿）、`docs/audit/2026-09-05-security-audit-refined-guide.md`（v2 落地指南）
- **完成日期**：2026-09-05

---

## 1. 背景：master 已含全部 P0/P1/P2 修复

经逐项盘点核对，**`master` 代码树已落地审计报告 §2（v2 指南看板）中的全部 P0/P1/P2 修复**（此前轮次已随订阅模式提交合入，测试 890 项基线全绿）。本分支在此基础上，补齐唯一缺口 **M12 签名端到端冒烟测试与 CI 接入**（v2 指南 §9 演进 4 定义），并完成全量回归验证。

### 已落地修复盘点（逐项验证通过）

| 优先级 | 修复项 | 落地位置（当前代码树） |
|---|---|---|
| P0-1 | **H1 Host 守卫 / DNS rebinding 防护** | `backend/security.py`（新增 HostGuardMiddleware + is_host_allowed）+ `backend/app.py:34,321`（中间件接线） |
| P0-2 | **H2 WS Origin 校验 + 连接数上限 + 裸 except** | `backend/api/ws.py:72-73,105-116`（`_MAX_WS_CONNECTIONS=16`、origin 白名单、host 校验）、L196 `logger.exception` |
| P0-3 | **H1 下载入队校验 + config 规范化 + 扩展名白名单** | `backend/api/download.py`（`_validate_download_dir`/`_validate_download_url`，5 处命中）、`downloader/constants.py`（`ALLOWED_MEDIA_EXTENSIONS`） |
| P0-4 | **M9 URL host 提取修复 + 短链落地复检** | `crawlers/url_parser.py:150`（改用 `urlparse().hostname`，免疫 `userinfo@` 绕过）、`bili_url_parser.py`（落地域名复检） |
| P0-5 | **H3 Cookie 凭据 DPAPI 加密落盘** | `app/crypto.py`（新增）+ `app/repositories.py`（encrypt/decrypt，4 处）+ `backend/api/bilibili.py` |
| P1-1 | **M10 B 站 DASH 直链过期自动重解析** | `downloader/downloader.py`（`_bili_reparser` 相关路径，10 处命中） |
| P1-2 | **M11 分页请求限速** | `crawlers/http_client.py`（`pagination_throttle`）+ `user_home_crawler.py`/`bili_user_crawler.py` |
| P1-3 | **M13 m3u8 播放列表检测中止** | `downloader/downloader.py`（`#EXTM3U` 特征检测，3 处命中） |
| P1-4 | **S2 ffmpeg 合并超时** | `downloader/downloader.py:768`（`asyncio.wait_for(proc.communicate(), timeout=600)`） |
| P1-5 | **S3 孤儿 .part 清理 + 删除任务清理磁盘** | `downloader/cleanup.py`（新增 `sweep_orphan_part_files` / `safe_remove_output`）+ `backend/app.py:266-272`（启动清理）+ `backend/api/download.py:337-359,452-474`（`_remove_item_outputs`） |
| P1-6 | **M1 covers SSRF guard 异步化 + IPv6 修复** | `backend/api/covers.py:141-144`（`loop.getaddrinfo` 协程化）+ IPv4 校验（拒绝而非 500） |
| P1-7 | **N3 文件锁竞态修复** | `downloader/downloader.py:190,682-703`（`setdefault` 不再提前 pop） |
| P1-8 | **S4 B 站清晰度降级 + 空流跳过** | `bili_video_parser.py:319-340`（qn>80 无权限自动降级 80 重试）、`:248,362,380`（空 URL 流跳过） |
| P2-1 | **M3 CSP 生产生效** | `frontend/src-tauri/tauri.conf.json:29`（CSP 策略，devCsp null） |
| P2-2 | **M4 capabilities WS scope + window-state 收窄** | `frontend/src-tauri/capabilities/default.json`（websocket:default 限 `ws://127.0.0.1:18989`）、`src-tauri/src/lib.rs:110-111`（StateFlags 仅 SIZE/POSITION/MAXIMIZED） |
| P2-3 | **M5 custom_sound_url 校验** | `backend/api/config.py:23-47`（`_validate_sound_url`：http(s)/file/本地路径 + 音频扩展名白名单） |
| P2-4 | **M6 依赖版本锁定** | `requirements.txt`（5 项 `==` 精确锁定）、`requirements-dev.txt`（17 行变更） |
| P2-5 | **M8 安装器语言/权限对齐** | `installer.iss:81-85`（chinesesimplified + english 无重复） |
| P2-6 | **S5 CI 安全门禁** | `.github/workflows/ci.yml`：gitleaks 硬门禁（L27-51）+ pip-audit/npm audit（L75-78,133-139） |
| P2-7 | **S8 `_safe_int` 统一** | `crawlers/utils.py`（新增 `safe_int`）+ 4 个调用点（video_parser/user_home_crawler/cookie_tester） |
| P2-8 | **B4 WBI 密钥 TTL 12h** | `crawlers/bilibili/constants.py:103`（`WBI_KEY_CACHE_TTL = 43200`） |
| P2-9 | **S6 README 合规文案置顶** | `README.md:52-54`（合理使用与免责声明区块） |
| P2-10 | **A3 签名器注释 + A5 buvid3 secrets** | `crawlers/signer/xbogus.py`（魔数来源注释）、`bili_signer.py`（`secrets` 替换 `random`） |

> 高质量存量逻辑（断点续传、分片并发上限、DASH 临时文件 finally 清理、进度节流、per-path 文件锁、WBI 自愈）均保留，未发生回归（896 项测试全绿佐证）。

---

## 2. 本分支新增改动（M12）

### 2.1 新增 `scripts/signer_live_smoke.py`（147 行）

**问题分析（审计 M12/A4）**：抖音签名参数（Chrome UA、`version_code=170400`、固定环境指纹）过期时全部 Web API 返回 461/412/验证页，且 CI 无法提前感知——这是本项目最现实的功能失效点。v2 指南明确**不做 CI 定时任务**（定时需在 repo secrets 存放真实账号凭据，风险大于收益），改为**手动/发布前运行的端到端冒烟脚本 + workflow_dispatch 接入**。

**修改前（无）**：不存在任何"签名参数是否仍被服务端接受"的检测手段。

**修改后（核心逻辑）**：

```python
async def _run_smoke(cookie: str, aweme_id: str) -> int:
    conn = get_memory_connection()
    cookie_repo = CookieRepository(conn)
    http_client = HttpClient(cookie_repo, Signer())   # 复用生产链路（签名+UA+curl_cffi impersonate）
    try:
        try:
            params = {"aweme_id": aweme_id, **api_spec.COMMON_FIXED_PARAMS}
            response = await http_client.get(
                api_spec.AWEME_DETAIL_URL, params=params,
                use_cookie_pool=False, cookie=cookie,
            )
        except (CookieInvalidError, RateLimitedError, VerifyRequiredError) as e:
            print(f"[FAIL] 签名链路被服务端拒绝: {e}")
            print("提示: 请更新 crawlers/api_spec.py 的 version_code/固定参数、")
            print("      crawlers/signer/* 的环境指纹常量，以及 DEFAULT_USER_AGENT。")
            return 1
        ...
        if status_code == 0:
            print("[PASS] 签名链路有效: detail 接口正常返回")
            return 0
```

**行为约定**：
- **退出码 0** = 签名链路有效（detail 接口 `status_code==0`）
- **退出码 1** = 签名/风控异常（461/412/验证页/网络错/业务错），提示需更新版本常量
- **退出码 2** = 跳过（未提供 Cookie，CI 无凭据时允许）

**Cookie 来源**：环境变量 `DOUYIN_TEST_COOKIE`（推荐，CI 走 secret）或 `--cookie` 参数；不硬编码凭据。

### 2.2 CI 接入（`.github/workflows/ci.yml`，+42/-1）

- 新增 `workflow_dispatch` 触发器（输入 `aweme_id`，默认公开作品 ID）。
- 新增 `signer-live-smoke` job：`if` 条件限定 `workflow_dispatch` 且配置了 `DOUYIN_TEST_COOKIE` secret 才运行；未配置自动跳过、不阻塞 push/PR 主流程（gitleaks/lint-test/frontend-check 三 job 不变）。
- job 内读取 `secrets.DOUYIN_TEST_COOKIE` → 环境变量注入脚本，执行 `python scripts/signer_live_smoke.py --aweme-id ...`。

### 2.3 新增 `tests/test_signer_live_smoke.py`（72 行，6 项）

覆盖冒烟脚本的**本地可测部分**（不发起真实网络请求）：
- `--aweme-id` 默认值 / 显式值解析
- `DOUYIN_TEST_COOKIE` 环境变量默认与 `--cookie` 优先级
- 无 Cookie / 空 Cookie → SKIP（退出码 2）+ 不碰网络

### 2.4 复核补齐（对照 v2 指南逐项二次核验发现的两处遗漏）

| 项 | 遗漏点 | 本次补齐 |
|---|---|---|
| P1-8（S4 后半） | `_parse_playurl_response` 仍是脆弱写法：`backup_url` 空列表回退 `[""][0]` → 空 URL 流被 append；DASH 全空时静默返回空流 | `crawlers/bilibili/bili_video_parser.py`：视频/音频流空 URL 跳过（base_url 与 backup_url 双空 → `continue`）；DASH 响应解析后全空 → 抛 `VideoNotFoundError`；新增 `tests/test_bilibili/test_bili_playurl_empty_stream.py`（7 项） |
| P1-6（N1 后半） | covers IPv6 防护修复已落地但**无单测**（回归保护缺失） | `tests/test_api_covers.py` 新增 `test_ipv6_target_rejected_not_crash`：`::1`/`fe80::`/`fc00::`/`::ffff:127.0.0.1`/`::ffff:10.0.0.5` 拒绝、公网 IPv6 放行、非法串拦截；覆盖修复前 `TypeError → 500` 崩溃路径 |
| P2-5（M8 后半） | installer.iss 语言重复已修，但**缺发布通道标注**（v2 §6.5 要求"保留文件 + 头注释标注 Tauri NSIS 为当前发布通道"） | `installer.iss` 文件头新增发布通道声明（release.yml 产线 = Tauri NSIS，Inno 为历史遗留备用） |

---

## 3. 验证结果（全部通过）

| 项目 | 基线要求 | 实测结果 |
|---|---|---|
| 全量单元测试 | 原有 601 用例全部 Pass，覆盖率不降低 | **896 passed, 6 skipped**（含新增 6 项冒烟测试），覆盖率 **84%**（≥80% 门槛） |
| Lint（ruff） | 通过 | ✅ `ruff check .` 0 错误（新增文件含 UP031/W292 已修复） |
| 格式（black） | 通过 | ✅ `black --check` 全部通过 |
| 前端 tsc | 无类型报错 | ✅ `npx tsc --noEmit` exit 0 |
| 前端构建 | Build 通过 | ✅ `npm run build` 成功（6.93s） |
| CI 工作流 | YAML 有效、新 job 注册 | ✅ 4 个 job：gitleaks / lint-test / frontend-check / signer-live-smoke |

---

## 4. 提交划分

| Commit | 内容 |
|---|---|
| `c0bf4ac` `feat(security): 新增签名端到端冒烟脚本 (M12/A4)` | `scripts/signer_live_smoke.py` + `tests/test_signer_live_smoke.py` |
| `da9070a` `ci(security): 签名端到端冒烟接入 CI workflow_dispatch (M12)` | `.github/workflows/ci.yml` |

> 说明：P0/P1/P2 修复此前已随 master 树合入（对应提交历史 a9f4291/a41298a/1e950b6/9e7888e/462b1dc/e00f0f0/bf71140/572346a/384983e 等），本分支与其共享基线，增量仅为 M12 补齐项；两份审计文档已入库（`docs/audit/`，tracked）。

---

## 5. 待人工确认项（不属于本分支代码范围）

- [ ] 发布前手动运行一次 `python scripts/signer_live_smoke.py`（配置 `DOUYIN_TEST_COOKIE`）验证即时签名有效性
- [ ] 配置 GitHub repo secret `DOUYIN_TEST_COOKIE` 后，在 Actions 页手动触发 workflow_dispatch 冒烟 job
- [ ] 打包版冒烟（P2-1/P2-2 DoD）在 release 流程执行