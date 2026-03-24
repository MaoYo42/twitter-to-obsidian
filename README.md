# Twitter Bookmarks → Obsidian Knowledge Base

全自动将 X/Twitter 书签转化为 Obsidian 知识库卡片。

**拉取书签 → 内容提取 → AI 提炼知识卡片 → 分类入库 → 自动清理线上书签**

## ✨ 特性

- 🔄 **全自动闭环** — 从拉取到清理一条命令搞定
- 🧠 **AI 知识提炼** — 原始推文自动提炼为结构化知识卡片
- 📂 **智能分类** — 按主题自动归入对应知识库目录
- 🍪 **免手动维护 Cookie** — 通过 [OpenCLI](https://github.com/nicepkg/opencli) 复用 Chrome 登录态
- 🗑️ **后台清理** — GraphQL API 静默删除已处理书签，不操控浏览器前台
- ⏰ **Cron 友好** — 设为定时任务，每天自动执行

## 📐 架构

```
X/Twitter 书签
    │
    ▼
┌─────────────────┐
│  阶段0: 连通性检查  │  opencli doctor + 自动唤醒 daemon
└────────┬────────┘
         ▼
┌─────────────────┐
│  阶段1: 拉取书签    │  opencli twitter bookmarks --limit N
└────────┬────────┘
         ▼
┌─────────────────┐
│  阶段2: 过滤去重    │  对比 processed_tweet_ids.json
└────────┬────────┘
         ▼
┌─────────────────┐
│  阶段3: 保存原始内容 │  → 30_已整理/Twitter/{tweet_id}.md
└────────┬────────┘
         ▼
┌─────────────────┐
│  阶段4: 清理书签    │  GraphQL DeleteBookmark API (后台)
└────────┬────────┘
         ▼
┌─────────────────┐
│  AI 知识卡片提炼   │  Agent 读取 → 提炼 → 入库知识库/
└─────────────────┘
```

## 🗂️ 目录结构

```
twitter-to-obsidian/
├── tools/
│   ├── twitter_auto_v2.py       # 🚀 主入口：全自动 pipeline v2
│   ├── twitter_auto.py          # v1 备用（依赖 cookie 文件）
│   ├── twitter_unbookmark.py    # GraphQL API 批量删除书签
│   ├── twitter_fetch.py         # URL → Markdown 内容抓取
│   ├── twitter_ingest.py        # 书签 URL 收集
│   ├── twitter_route.py         # 分类路由
│   ├── twitter_pipeline.py      # v1 三阶段编排
│   ├── twitter_cookie_via_opencli.py  # opencli cookie 获取
│   ├── twitter_cookie_from_chrome.py  # Chrome DB 直接解密 (备用)
│   ├── twitter_refresh_cookie.py      # CDP cookie 提取 (v1)
│   ├── twitter_doctor.py        # 环境检查
│   ├── twitter_manual_import.py # 手动导入
│   └── common.py                # 公共工具函数
├── prompts/
│   └── 知识卡片提炼prompt.md     # AI 提炼指令模板
├── templates/                    # Markdown 模板
├── 00_收件箱/                    # URL 暂存
├── 10_原始内容/                  # 原始抓取
├── 30_已整理/                    # 待提炼
├── 40_已归档/                    # 已处理归档
└── README.md
```

## 🚀 快速开始

### 前提

- **Python 3.10+**
- **Google Chrome** 已登录 x.com
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

# 自定义拉取数量
python3 tools/twitter_auto_v2.py --limit 50

# 跳过清理书签
python3 tools/twitter_auto_v2.py --no-unbookmark
```

### 定时执行

配合 cron 或 AI Agent 定时运行：

```bash
# 每晚 21:30 自动执行
30 21 * * * cd /path/to/twitter-to-obsidian && python3 tools/twitter_auto_v2.py
```

## 🔑 Cookie 获取方案

| 方案 | 说明 | 推荐 |
|------|------|------|
| **opencli (v2)** | 通过 OpenCLI daemon 复用 Chrome 登录态 | ✅ 推荐 |
| Chrome DB 解密 | 直接读 Chrome Cookie 数据库 + Keychain | 需要系统密码 |
| 手动设置 | 导出 cookie 到环境变量 | 最后手段 |

## 🧠 AI 知识卡片提炼

Pipeline 保存的是原始推文内容。知识卡片提炼由 AI Agent 完成（参考 `prompts/知识卡片提炼prompt.md`）：

- 8-25 字中文知识标题命名
- 结构化格式：核心要点 + 详细内容 + 个人备注
- 自动分类到对应知识库目录
- 低价值内容直接归档

你也可以用任何 LLM（ChatGPT、Claude、本地模型）手动提炼。

## ⚠️ 注意事项

- 需要 Chrome 后台运行 + OpenCLI 插件启用 + x.com 已登录
- OpenCLI daemon 有 5 分钟空闲超时，脚本会自动唤醒
- GraphQL API 有限流（429），脚本内置退避重试
- 书签数据不含图片/视频内容，纯文字推文效果最好

## 📄 License

MIT
