# C++ Backend Internship Monitor

面向 C++ 后端、Linux 服务端、网络通信、基础架构和系统开发方向的实习岗位云端监控系统。

项目通过 GitHub Actions 周期运行，自动抓取岗位页面，按关键词和规则评分，调用可选 AI 分析岗位匹配度，使用 SQLite 去重，并在达到每日停止条件后通过 SMTP 统一发送报告。

## 云端运行方式

本项目不是在本地常驻运行，而是在 GitHub Actions 云端按计划启动：

- 默认每天北京时间 18:00 运行一次
- 支持在 GitHub Actions 页面手动运行
- 每次运行结束后会把 `database/jobs.db` 和 `reports/latest.md` 提交回仓库
- SQLite 数据库用于跨运行去重，避免重复推送同一岗位
- 每天会累计有效岗位数量；如果当天未达到 10 个有效岗位，会继续爬取，直到达到 10 个或当天累计爬取 200 轮
- 未达到每日停止条件时只更新数据库和报告文件，不发送邮件

GitHub Actions 不能作为 24 小时常驻进程使用，但这种定时唤醒方式适合招聘信息监控。

## 每日爬取目标

`config.yaml` 里的默认策略是：

```yaml
app:
  daily_timezone: Asia/Shanghai
  daily_target_valid_jobs: 10
  max_daily_crawl_attempts: 200
  max_crawl_attempts_per_run: 200
  crawl_interval_seconds: 0
```

有效岗位指：规则评分未被排除、分数达到 `min_score`、并且数据库里没有见过的新岗位。重复链接不会重复计数。

一轮爬取会跑完当前启用的所有 `sources`。云端 workflow 超时时间设置为 360 分钟，避免 200 轮还没跑完就被提前结束。

邮件不会在每一轮爬取后发送。只有下面任一条件满足后，系统才会统一发一封报告：

- 今日累计有效岗位达到 `daily_target_valid_jobs`
- 今日累计爬取轮次达到 `max_daily_crawl_attempts`

## 需要配置的 GitHub Secrets

进入仓库：

`Settings -> Secrets and variables -> Actions -> New repository secret`

建议添加：

| Secret | 用途 | 必填 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | DeepSeek AI 岗位分析 | 否 |
| `OPENAI_API_KEY` | 切换 OpenAI 时使用 | 否 |
| `SMTP_HOST` | SMTP 服务器，如 `smtp.gmail.com` | 发邮件必填 |
| `SMTP_PORT` | SMTP 端口，如 `587` | 发邮件必填 |
| `SMTP_USE_SSL` | 465 端口时可填 `true`，留空会自动判断 | 否 |
| `SMTP_STARTTLS` | 587 端口时通常填 `true` | 否 |
| `SMTP_USERNAME` | 邮箱登录用户名 | 发邮件必填 |
| `SMTP_PASSWORD` | 邮箱密码或应用专用密码 | 发邮件必填 |
| `EMAIL_FROM` | 发件邮箱 | 发邮件必填 |
| `EMAIL_TO` | 收件邮箱 | 发邮件必填 |

可选 Variables：

| Variable | 默认值 | 用途 |
| --- | --- | --- |
| `AI_PROVIDER` | `deepseek` | `deepseek`、`openai`、`openai_compatible` 或 `disabled` |
| `AI_MODEL` | `deepseek-v4-flash` | AI 分析模型 |
| `AI_BASE_URL` | `https://api.deepseek.com` | DeepSeek/OpenAI-compatible 服务地址 |

云端 workflow 会强制检查邮件 Secrets。定时任务在每天 UTC 10:00（北京时间 18:00）运行，并使用 `--require-email`；push 和手动触发会使用 `--no-email`，只做检查和更新报告，不会在 18:00 之外发邮件。未达到每日停止条件时不会发邮件，也不会因为暂未发送而失败；一旦达到停止条件，如果邮件配置缺失或发送失败，本次 Actions 会失败，避免出现“显示成功但其实没发邮件”的情况。

## 邮箱推送配置

如果使用 QQ 邮箱，建议先在 QQ 邮箱设置里开启 `POP3/SMTP` 或 `IMAP/SMTP`，生成授权码。GitHub Actions Secrets 可按下面填写：

```text
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USE_SSL=true
SMTP_USERNAME=你的QQ邮箱地址
SMTP_PASSWORD=QQ邮箱授权码，不是QQ登录密码
EMAIL_FROM=你的QQ邮箱地址
EMAIL_TO=接收日报的邮箱地址
```

如果使用 Gmail，常见配置是：

```text
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_STARTTLS=true
SMTP_USERNAME=你的Gmail地址
SMTP_PASSWORD=Gmail应用专用密码
EMAIL_FROM=你的Gmail地址
EMAIL_TO=接收日报的邮箱地址
```

## DeepSeek 配置

如果使用 DeepSeek，只需要在 GitHub Actions Secrets 里添加：

```text
Name: DEEPSEEK_API_KEY
Secret: 你的 DeepSeek API Key
```

默认配置会使用 `AI_PROVIDER=deepseek`、`AI_MODEL=deepseek-v4-flash`、`AI_BASE_URL=https://api.deepseek.com`。这些默认值不需要手动添加为 Variables。

## 手动触发

1. 打开仓库的 `Actions` 页面
2. 选择 `Cloud Job Monitor`
3. 点击 `Run workflow`

## 自定义岗位来源

编辑 `config.yaml` 的 `sources`：

- `nowcoder`、`shixiseng`、`yingjiesheng` 是内置的搜索页爬虫适配器
- `generic` 适合企业招聘官网、高校就业网、人才平台等普通页面
- 如果某个平台反爬或页面强依赖 JavaScript，建议把稳定的搜索结果页、RSS、企业招聘页面加入 `generic.urls`

示例：

```yaml
sources:
  - name: my_company_pages
    type: generic
    enabled: true
    urls:
      - "https://example.com/jobs"
```

## 本地验证

云端运行使用 Python 3.12。本地检查也建议使用 Python 3.12：

```bash
python -m pip install -r requirements.txt
python -m pytest
python main.py --no-email
```

云端同款邮件强制检查：

```bash
python main.py --config config.yaml --require-email
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

