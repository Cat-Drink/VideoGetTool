# 根因分析：aweme/detail 返回 HTTP 200 但响应体为空导致 JSON 解析失败

- **日期**: 2026-09-02
- **作者**: researcher（douyin-parser-hotfix 团队）
- **涉及文件**: `crawlers/http_client.py`, `crawlers/video_parser.py`, `crawlers/api_spec.py`, `crawlers/signer/*`
- **任务**: t1

## 一、故障现象

`crawlers/video_parser.py:527` 调用 `response.json()` 抛出：

```
Expecting value: line 1 column 1 (char 0)
```

应用日志显示：

```
GET https://www.douyin.com/aweme/v1/web/aweme/detail/ → HTTP/2 200 OK
```

即：HTTP 状态码为 200，但响应体为空（或非 JSON），导致 JSON 解析失败。

## 二、复现证据

用项目现有 `Signer` + `httpx`（`hotfix_repro.py`，aweme_id=7680130011252133158）实际复现：

```
STATUS: 200
URL: https://www.douyin.com/aweme/v1/web/aweme/detail/?aweme_id=7680130011252133158&aid=6383&device_platform=webapp&channel=channel_pc_web&version_code=170400&X-Bogus=DFSzswVYRWtANG%2F%2FCw008l9WX7jk&a_bogus=mXBdhHjLm2WbO4EJ1XowdUV9MAw3quIQVjFIDzU6HxV8&msToken=...&verifyFp=...
HEADERS:
  content-type: application/json
  content-length: 0
  x-janus-info: o2AijlA31hg6vKLsuKswWwUucCegie0UGadyD8uiGjuu1dK-...
  server: Tengine
  x-tt-logid: ...
BODY_LEN: 0
BODY_PREVIEW: b''
JSON_FAIL: Expecting value: line 1 column 1 (char 0)
```

**关键观测**：
- HTTP 200，`content-type: application/json`
- **`content-length: 0`，body 为 `b''`（0 字节）**
- 响应头带 **`x-janus-info`**（Douyin Janus 风控系统的标记头）

## 三、排除性实验（对照组）

| # | 变量 | 结果 |
|---|------|------|
| A | 最小请求头（UA/Referer/Accept/Accept-Language）+ 签名 | 200 空 body |
| B | 补全浏览器头（sec-ch-ua, sec-fetch-*, Origin, Priority） | 200 空 body |
| C | 完整浏览器头 + 有效登录 Cookie | 200 空 body |
| D | **完全不签名**（无 a_bogus/X-Bogus/msToken） | 200 空 body |
| E | 仅 a_bogus（去掉 X-Bogus/verifyFp） | 200 空 body |
| F | 新版 version_code=180800 | 200 空 body |
| G | HTTP/1.1（curl.exe，不同 TLS 指纹） | 200 空 body |
| H | search 接口（general/search/single）httpx | 同样被风控（verify_check 占位） |
| I | **curl_cffi impersonate="chrome" 请求同一 detail 接口** | **200, len=98763, aweme_detail 存在, status_code=0 ✅** |

**结论性对比**：
- 首页 `https://www.douyin.com/` 可正常返回 72KB HTML（说明网络可达、非全 IP 封锁）。
- 但 `aweme/v1/web/*` API 接口对 httpx 一律返回 200 + 空 body。
- **唯一变量生效的是客户端 TLS 指纹**：httpx（非浏览器 TLS ClientHello）→ 空 body；curl_cffi 冒充 Chrome → 真实 JSON。

## 四、根因结论

> **抖音 Janus 风控系统通过 TLS 指纹（JA3/JA4）识别出 Python httpx 客户端不是真实浏览器，对 `aweme/v1/web/*` 接口家族（detail/post/search）返回 HTTP 200 + 空 body（content-length: 0，带 x-janus-info 头）进行"软封禁"（静默空响应）。**

判定为题目选项 **(a) 响应体真为空（风控/反爬）**，且触发条件为 **TLS 指纹不匹配**：

1. ✅ 响应体**真的为空**（0 字节），非 Content-Encoding 解压问题（无任何压缩数据）。
2. ✅ 排除 Cookie 失效：带 8858 字符的有效登录 Cookie（含 sessionid/sid_tt/odin_tt/ttwid）仍为空。
3. ✅ 排除请求头缺失：补全 sec-ch-ua/sec-fetch-*/Origin 后仍为空。
4. ✅ 排除签名算法失效：完全不签名也返回同样空 body（说明服务端在签名校验之前就已拒绝）。
5. ✅ 排除 API 参数/版本过旧：version_code=170400/180800/190500 全部为空。
6. ✅ 排除 HTTP 版本：HTTP/1.1（curl.exe）与 HTTP/2 结果一致。
7. ✅ **决定性证据**：curl_cffi 以 `impersonate="chrome"` 发送**相同参数、相同 Cookie、相同签名**的请求 → 返回 98KB 真实 JSON（`aweme_detail` 存在、`status_code=0`）。

## 五、修复方案

**核心改动**：在 `crawlers/http_client.py` 中，用 `curl_cffi.requests.AsyncSession(impersonate="chrome")` 替代 `httpx.AsyncClient`，使 TLS 指纹（JA3/JA4）与真实 Chrome 一致，绕过 Janus 的 TLS 指纹识别。

### 兼容性核对（curl_cffi Response vs httpx Response）

全项目对 Response 的实际使用面（grep 结果）：
- `.json()` — video_parser.py:527, cookie_tester.py:181, user_home_crawler.py:361 ✅ 兼容
- `.status_code` — http_client.py:358 ✅ 兼容
- `.url`（仅 `str(response.url)` 与日志 `%s`）— http_client.py, url_parser.py:298 ✅ 兼容（curl_cffi 返回 str）
- `.headers.get("content-type"/"location")` — http_client.py:409, url_parser.py:294 ✅ 兼容
- `.text` — http_client.py:417 ✅ 兼容
- 未使用 `.iter_bytes/.raise_for_status/.request/.is_success/.read` — 无额外改造

**必须处理的差异**：
1. **`follow_redirects` → `allow_redirects`**（curl_cffi 构造参数名不同，实测报错 `unexpected keyword argument 'follow_redirects'`）。
2. **异常类型**：curl_cffi 抛 `curl_cffi.requests.exceptions.RequestException`（RequestsError），**不是 `httpx.HTTPError`**。`get()`（http_client.py:207）与 `_retry_with_next_cookie()`（http_client.py:248）中的 `except httpx.HTTPError` 必须改为捕获 curl_cffi 的异常（建议统一 catch `curl_cffi.requests.exceptions.RequestsError`，或做双异常兼容）。
3. **`aclose()` 不存在**：curl_cffi AsyncSession 只有同步 `close()`（无 `aclose`）。`HttpClient.close()`（http_client.py:155）的 `await self._client.aclose()` 需改为 `self._client.close()`（同步调用）。当前 backend/app.py 关闭流程未显式调用 `ctx.http_client.close()`，但测试会用到，需一并修正。
4. **`http2` 参数**：curl_cffi 默认走 libcurl，无需（也不支持）httpx 的 `http2=True` 参数；要 HTTP/2 时 curl_cffi 通过 `http_version` 或 `impersonate` 自动处理，无需显式设置。

### 依赖与范围

- **依赖声明**：curl_cffi 0.16.2 已安装但**未写入 requirements.txt**（当前仅 `httpx[http2]>=0.28`）。需添加 `curl_cffi>=0.16`。httpx 可保留作为下载器使用（见下）。
- **改动范围**：仅 `crawlers/http_client.py`（及构造参数、异常、close）。`video_parser.py / cookie_tester.py / user_home_crawler.py / url_parser.py` 通过注入的 HttpClient 调用，**无需改动**（它们只用兼容的 Response API）。
- **下载器（downloader/）**：`downloader.py` 直接使用 `httpx.AsyncClient` 做媒体流式下载（`.head()`, `.stream()`），目标为媒体 CDN 而非抖音 web API，**不在本次修复范围，保持 httpx 即可**。
- **测试影响**：`tests/test_http_client.py` 大量使用 `httpx.Response` 构造（`_make_response`）与 `respx` mock（respx 仅支持 httpx）。迁移后这些测试需改为使用 curl_cffi 的 Response 构造 / 替换 mock 层。`tests/test_video_parser.py / test_cookie_tester.py / test_user_home_crawler.py / test_url_parser.py` 通过 mock HttpClient.get 测试，不受影响。

### 建议实现要点（供 engineer）

```python
# crawlers/http_client.py 改造示意
from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import RequestException as CurlRequestException

self._client = AsyncSession(
    impersonate="chrome",   # 关键：TLS 指纹冒充 Chrome
    allow_redirects=False,  # 原 httpx 的 follow_redirects=False
    timeout=(timeout_connect, timeout_read),  # 或按 curl_cffi 的 timeout 语义调整
)

# get() 内
except CurlRequestException as e:
    raise NetworkError(f"网络请求失败: {e}") from e

# close() 内
self._client.close()  # 同步方法，不能 await
```

## 六、验证方式

修复后运行：

```
python hotfix_verify_curlffi.py   # 已创建于工作区根目录，实测通过
```

期望输出（修复目标）：
```
STATUS: 200
CT: application/json
LEN: 98763
JSON OK keys: ['aweme_detail', 'log_pb', 'status_code']
status_code: 0
aweme_detail: dict
```

## 七、附加说明

- 工作区根目录留有调查脚本：`hotfix_repro.py`（httpx 复现，仍返回空 body）、`hotfix_verify_curlffi.py`（curl_cffi 验证，成功）、`hotfix_api_compat.py`（API 兼容性探测）、`hotfix_getcookie.py`（读 DB Cookie）、`hotfix_variants.py / hotfix_matrix.py / hotfix_expA.py / hotfix_v1905.py`（历史对照实验）。
- 本次调查同时确认：应用 DB 中的 Cookie 为有效登录态（8858 字符，含 sessionid/sid_tt/odin_tt/ttwid），**不是 Cookie 失效问题**。
