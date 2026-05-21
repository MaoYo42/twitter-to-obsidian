# Twitter Bookmarks → Obsidian Knowledge Base

全自动将 X/Twitter 书签转化为 Obsidian 知识库卡片。

**拉取书签 → 内容抓取 → AI 知识提炼 → 分类入库 → 自动清理线上书签**

## ✨ 特性

- 🔄 **全自动闭环** — 从拉取到清理一条命令搞定
- 🧠 **AI 知识提炼** — 原始推文自动提炼为结构化知识卡片（需配合 AI Agent）
- 📂 **智能分类** — 按作者/主题前缀路由到对应知识库目录
- 🍪 **免维护 Cookie** — 通过 [OpenCLI](https://github.com/nicepkg/opencli) 复用 Chrome 登录态，自动刷新
- 🗑️ **GraphQL 静默清理** — 后台 API 删除已处理书签，不操控浏览器前台
- ⏰ **Cron 友好** — 设为定时任务，每天自动执行
- 📝 **运行日志** — 每次执行的拉取、新增、清理情况自动记录

## 📐 架构

```
X/Twitter 书签
    │
    ▼
┌─────────────────────────┐
│ 阶段0: 连通性检查       │  opencli doctor + 3 次自动重试
│   (stage_check_daemon)  │
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ 阶段1: 拉取书签         │  opencli twitter bookmarks --limit N
│   (stage_fetch_bookmarks)│  输出 JSON: id, author, text, url, ...
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ 阶段2: 过滤去重         │  对比 processed_tweet_ids.json
│   (stage_filter_new)    │  只处理新增书签
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ 阶段3: 保存原始内容     │  结构化 Markdown（含元数据）
│   (stage_save_to_sorted)│  → 30_已整理/Twitter/{tweet_id}.md
└────────┬────────────────┘
         ▼
┌─────────────────────────┐
│ 阶段4: 清理线上书签     │  GraphQL DeleteBookmark API
│   (stage_unbookmark)    │  通过 opencli 自动获取新鲜 Cookie
└─────────────────────────┘
         │
         ▼
    ┌─────────┐
    │ AI Agent│  ← 外部：读取原始推文 → 提炼知识卡片 → 入库
    │  提炼    │     prompts/知识卡片提炼prompt.md
    └─────────┘
```

## 🗂️ 目录结构

```
twitter-to-obsidian/
├── tools/                          # 脚本工具集
│   ├── twitter_auto_v2.py          # 🚀 主入口：全自动 pipeline v2（推荐）
│   ├── twitter_auto.py             # v1 备用（依赖 cookie 文件）
│   ├── twitter_unbookmark.py       # GraphQL API 批量删除书签（独立使用）
│   ├── twitter_fetch.py            # URL/推文 → Markdown 内容抓取
│   ├── twitter_ingest.py           # 书签 URL 收集
│   ├── twitter_route.py            # 按前缀分类路由 + 索引更新
│   ├── twitter_pipeline.py         # v1 三阶段编排
│   ├── twitter_cookie_via_opencli.py  # opencli cookie 获取
│   ├── twitter_cookie_from_chrome.py  # Chrome DB 直接解密 (备用)
│   ├── twitter_refresh_cookie.py      # CDP cookie 提取 (v1)
│   ├── twitter_doctor.py           # 环境连通性检查
│   ├── twitter_manual_import.py    # 手动导入（URL/文件）
│   └── common.py                   # 公共工具函数（路径、配置、请求）
├── prompts/
│   └── 知识卡片提炼prompt.md       # AI Agent 知识提炼指令模板
├── templates/                      # Markdown 模板文件
├── 00_收件箱/                      # URL 暂存（含 _state/processed_tweet_ids.json）
├── 10_原始内容/                    # 原始抓取内容（待路由）
├── 30_已整理/                      # 待 AI 提炼
├── 40_已归档/                      # 已处理归档
├── LICENSE
└── README.md
```

## 🚀 快速开始

### 前提

- **Python 3.10+**
- **Google Chrome / Chromium** 已登录 [x.com](https://x.com)
- **[OpenCLI](https://github.com/nicepkg/opencli)** 已安装且插件已启用
- **Obsidian** (可选，用于浏览知识库)

### 安装

```bash
git clone https://github.com/MaoYo42/twitter-to-obsidian.git
cd twitter-to-obsidian
```

无额外依赖，纯 Python 标准库。

### 使用

```bash
# 全自动：拉取 → 保存 → 清理书签
python3 tools/twitter_auto_v2.py

# 预览模式（不执行写入和清理）
python3 tools/twitter_auto_v2.py --dry-run

# 自定义拉取数量（默认 100）
python3 tools/twitter_auto_v2.py --limit 50

# 跳过清理书签（只拉取保存不删除线上书签）
python3 tools/twitter_auto_v2.py --no-unbookmark

# 按前缀分类路由已保存的书签
python3 tools/twitter_route.py

# 手动导入 URL
python3 tools/twitter_manual_import.py
```

### 定时执行

配合 cron 或 AI Agent 定时运行：

```bash
# 每晚 21:30 自动执行
30 21 * * * cd /path/to/twitter-to-obsidian && python3 tools/twitter_auto_v2.py
```

```bash
# 路由脚本紧跟其后
31 21 * * * cd /path/to/twitter-to-obsidian && python3 tools/twitter_route.py
```

## 🔧 Pipeline 详解

### 阶段 0：连通性检查

自动执行 `opencli doctor`，3 次重试，确认：
- Chrome 已运行
- OpenCLI 插件已连接
- daemon 未超时（有 5 分钟空闲自动断开）

如果失败，流程提前终止并提示用户。

### 阶段 1：拉取书签

通过 `opencli twitter bookmarks --limit N -f json` 拉取书签列表。输出包含每条书签的：
- `id` — 推文 ID
- `author` — 作者
- `text` — 推文正文
- `url` — 原始链接
- `created_at` — 创建时间
- `likes` — 喜欢数

### 阶段 2：过滤去重

对比 `00_收件箱/_state/processed_tweet_ids.json` 中的已处理 ID 集合，只保留新增书签。

### 阶段 3：保存原始内容

每条新书签保存为 `30_已整理/Twitter/{tweet_id}.md`，格式为：

```markdown
---
tweet_id: 1234567890
author: username
likes: 42
created_at: 2025-01-15T10:30:00Z
url: https://x.com/username/status/1234567890
---

推文正文内容...
```

文件名使用纯 tweet ID，后续 AI Agent 提炼时可重命名为中文标题。

### 阶段 4：清理线上书签

通过 `opencli daemon cookies API` 自动获取新鲜 Cookie + CSRF Token，再调用 Twitter GraphQL API `DeleteBookmark` 静默删除已处理书签。

- 内置 **429 限流退避重试**
- 每删一条间隔 0.5s 防触发风控
- 每 10 条输出一次进度

## 🔑 Cookie 获取方案

| 方案 | 说明 | 推荐 |
|------|------|------|
| **opencli v2** | 通过 OpenCLI daemon 自动复用 Chrome 登录态 | ✅ 推荐（默认） |
| Chrome DB 解密 | 直接读 Chrome Cookie 数据库 + macOS Keychain | 需要系统密码 |
| 手动设置 | 导出 cookie 到 `~/.x_cookie_env` | 最后手段 |

## 🧠 AI 知识卡片提炼

Pipeline 本身只保存原始推文内容，**知识卡片提炼由 AI Agent 完成**。

参考 `prompts/知识卡片提炼prompt.md` 中的模板，用任意 LLM（Claude、ChatGPT、DeepSeek 等）批量提炼：

1. 读取 `30_已整理/Twitter/` 下的原始推文
2. 按模板提炼为结构化知识卡片
3. 自动分类放入对应知识库目录
4. 低价值内容归档到 `40_已归档/`

你可以用 Hermes Agent、Claude Code、或任何手动流程完成提炼。

## 🔧 其他工具

| 工具 | 用途 |
|------|------|
| `twitter_fetch.py` | 从 URL 抓取完整推文/文章内容（支持 Jina AI proxy） |
| `twitter_route.py` | 按文件前缀分流原始笔记到对应目录，自动更新 `_index.md` |
| `twitter_manual_import.py` | 手动导入单条 URL 或多个文件 |
| `twitter_unbookmark.py` | 独立使用 GraphQL API 批量删除书签 |
| `twitter_doctor.py` | 单独检查 opencli 及环境连通性 |
| `twitter_ingest.py` | 收集书签 URL 到收件箱（旧版） |

## 📊 运行日志

每次自动执行后，运行结果会记录到 `00_收件箱/_state/auto_run_log.jsonl`：

```jsonl
{"version":"v2-opencli","fetched":100,"new":12,"saved":12,"unbookmark_ok":12,"unbookmark_fail":0,"timestamp":"2025-06-10T21:30:00"}
```

## ⚠️ 注意事项

- **Chrome 必须后台运行** + OpenCLI 插件启用 + x.com 已登录
- OpenCLI daemon 有 **5 分钟空闲超时**，脚本的 doctor 会自动唤醒
- GraphQL API 有 **429 限流**，脚本内置退避重试
- Pipeline 只保存**文字内容**，不含图片/视频
- `--dry-run` 模式可安全预览即将操作的内容

## 📄 License

MIT
