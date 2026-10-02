# C++ Backend Internship Monitor

面向 C++ 后端、Linux 服务端、网络通信、基础架构、系统开发和嵌入式网络通信方向的实习岗位监控程序。

系统通过 GitHub Actions 每天抓取岗位，按关键词评分，使用 SQLite 去重，可选调用 AI 生成匹配分析，并通过 SMTP 发送当天累计报告。

## 自动运行

- 每天北京时间 **13:00** 运行，对应 GitHub Actions cron `0 5 * * *`
- 定时运行完成一次抓取后发送一封邮件，即使当天没有合格的新岗位也会发送结果
- 当天邮件发送成功后写入标记；同一天意外重复触发的定时任务会跳过
- 普通 push 只安装依赖、执行测试和检查 workflow，不抓取、不发送邮件
- 提交信息包含 `[send-now]` 时，会立即抓取并发送邮件
- workflow 并发任务排队执行，不会由后续触发取消正在运行的扫描

GitHub Actions 的定时任务可能比 13:00 延迟几分钟，这是 GitHub 调度机制导致的正常现象。

## 手动运行模式

在 `Actions -> Cloud Job Monitor -> Run workflow` 中选择：

| 模式 | 行为 |
| --- | --- |
| `scan_only` | 抓取并更新数据库和报告，不发邮件 |
| `scan_and_email` | 抓取后发送当天累计报告 |
| `resend_latest` | 不抓取，直接补发 `reports/latest.md` |

## 当前爬取来源

当前启用以下搜索页适配器：

- 牛客：C++ 后端、Linux 服务端、网络编程
- 实习僧：武汉优先，同时覆盖北京、上海、深圳、杭州、广州、南京、成都、西安、苏州；自动还原页面动态字体并提取真实公司名
- 应届生求职网：C++ 后端和 Linux 实习

`company_pages` 中保留了企业招聘官网示例，但这些页面大多依赖 JavaScript，默认关闭。只有经过实际解析验证后才应启用。

爬虫会输出每个来源抓取数量、排除数量、低分数量、重复数量和新增数量，并记录少量被过滤岗位示例，方便判断页面改版、反爬或评分配置问题。

## 筛选和停止条件

主要配置位于 `config.yaml`：

```yaml
app:
  daily_timezone: Asia/Shanghai
  min_score: 30
  daily_target_valid_jobs: 10
  max_daily_crawl_attempts: 1
  max_crawl_attempts_per_run: 1
```

一次运行会完整抓取当前启用来源。相同搜索页在短时间内通常不会产生新结果，因此每天只抓取一轮，避免旧版本连续请求同一页面 200 次。

`daily_target_valid_jobs` 仍用于展示目标进度；定时任务使用 `--force-email`，因此完成当天这一轮后就会发送邮件，不再等待凑满 10 个岗位。数据库按链接去重，邮件从数据库重新读取当天累计岗位，所以 SMTP 失败后重试不会得到空报告。

武汉和远程岗位在报告中优先，其后是接受的其他城市。岗位必须命中 C++、Linux、Socket、服务端、基础架构或嵌入式等核心方向；只有“Java/Go 后端”而没有这些核心词的岗位会被排除。实习时长不会导致岗位被过滤。

## GitHub Secrets

进入：

`Settings -> Secrets and variables -> Actions -> New repository secret`

| Secret | 用途 | 必填 |
| --- | --- | --- |
| `SMTP_HOST` | SMTP 地址，如 `smtp.qq.com` | 是 |
| `SMTP_PORT` | QQ SSL 通常为 `465` | 是 |
| `SMTP_USERNAME` | 邮箱登录用户名 | 是 |
| `SMTP_PASSWORD` | SMTP 授权码或应用专用密码 | 是 |
| `EMAIL_FROM` | 发件邮箱 | 是 |
| `EMAIL_TO` | 收件邮箱 | 是 |
| `SMTP_USE_SSL` | 使用 465 时填 `true` | 建议 |
| `SMTP_STARTTLS` | 使用 587 时填 `true` | 建议 |
| `DEEPSEEK_API_KEY` | DeepSeek 岗位分析 | 否 |
| `OPENAI_API_KEY` | 使用 OpenAI 时填写 | 否 |

QQ 邮箱推荐配置：

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_STARTTLS=false
SMTP_USERNAME=你的QQ邮箱地址
SMTP_PASSWORD=QQ邮箱SMTP授权码
EMAIL_FROM=你的QQ邮箱地址
EMAIL_TO=接收日报的邮箱地址
```

Gmail 常见配置：

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_SSL=false
SMTP_STARTTLS=true
SMTP_USERNAME=你的Gmail地址
SMTP_PASSWORD=Gmail应用专用密码
EMAIL_FROM=你的Gmail地址
EMAIL_TO=接收日报的邮箱地址
```

workflow 会先检查六个必填值是否为空。SMTP 登录或发送失败会让 Actions 明确失败，不会写入当天成功标记。

## AI Variables

可在 Actions Variables 中设置：

| Variable | 默认值 |
| --- | --- |
| `AI_PROVIDER` | `deepseek` |
| `AI_MODEL` | `deepseek-v4-flash` |
| `AI_BASE_URL` | `https://api.deepseek.com` |

AI 调用失败不会丢弃岗位，会退回规则评分结果。

## 本地验证

```bash
python -m pip install -r requirements.txt
python -m pytest
python main.py --config config.yaml --no-email
```

本地抓取并强制发送：

```bash
python main.py --config config.yaml --force-email --require-email
```

补发已有日报：

```bash
python main.py --config config.yaml --email-only --require-email
```

## 目录结构

```text
.
├── main.py
├── config.yaml
├── requirements.txt
├── models.py
├── settings.py
├── storage.py
├── crawler/
├── analyzer/
├── mail/
├── tests/
├── database/
├── reports/
└── .github/workflows/daily.yml
```
