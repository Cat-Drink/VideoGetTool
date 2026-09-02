# t3 验证清单：验证修复效果并跑全量测试

- 作者: captain（douyin-parser-hotfix 团队）
- 依赖: t2（engineer 实施修复后执行）

## 一、修复目标（对照）

修复前（httpx）：
```
GET aweme/detail → HTTP 200, content-length:0, body=b''（带 x-janus-info）→ response.json() 抛 "Expecting value: line 1 column 1 (char 0)"
```

修复后（curl_cffi impersonate="chrome" + 有效 Cookie）：
```
GET aweme/detail → HTTP 200, len≈98KB, aweme_detail 存在, status_code=0
```

## 二、验证步骤

### 1. 单元测试
```
python -m pytest tests/test_http_client.py -v
python -m pytest tests/test_video_parser.py -v
python -m pytest tests/test_cookie_tester.py -v
python -m pytest tests/test_user_home_crawler.py -v
python -m pytest tests/test_url_parser.py -v
```
- 全绿 → 通过
- 有失败 → 需 engineer 修复或确认是预期调整

### 2. 真实端到端验证（关键）
用 DB 真实 Cookie + 修复后的 HttpClient 调 VideoParser.parse_video：
- 返回 VideoInfo（title/author/cover/no_watermark_url 等字段非空）
- 不再抛 "响应 JSON 解析失败"

### 3. 短链重定向回归
- url_parser.follow_redirect（v.douyin.com 短链 → 302 → Location）
- 确认 curl_cffi allow_redirects=False 时仍返回 302 + Location 头

### 4. 空 body 防御
- 若请求仍返回空 body（例如无 Cookie 时），应优雅处理（报 Cookie 失效或明确错误），而不是崩溃

### 5. 全量测试（可选，若时间允许）
```
python -m pytest -x -q
```

## 三、通过标准
1. 相关单元测试全绿
2. 真实端到端 parse_video 成功返回 VideoInfo（数据非空）
3. 短链重定向正常工作
4. 空 body 场景有防御性处理

## 四、输出
- 验证报告（成功/失败、测试结果、抓取是否恢复）
- 更新 t3 状态 completed
