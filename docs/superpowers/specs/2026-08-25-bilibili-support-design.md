# B 站（Bilibili）视频抓取支持方案设计

> 对应分支：`feat/bilibili-support`
> 文档日期：2026-08-25
> 状态：规划设计

---

## 1. 背景与目标

### 1.1 背景

VideoGetTool 目前仅支持**抖音（Douyin）**单一数据源。用户调研中收到大量"增加 B 站支持"的诉求。B 站（Bilibili）作为国内第二大视频平台，拥有丰富的长视频、番剧、UGC 内容生态，与抖音的短视频/图文形态形成互补。

### 1.2 目标

在 VideoGetTool 现有架构上，增量增加 B 站数据源支持，使产品具备**双平台内容抓取与下载**能力。

| 维度 | 目标 |
|---|---|
| **内容类型** | 单视频（含多 P）、用户主页投稿、视频合集/系列 |
| **画质** | 1080P 及以下（免费画质），预留 4K/8K 接口 |
| **下载格式** | MP4（DASH 音视频合并后输出） |
| **元数据** | 标题、作者、描述、播放量、弹幕数、发布时间、标签 |
| **交互** | 与抖音源共用同一套任务队列、下载引擎、Cookie 管理框架 |

### 1.3 非目标（本次规划不包含）

| 事项 | 说明 |
|---|---|
| 番剧/影视 | 版权保护严格，需大会员 Cookie，暂不纳入 V1 范围 |
| 直播录制 | 直播流与点播流差异大，需独立设计 |
| 弹幕下载与转换 | 弹幕 XML → ASS 转换属于独立 feature，可后续迭代 |
| 收藏夹/合集 | 需额外 API 对接，列为 V2 规划 |

---

## 2. 现有架构回顾

VideoGetTool 当前架构为：

```
┌──────────────────────────────────────────────────┐
│  Tauri + React 前端                              │
│  (BatchFetchPage / DownloadPage / CookiePage ...)  │
└───────────────┬──────────────────────────────────┘
                │ REST + WebSocket
┌───────────────▼──────────────────────────────────┐
│  Python FastAPI Sidecar                           │
│  backend/app.py  ─  lifespan 初始化                │
│  ├── backend/api/crawler.py   (Douyin 解析)       │
│  ├── backend/api/download.py  (下载任务)           │
│  ├── backend/api/cookie.py    (Cookie 管理)        │
│  ├── backend/api/config.py    (配置)               │
│  └── backend/api/ws.py        (WebSocket 推送)     │
│                                                    │
│  ┌─────────────┐  ┌──────────────────────────┐    │
│  │ crawlers/   │  │ downloader/               │    │
│  │ (Douyin 专用)│  │ Scheduler + Downloader    │    │
│  │ url_parser  │  │ (Range续传/.part/重试)     │    │
│  │ video_parser│  │                            │    │
│  │ signer/     │  └──────────────────────────┘    │
│  │ http_client │                                   │
│  │ user_home   │                                   │
│  └─────────────┘                                   │
│                                                    │
│  app/ (database.py / models.py / repositories.py)  │
│  SQLite (tasks / task_items / metadata / cookies)  │
└──────────────────────────────────────────────────┘
```

### 2.1 可复用的设计

| 组件 | 复用方式 | 备注 |
|---|---|---|
| **下载引擎** (Scheduler + Downloader) | ✅ 直接复用 | 下载核心逻辑与平台无关，仅需适配 B 站 DASH 格式 |
| **任务队列** (SQLite CRUD) | ✅ 直接复用 | source_type 字段区分来源 |
| **Cookie 管理** (CookieRepository) | ✅ 直接复用 | B 站 Cookie 存入同一张表，区分 source 标签 |
| **WebSocket 推送** (ws.py) | ✅ 直接复用 | 与来源无关 |
| **进度汇报** (ProgressReporter) | ✅ 直接复用 | 节流逻辑不变 |
| **前端下载页** (DownloadPage) | ✅ 小幅修改 | 增加来源列标识，其余复用 |
| **前端设置页** (SettingsPage) | ✅ 小幅修改 | 增加 B 站 Referer 配置 |

### 2.2 需要新增或修改的组件

| 组件 | 工作类型 | 说明 |
|---|---|---|
| **crawlers/bilibili/** | 🔴 新增 | 全新包，B 站专属爬虫 |
| **backend/api/bilibili.py** | 🔴 新增 | B 站解析/抓取 API 端点 |
| **backend/app.py** | 🟡 修改 | lifespan 中初始化 B 站模块 |
| **app/models.py** | 🟡 修改 | 增加 bvid / cid 字段 |
| **app/database.py** | 🟡 修改 | 迁移 schema 增加新字段 |
| **downloader/downloader.py** | 🟡 修改 | 增加 DASH 音视频合并步骤 |
| **frontend/src/pages/** | 🟡 修改 | 新增 B 站抓取页，修改现有页面 |
| **frontend/src/lib/api.ts** | 🟡 修改 | 增加 B 站 API 调用 |

---

## 3. B 站技术要点

### 3.1 核心概念对照

| 维度 | 抖音 (Douyin) | B 站 (Bilibili) |
|---|---|---|
| 视频标识 | `aweme_id` (数字) | `bvid` (BV1xx) / `aid` (av号，数字) |
| 多 P 支持 | 无 | 单视频可含多 P（`cid` 区分，P1, P2...） |
| 视频流格式 | 单 MP4 直链 | DASH 分离（video + audio 独立流） |
| 签名算法 | X-Bogus + A-Bogus + msToken + verifyFp | **WBI 签名**（w_rid = MD5(params + key) + wts） |
| 指纹参数 | `verify_fp` / `s_v_web_id` | **buvid3**（浏览器指纹 Cookie） |
| Cookie 角色 | 必须（几乎全部接口都需要） | 部分接口需要（HD 画质 / 大会员 / 投稿） |
| 风控强度 | 高（461/412/验证 HTML 频繁） | 中（主要限流 412，验证码较少） |
| Referer | `https://www.douyin.com/` | `https://www.bilibili.com/` |
| 视频 URL 有效期 | 短（几小时） | 较长（一天以上） |

### 3.2 B 站 API 关键端点

| 端点 | 用途 | 签名 | 备注 |
|---|---|---|---|
| `/x/web-interface/view?bvid=xxx` | 视频基本信息 | 无 | 标题、作者、统计、cid 列表 |
| `/x/player/wbi/playurl?bvid=xxx&cid=xxx` | 视频播放流地址 | WBI 签名 | 返回 DASH 流 multi_quality 或 dash |
| `/x/space/wbi/arc/search?mid=xxx` | 用户投稿列表 | WBI 签名 | 分页，含视频列表 |
| `/x/web-interface/wbi/index` | 获取 WBI key | 无 | 返回 img_key + sub_key |
| `/x/web-interface/nav` | 登录状态检测 | 无 | 用于 Cookie 测试 |
| `/x/relation/stat` | 用户关系统计 | 无 | 补充用户信息 |

### 3.3 WBI 签名算法

B 站 WBI 签名是替代旧版签名的新机制，必须在请求携带 `w_rid` 和 `wts` 参数：

```
1. 从 /x/web-interface/wbi/index 获取 img_key 和 sub_key
2. 拼接混合键: mix_key = sub_key[:4] + img_key[:4]
3. 按参数名 ASCII 升序排序所有参数
4. 拼接成 query string: "param1=val1&param2=val2"
5. 计算: w_rid = md5(query_string + mix_key)
6. 携带: wts = current_timestamp (unix 秒)
```

**注意**：img_key 和 sub_key 有缓存有效期（约一天），需定期刷新。

### 3.4 buvid3 指纹

buvid3 是 B 站用于识别客户端设备的指纹字符串，格式为：
```
buvid3=XXXX-YYYY-ZZZZ...infoc
```
生成后需写入 Cookie 并随请求发送。可从 `/x/web-interface/nav` 或 `/x/web-interface/bili_ticket` 获取/刷新。

---

## 4. 新增模块详细设计

### 4.1 crawlers/bilibili/ 包

```
crawlers/bilibili/
├── __init__.py              # 包入口，导出所有公开类
├── bili_signer.py           # WBI 签名 + buvid3 生成
├── bili_url_parser.py       # B 站链接解析
├── bili_video_parser.py     # 视频信息 + 播放流解析
├── bili_user_crawler.py     # 用户主页投稿抓取
├── bili_http_client.py      # B 站专用 HTTP 客户端（可选）
└── constants.py             # API 端点与常量
```

#### 4.1.1 bili_signer.py — WBI 签名

```python
class BiliSigner:
    """B 站 WBI 签名器。"""

    def __init__(self):
        self._img_key: str = ""
        self._sub_key: str = ""
        self._mix_key: str = ""
        self._key_expires_at: float = 0

    async def refresh_keys(self, http_client) -> None:
        """从 /x/web-interface/wbi/index 刷新密钥。"""

    def sign(self, params: dict) -> dict:
        """为参数字典追加 w_rid 和 wts。"""

    def generate_buvid3(self) -> str:
        """生成 buvid3 指纹字符串。"""
```

#### 4.1.2 bili_url_parser.py — 链接解析

支持的 URL 类型：

| 输入格式 | 示例 | 识别类型 |
|---|---|---|
| `bilibili.com/video/BV1GJ411x7/...` | 视频 | `video` |
| `b23.tv/xxxxx` | 短链 | 需 follow 302 → `video` |
| `space.bilibili.com/12345` | 用户主页 | `user_home` |
| `space.bilibili.com/12345/video` | 投稿列表 | `user_home` |
| `bilibili.com/medialist/play/...` | 合集/播放列表 | 暂不实现 |

```python
class BiliURLParser:
    """B 站链接解析器。"""

    async def parse(self, text: str) -> BiliParsedURL:
        """从文本中提取 B 站链接并识别类型。"""

    @staticmethod
    def extract_bvid(url: str) -> str | None:
        """从 URL 中提取 bvid (BV1...)。"""

    @staticmethod
    def extract_mid(url: str) -> str | None:
        """从空间主页 URL 提取 mid。"""
```

#### 4.1.3 bili_video_parser.py — 视频解析

分两步：先获取视频基本信息，再获取播放流地址。

```python
@dataclass(frozen=True)
class BiliVideoInfo:
    bvid: str
    aid: int
    title: str
    author: str
    author_mid: int
    cover_url: str
    duration: int          # 秒
    description: str
    tags: list[str]
    cid_list: list[int]    # 多 P 时每个分 P 的 cid
    pages: list[BiliPage]  # 分 P 信息
    stats: dict            # view / danmaku / reply / favorite / coin / share

@dataclass(frozen=True)
class BiliPage:
    """分 P 信息。"""
    cid: int
    title: str
    page: int
    duration: int

@dataclass(frozen=True)
class BiliPlayUrl:
    """播放流地址（DASH 或 MP4）。"""
    video_urls: list[str]  # DASH 视频流 URL
    audio_urls: list[str]  # DASH 音频流 URL
    quality: int           # 清晰度 80/64/32/16
    quality_name: str      # 4K/1080P/720P/360P
    dash: bool             # 是否 DASH 格式


class BiliVideoParser:
    def __init__(self, http_client, signer):
        ...

    async def parse_video(self, bvid: str) -> BiliVideoInfo:
        """调用 /x/web-interface/view 获取视频基本信息。"""

    async def parse_playurl(self, bvid: str, cid: int) -> BiliPlayUrl:
        """调用 /x/player/wbi/playurl 获取播放流（需 WBI 签名）。"""

    async def parse_all_pages(self, bvid: str) -> list[BiliVideoInfo]:
        """获取所有分 P 的播放流。"""
```

#### 4.1.4 bili_user_crawler.py — 用户主页抓取

```python
@dataclass(frozen=True)
class BiliPostItem:
    bvid: str
    title: str
    author: str
    cover_url: str
    duration: int
    view_count: int
    created_at: str
    type: str = "video"


class BiliUserCrawler:
    def __init__(self, http_client, signer):
        ...

    async def fetch_user_posts(
        self, mid: int, max_count: int = 50
    ) -> AsyncIterator[BiliPostItem]:
        """调用 /x/space/wbi/arc/search 分页获取用户投稿。"""
```

### 4.2 后端 API 扩展

#### 新增 `backend/api/bilibili.py`

| 端点 | 方法 | 请求体 | 响应 | 说明 |
|---|---|---|---|---|
| `/api/bilibili/parse` | POST | `{urls: string[], bilibili_cookie?: string}` | `BiliParseResult[]` | 解析 B 站链接 |
| `/api/bilibili/fetch-space` | POST | `{url: string, mid: int, max_count: int}` | `{items: BiliPostItem[], has_more: bool}` | 用户投稿抓取 |
| `/api/bilibili/playurl` | POST | `{bvid: string, cid: number}` | `BiliPlayUrl` | 获取播放流（前端下载时调用） |
| `/api/bilibili/cookie-test` | POST | `{cookie: string}` | `{valid: bool, nickname?: string}` | 测试 B 站 Cookie |

#### 修改 `backend/api/download.py`

在 `start_download` 中增加对 B 站来源的处理分支：
- 如果 `source_type` 是 `bilibili`，使用 `BiliVideoParser` 获取播放流
- 检查返回的 `BiliPlayUrl.dash`，如果是 DASH 格式则将 audio/video URL 对存入 task_item

### 4.3 数据库模型调整

#### 修改 `app/models.py`

```python
# 新增 SourceType 枚举值
class SourceType(StrEnum):
    SINGLE = "single"
    BATCH = "batch"
    USER_HOME = "user_home"
    FILE_IMPORT = "file_import"
    # 新增
    BILIBILI = "bilibili"
    BILIBILI_SPACE = "bilibili_space"

# 修改 TaskItem，增加 B 站特有字段
@dataclass
class TaskItem:
    # ... 现有字段不变
    bvid: str | None = None      # B 站视频 ID
    cid: int | None = None       # 分 P 的 cid（多 P 时区分）
    page: int = 0                 # 分 P 序号（0 表示不分 P）
    # 新增：DASH 合并相关
    audio_url: str | None = None  # DASH 音频流 URL
    dash_merged: bool = False     # 是否已完成 DASH 合并
```

#### 修改 `app/database.py`

Schema 迁移 v3 → v4：

```sql
ALTER TABLE task_items ADD COLUMN bvid TEXT DEFAULT '';
ALTER TABLE task_items ADD COLUMN cid INTEGER DEFAULT 0;
ALTER TABLE task_items ADD COLUMN page INTEGER DEFAULT 0;
ALTER TABLE task_items ADD COLUMN audio_url TEXT DEFAULT '';
ALTER TABLE task_items ADD COLUMN dash_merged INTEGER DEFAULT 0;
```

### 4.4 下载引擎适配

#### 4.4.1 DASH 音视频合并

B 站高质量视频（720P 以上）通常使用 DASH 格式，视频和音频流分开。下载器需要增加合并步骤：

```
现有下载流程（抖音）：
  请求 URL → 流式写入 .part → 重命名 .part 为最终文件

新增 DASH 流程（B 站）：
  请求 video_url → 流式写入 video.part
  请求 audio_url → 流式写入 audio.part
  两个 .part 都完成后 → ffmpeg -i video.part -i audio.part -c copy output.mp4
  删除两个 .part 文件
```

##### 修改 `downloader/downloader.py`

在 `Downloader` 中增加 `_download_dash` 方法：

```python
async def _download_dash(
    self, task_item: TaskItem, video_url: str, audio_url: str
) -> DownloadResult:
    """下载 DASH 音视频流并用 ffmpeg 合并。"""
    # 1. 并发下载 video 和 audio 流
    video_path = ...  # temp_video.part
    audio_path = ...  # temp_audio.part
    async with asyncio.TaskGroup() as tg:
        tg.create_task(self._download_single_file(task_item, video_url, video_path))
        tg.create_task(self._download_single_file(task_item, audio_url, audio_path))

    # 2. ffmpeg 合并
    output_path = ...  # 最终文件名 .mp4
    await self._merge_dash(video_path, audio_path, output_path)

    # 3. 清理临时文件
    video_path.unlink(missing_ok=True)
    audio_path.unlink(missing_ok=True)
    return DownloadResult(success=True, local_path=str(output_path))

async def _merge_dash(self, video_path: Path, audio_path: Path, output_path: Path) -> None:
    """调用 ffmpeg 合并音视频流。"""
    ffmpeg_path = self._find_ffmpeg()
    proc = await asyncio.create_subprocess_exec(
        str(ffmpeg_path),
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c", "copy",
        str(output_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()
    if proc.returncode != 0:
        raise DownloadError(f"ffmpeg 合并失败: 返回码 {proc.returncode}")
```

##### ffmpeg 查找策略

项目已有 `resources/ffmpeg/` 目录，但当前为空。需要：
1. 在发布包中捆绑 ffmpeg.exe（Windows）
2. 优先查找 `resources/ffmpeg/ffmpeg.exe`
3. 退枝到系统 PATH 中的 ffmpeg
4. 都找不到则报错提示用户安装

### 4.5 前端适配

#### 4.5.1 新增 B 站抓取页

新增 `frontend/src/pages/BiliFetchPage.tsx`，类似于现有的 `BatchFetchPage.tsx`，但针对 B 站：
- 支持输入 B 站视频链接（BV号）批量解析
- 支持输入 UP 主空间链接抓取投稿列表
- 展示解析结果列表（封面、标题、UP主、播放量、时长）
- 多 P 视频显示"共 N 集"并支持选择哪些 P 下载
- 选择下载目录后加入下载队列

#### 4.5.2 修改现有页面

| 页面 | 修改内容 |
|---|---|
| `DownloadPage.tsx` | 任务项增加来源标识列（B站/抖音）；DASH 合并中状态显示 |
| `NavBar.tsx` | 增加"B站抓取"导航项 |
| `AppShell.tsx` | 注册 B 站抓取页路由 |
| `CookiePage.tsx` | 增加"B站 Cookie"标签页或来源选择器 |
| `SettingsPage.tsx` | 增加 B 站下载 Referer 配置（默认 `https://www.bilibili.com/`） |

#### 4.5.3 修改 API 层

`frontend/src/lib/api.ts` 新增：

```typescript
// B 站解析结果
export interface BiliParseResult {
  url: string;
  bvid: string;
  title: string;
  author: string;
  cover_url: string;
  duration: number;
  pages: { cid: number; title: string; page: number; duration: number }[];
  view_count: number;
  danmaku_count: number;
  publish_time: string;
  tags: string[];
  error?: string;
}

export async function biliParseUrls(urls: string[]): Promise<BiliParseResult[]> {
  return request("/bilibili/parse", { method: "POST", body: JSON.stringify({ urls }) });
}

export async function biliFetchSpace(mid: number, maxCount: number = 50): Promise<...> {
  return request("/bilibili/fetch-space", { method: "POST", body: JSON.stringify({ mid, max_count: maxCount }) });
}
```

---

## 5. 分阶段实施计划

### 阶段一：核心爬虫与链接解析（预计 3-4 天）

| 任务 | 产出 | 依赖 |
|---|---|---|
| 1.1 实现 `bili_signer.py`（WBI 签名 + buvid3） | 通过签名测试 | 无 |
| 1.2 实现 `bili_url_parser.py`（链接解析） | 正确解析 BV 号/mid | 1.1 |
| 1.3 实现 `bili_video_parser.py` 视频信息部分 | 获取标题、作者、分 P 列表 | 1.1, 1.2 |
| 1.4 实现 `bili_http_client.py`（B 站 HTTP 封装） | 可发起已签名请求 | 1.1 |
| 1.5 后端 API `/api/bilibili/parse` | 前端可调通解析接口 | 1.2, 1.3, 1.4 |

**验收标准**：输入 `https://www.bilibili.com/video/BV1GJ411x7/` 返回正确标题、作者、分 P 列表。

### 阶段二：播放流解析与下载（预计 3-4 天）

| 任务 | 产出 | 依赖 |
|---|---|---|
| 2.1 实现 `bili_video_parser.py` playurl 部分 | 获取 DASH 视频/音频流 | 1.1, 1.4 |
| 2.2 下载器 DASH 合并支持（`_download_dash`） | 下载视频+音频→ffmpeg→MP4 | 2.1 |
| 2.3 ffmpeg 捆绑与查找策略 | 安装包中含 ffmpeg | 2.2 |
| 2.4 数据库迁移（bvid/cid/audio_url 字段） | schema v4 | 2.2 |
| 2.5 后端 `/api/bilibili/playurl` + 下载 API 适配 | 端到端下载 | 2.1-2.4 |

**验收标准**：粘贴 BV 号 → 解析 → 加入下载 → 下载完成输出 MP4（含声音）。

### 阶段三：用户主页抓取（预计 2 天）

| 任务 | 产出 | 依赖 |
|---|---|---|
| 3.1 实现 `bili_user_crawler.py`（空间投稿列表） | 分页获取 UP 主投稿 | 1.1, 1.4 |
| 3.2 后端 `/api/bilibili/fetch-space` | 前端可调通 | 3.1 |
| 3.3 Cookie 测试（`/x/web-interface/nav`） | B 站 Cookie 管理 | 1.4 |

**验收标准**：输入 `space.bilibili.com/12345` → 返回投稿列表 → 批量加下载 → 全部下载成功。

### 阶段四：前端完善（预计 3 天）

| 任务 | 产出 | 依赖 |
|---|---|---|
| 4.1 新增 `BiliFetchPage.tsx` | B 站视频解析+抓取页面 | 阶段一、二 |
| 4.2 导航栏与路由注册 | 可访问 B 站页面 | 4.1 |
| 4.3 `CookiePage.tsx` 增加 B 站 Cookie 支持 | 可管理 B 站 Cookie | 阶段三 |
| 4.4 `DownloadPage.tsx` 增加来源标识 | 任务列表区分来源 | 4.1 |
| 4.5 前端 API 层（`api.ts`）扩展 | 前端可调用 B 站接口 | 阶段一、二 |

**验收标准**：完整流程：打开 B 站页面 → 输入链接 → 解析 → 选择 → 下载 → 播放。

### 阶段五：集成测试与发布（预计 2 天）

| 任务 | 产出 | 依赖 |
|---|---|---|
| 5.1 后端单元测试（B 站模块） | 测试覆盖率 ≥ 80% | 阶段一、二、三 |
| 5.2 端到端集成测试 | 全流程验证 | 阶段四 |
| 5.3 文档更新 | README、隐私声明、合规检查 | 5.2 |
| 5.4 发布与 Release Notes | v0.4.0 打包发布 | 5.3 |

---

## 6. 关键风险与对策

| 风险 | 可能性 | 影响 | 对策 |
|---|---|---|---|
| **WBI 签名算法变更** | 中 | 高 | 模块化设计，仅改 `bili_signer.py`；增加自动检测机制 |
| **buvid3 风控升级** | 中 | 中 | 参考 `bilibili-API-collect` 的社区方案；支持 Cookie 池轮询 |
| **DASH 流格式变更** | 低 | 高 | 播放流解析独立模块，格式解析与下载流程分离 |
| **ffmpeg 捆绑体积** | 低 | 中 | 仅捆绑 ffmpeg.exe（约 50MB），可选下载器或提示用户安装 |
| **B 站 API 接口变更** | 中 | 高 | 所有 API 端点集中定义在 `constants.py`，变更时只改一处 |
| **多 P 视频用户体验** | 低 | 中 | 默认合并所有 P 为独立文件，UI 展示"共 N 集"并支持勾选 |

---

## 7. 合规说明

B 站视频下载需注意以下合规事项：

1. **版权内容**：下载的 B 站视频仅限个人学习、研究、收藏使用，不得用于二次分发、商业用途
2. **大会员内容**：1080P+ 及以上画质需要大会员 Cookie，工具不主动破解或绕过会员限制
3. **平台规则**：遵守 `www.bilibili.com` 的 `robots.txt` 与用户协议，控制请求频率避免对平台造成压力
4. **开源协议**：参考 `bilibili-API-collect`（已归档）和 `bilix`（MIT）的设计，但不直接复用其代码，保持与现有项目一致的合规策略
5. **免责声明**：在 README 和首次引导中增加 B 站使用边界说明

---

## 8. 附录：项目结构变更概览

### 新增文件

```
crawlers/bilibili/
├── __init__.py
├── bili_signer.py
├── bili_url_parser.py
├── bili_video_parser.py
├── bili_user_crawler.py
├── bili_http_client.py
└── constants.py

docs/superpowers/specs/2026-08-25-bilibili-support-design.md

backend/api/bilibili.py

frontend/src/pages/BiliFetchPage.tsx
```

### 修改文件

```
backend/app.py
backend/api/download.py
app/models.py
app/database.py
downloader/downloader.py
downloader/constants.py
frontend/src/lib/api.ts
frontend/src/pages/DownloadPage.tsx
frontend/src/pages/CookiePage.tsx
frontend/src/pages/SettingsPage.tsx
frontend/src/components/NavBar.tsx
frontend/src/layouts/AppShell.tsx
frontend/src/lib/utils.ts
pyproject.toml
```

---

> **下一步**：评审本方案后，开始阶段一（核心爬虫模块）的编码实现。
