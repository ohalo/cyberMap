# cyberMap

每日更新的 AI 工具与开源项目导航站：[https://cybermap.halo26812.eu.org/](https://cybermap.halo26812.eu.org/)

基于 Hexo + webstack 主题构建，数据由 `source/_data/webstack.yml` 单一驱动。推送 `main` 后由 Vercel 自动构建发布（无 Actions / `vercel.json`）。

## 站点内容

- **首页导航**：4 个父分组 / 17 个常设子分类（AI 工具箱、模型与开源、学习与资源、站点与常用），收录经核验的 AI 工具官网、GitHub 开源项目、模型与框架。
- **`/daily/` 每日 AI 速递**：按日期倒序的可订阅内容流，含收录质量回执（验证漏斗 + 逐条证据）、站点存活看板、上游变更雷达、项目动态速递、方向标签知识库；提供 6 个 RSS（全站聚合 + 开源/工具/模型/学习四类分类流 + 项目动态流）。
- **`/weekly/` 每周收录周报**：按 ISO 周聚合本周新增、验证漏斗、活跃项目 Top10 与方向分布，独立 RSS。
- **`/data/` 开放数据层**：全站导航的机器可读目录（`sites.json`）、OPML 订阅与文档页。
- **`/rank/` 排行榜**：AI 插件与 Agent Harness 榜单，由独立流水线每日维护（本仓库的每日收录流程不改动 `source/rank/**`）。
- **`/en/` 英文首页**：由 `scripts/build_en_site.py` 从导航数据与人工翻译表生成。
- **双主题**：经典态与赛博态（cookie `night=1`），赛博视觉令牌与设计节点见 `source/css/cybermap.css`、`source/js/cybermap.js`。

## 本地开发

需要 Node.js >= 22。

```bash
npm install
npm run server      # 本地预览 http://localhost:4000
npm run build       # hexo generate，产物在 public/
```

## 数据与脚本

- `source/_data/webstack.yml`：唯一数据源；新站点按性质写入最合适的既有分类，描述尾注 `· YYYY-MM-DD 收录` 标记收录日期。
- `scripts/`：仓库内生成器（SEO、每日速递、质量回执、健康看板、变更雷达、开放数据、周报、英文页）。多数只读、幂等，可被重复运行。
- 每日收录的完整 SOP 在用户级 skill `cybermap-daily`（`SKILL.md` 与 `references/workflow.md`），由每天 09:00 的自动化任务执行；所有中间产物（候选、证据报告、条目、备份）落在该 skill 的 `state/` 目录，不污染仓库。

## 发布约定

- 线上由 Vercel 监听 `main` 推送自动构建，`push 成功 = 触发上线`。
- 受本机沙箱限制，提交走用户级 CLI 的对象级 plumbing 模式（不读写 `.git/index`），不要手动 `git pull/add/commit`。
- `source/rank/**`、`source/daily/**`、`source/data/**`、`source/weekly/**`、`robots.txt`、`sitemap.xml` 在 `_config.yml` 中配为 `skip_render`，原样发布。
