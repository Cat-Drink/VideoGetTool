# 根因分析：列表项预览图不显示（/covers 代理误拦截透明代理网段）

- **日期**: 2026-09-02
- **关联**: 紧随 curl_cffi 迁移（httpx→curl_cffi，65ad7d3）之后
- **涉及文件**: `backend/api/covers.py`, `tests/test_api_covers.py`

## 一、故障现象

curl_cffi 迁移修复抖音解析接口后，解析列表项与抓取列表项的**预览图片不显示**。
前端 `<img>` 指向本地 sidecar 的 `/api/covers?url=...` 代理地址，
代理抓取远程封面后以本地来源返回。

## 二、根因

1. 封面 CDN（`douyinpic.com` / `hdslb.com`）在本地透明代理（Clash / sing-box /
   V2Ray TUN 模式）环境下，DNS 解析到 `198.18.0.0/15` 网段（RFC 2544 基准测试
   网段，被代理用作虚拟网关地址）。
2. `/covers` 的 SSRF 防护（`_SSRFGuardTransport` / `_is_blocked_ip`）在连接阶段
   对解析出的 IP 做私网/保留段校验；Python `ipaddress` 将 `198.18.0.0/15`
   判定为 `is_private=True`，导致该网段被误拦截。
3. 于是 `/covers` 返回 400 `target blocked or unreachable`，前端图片加载失败，
   列表项预览图不显示。

## 三、验证证据

- `socket.getaddrinfo('p3-pc-sign.douyinpic.com', 443)` → `198.18.0.206`
- 修复前：`_is_blocked_ip('198.18.0.206')` → `True`，代理返回 400
- 修复后：`_is_blocked_ip('198.18.0.206')` → `False`，`proxy_cover` 成功返回
  20095 字节 image/jpeg

## 四、修复方案

在 `_is_blocked_ip` 中显式放行 RFC 2544 基准测试网段 `198.18.0.0/15`：

- 该网段是基准测试/透明代理虚拟网关地址，并非真实私网/内网基础设施；
- 请求仍经由用户本地代理出口，不构成 SSRF 到内网的风险；
- 真正的私网（10/8、172.16/12、192.168/16）、回环、链路本地、保留段仍被拦截。

## 五、验证

- `tests/test_api_covers.py` 新增回归用例 `test_allows_benchmark_range_for_proxy`
- 全量测试：781 passed, 6 skipped
- 真实封面端到端：`proxy_cover` 成功返回图片字节
