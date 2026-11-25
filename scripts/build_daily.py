#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 每日 AI 速递生成器

读取 ``source/_data/webstack.yml`` 里全部 18 个分类的条目（每日收录按性质
路由进常设分类后，带「· YYYY-MM-DD 收录」尾注的条目可能出现在任何分类），
按描述尾注聚合成时间轴页面 ``source/daily/index.html``，并输出 RSS 2.0
订阅源：一份混合流 ``source/daily/feed.xml`` + 四份按性质大类聚合的独立流
``feed-oss.xml``（开源项目）/ ``feed-tool.xml``（工具官网）/ ``feed-model.xml``
（模型框架）/ ``feed-learn.xml``（学习与资源）（供读者只订阅自己关心的类型）；
另有 ``feed-updates.xml`` 项目动态流，来源 updates.json.recent，逐条罗列
已收录项目最近的新提交与涨星，与按收录日期的全量/分类流正交。

设计约束
--------
* 零新增依赖：只用标准库 + 仓库已有的 PyYAML。
* 页面自包含：内联 CSS / JS，不加载主题资源。浅/深主题通过共享 cookie
  ``night=1`` 与首页保持一致，在任一页面切换都会同步。
* 只读数据文件：绝不改写 webstack.yml；同样输入产出同样输出，可反复运行。
* 与 ``/rank/`` 同构：产物是纯静态文件，靠 _config.yml 的
  ``skip_render: ['rank/**', 'daily/**']`` 原样发布。
* 原子写入：先写同目录临时文件再 os.replace，避免留下半成品。

用法
----
    python scripts/build_daily.py [--repo /path/to/cyberMap]
                                  [--site-url https://cybermap.halo26812.eu.org]
    python scripts/build_daily.py --check     # 只校验数据，不写文件

退出码：0 成功；1 数据/参数错误（stdout 输出 JSON 诊断）。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import date, datetime, time, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    print(json.dumps({"ok": False, "error": f"缺少 PyYAML：{exc}"}, ensure_ascii=False))
    sys.exit(1)


SITE_URL_DEFAULT = "https://cybermap.halo26812.eu.org"
DATA_REL = Path("source/_data/webstack.yml")
OUT_REL = Path("source/daily")
VERIFY_REL = Path("source/daily/verify.json")
HEALTH_REL = Path("source/daily/health.json")
UPDATES_REL = Path("source/daily/updates.json")

# 分类 -> (中文标签, 短名)。顺序决定同一天内卡片的展示顺序。
# 覆盖全部 20 个分类：每日收录按性质路由进常设分类，
# 带日期尾注的常设分类条目同样进入时间轴/标签云/搜索。
CATEGORY_LABELS = OrderedDict([
    ("aiChat", ("对话与搜索", "chat")),
    ("aiImage", ("图像与设计", "image")),
    ("aiVideo", ("视频与音频", "video")),
    ("aiCode", ("编程与开发", "code")),
    ("aiOffice", ("办公与效率", "office")),
    ("aiAgent", ("智能体与自动化", "agent")),
    ("GPTModels", ("大语言模型", "llm")),
    ("githubGPT", ("GitHub 项目", "gh")),
    ("aiFrameworks", ("推理与训练框架", "framework")),
    ("ragKnowledge", ("RAG 与知识库", "rag")),
    ("agentFrameworks", ("智能体框架", "agentfw")),
    ("studyGPT", ("提示词与教程", "learn")),
    ("techBlog", ("技术博客", "blog")),
    ("aiNav", ("AI 导航站", "nav")),
    ("likeGPT", ("社区与问卷", "community")),
    ("hotTools", ("常用工具", "tools")),
    ("myBlog", ("我的博客", "myblog")),
])

# 分类订阅源：文件名 -> (分类中文名, 覆盖的分类 key 元组)。
# 分类流按「性质大类」聚合多个分类，而非一一对应：
#   开源项目流 = 每日开源 + GitHub 项目 + 推理与训练框架
#   工具官网流 = 每日工具 + AI 工具箱六个子类 + 常用工具
#   模型框架流 = 每日模型 + 大语言模型
#   学习资源流 = 提示词与教程 + 技术博客 + AI 导航站 + 社区与问卷 + 我的博客
# feed.xml 仍是混合全量流，覆盖所有分类。
CATEGORY_FEEDS = OrderedDict([
    ("feed-oss.xml", ("开源项目", ("githubGPT", "aiFrameworks",
                                  "ragKnowledge", "agentFrameworks"))),
    ("feed-tool.xml", ("工具官网", ("aiChat", "aiImage", "aiVideo",
                                   "aiCode", "aiOffice", "aiAgent", "hotTools"))),
    ("feed-model.xml", ("模型框架", ("GPTModels",))),
    ("feed-learn.xml", ("学习与资源", ("studyGPT", "techBlog", "aiNav", "likeGPT", "myBlog"))),
])

# 项目动态速递独立流：来源 updates.json.recent，与按收录日期的全量/分类流正交。
UPDATES_FEED = "feed-updates.xml"

# 形如「 · 2026-11-15 收录」，允许尾部空白；只匹配结尾，避免误伤正文里的日期。
DATE_TAG_RE = re.compile(r"[·•]\s*(\d{4}-\d{2}-\d{2})\s*收录\s*$")
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
CST = timezone(timedelta(hours=8))

# 方向标签规则表：(标签名, 正则)。与「按类型的分类订阅」正交：
# 分类回答「是什么类型」（开源/工具/模型），方向标签回答「属于哪个领域」
# （RAG / 推理 / 安全 / 教育…）。规则顺序即优先级，越具体的排越前；
# 每条最多打 3 个标签，全不命中时用「AI 应用」兜底，避免出现空标签。
# 复用 name + description 文本推断，纯标准库、幂等、无新增依赖。
TAG_RULES = [
    ("安全审计", r"secur|audit|漏洞|vulnerab|pentest|安全"),
    ("教育课堂", r"classroom|教学|课堂|education|课程|\blearn|学习|\bcourse"),
    ("视频图像", r"\bvideo|视频|multimodal|多模态|图像|image|\b3d|世界模型|render|渲染|动画|animation|创意"),
    ("办公文档", r"powerpoint|\bppt\b|slide|演示|\boffice|办公|文档|document"),
    ("浏览器自动化", r"browser|浏览器|playwright|无障碍|accessibility|网页自动化"),
    ("推理引擎", r"inference|推理|vllm|serving|推理引擎|模型服务|\bc99|低延迟"),
    ("训练微调", r"\btrain|训练|finetun|微调|from scratch|从零"),
    ("RAG 检索", r"\brag\b|retriev|检索|知识库|向量|embedding"),
    ("记忆", r"memor|记忆|跨会话"),
    ("多智能体", r"multi.?agent|多智能体|agent.?team|orchestrat|编排|\bteam|团队|commander|协同|协调|协同完成"),
    ("MCP", r"\bmcp\b|model context protocol"),
    ("技能生态", r"\bskill|技能"),
    ("前端 UI", r"frontend|前端|generative.?ui|生成式.{0,2}ui|react|angular|界面|\bui\b"),
    ("代码开发", r"coding|代码|code review|审查|developer|开发|\bsdk\b|\bcli\b|pull request|\bpr\b"),
    ("本地运行", r"local|本地|ollama|desktop|桌面|on.?device|端侧|self.?host"),
    ("语音", r"voice|语音|\btts\b|whisper|speech|配音"),
]
TAG_RULE_PATTERNS = [(label, re.compile(pattern, re.I)) for label, pattern in TAG_RULES]
MAX_TAGS_PER_ITEM = 3
FALLBACK_TAG = "AI 应用"


# ---------------------------------------------------------------- 内联资源
# 用独立字符串常量而不是 f-string 模板，避免 CSS 里的大量花括号需要转义。
CSS = r"""
*,*::before,*::after{box-sizing:border-box}
:root{
  --dy-font:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",
    "Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",sans-serif;
  --dy-bg:#f4f7fc;
  --dy-surface:rgba(255,255,255,.86);
  --dy-solid:#fff;
  --dy-border:rgba(15,23,42,.09);
  --dy-border-strong:rgba(15,23,42,.15);
  --dy-text:#1b2436;
  --dy-soft:#45526b;
  --dy-muted:#6b7790;
  --dy-accent:#4f46e5;
  --dy-accent-2:#06b6d4;
  --dy-chip:rgba(79,70,229,.09);
  --dy-icon-bg:rgba(241,245,251,.9);
  --dy-shadow:0 4px 18px rgba(19,32,62,.055),0 1px 2px rgba(19,32,62,.04);
  --dy-shadow-hover:0 16px 34px rgba(38,52,92,.15),0 3px 8px rgba(38,52,92,.06);
  --dy-glow-a:rgba(56,189,248,.20);
  --dy-glow-b:rgba(167,139,250,.18);
  --dy-ok-bg:rgba(16,185,129,.10);
  --dy-ok-border:rgba(16,185,129,.28);
  --dy-ok-text:#0f8a63;
  --dy-good:#16a34a;
  --dy-bad:#dc2626;
  --dy-warn:#d97706;
  --dy-good-bg:rgba(22,163,74,.10);
  --dy-bad-bg:rgba(220,38,38,.10);
  --dy-warn-bg:rgba(217,119,6,.10);
  --dy-idle:#64748b;
  --dy-idle-bg:rgba(100,116,139,.10);
}
body.night{
  --dy-bg:#080d1a;
  --dy-surface:rgba(17,25,44,.78);
  --dy-solid:#121a2e;
  --dy-border:rgba(148,163,184,.16);
  --dy-border-strong:rgba(148,163,184,.28);
  --dy-text:#e8edf8;
  --dy-soft:#b6c2da;
  --dy-muted:#aebbd6;
  --dy-accent:#8b8bff;
  --dy-accent-2:#22d3ee;
  --dy-chip:rgba(139,139,255,.14);
  --dy-icon-bg:rgba(30,41,68,.9);
  --dy-shadow:0 8px 28px rgba(0,0,0,.28);
  --dy-shadow-hover:0 18px 38px rgba(0,0,0,.42);
  --dy-glow-a:rgba(34,211,238,.16);
  --dy-glow-b:rgba(139,92,246,.18);
  --dy-ok-bg:rgba(52,211,153,.12);
  --dy-ok-border:rgba(52,211,153,.30);
  --dy-ok-text:#6ee7b7;
  --dy-good:#4ade80;
  --dy-bad:#f87171;
  --dy-warn:#fbbf24;
  --dy-good-bg:rgba(74,222,128,.13);
  --dy-bad-bg:rgba(248,113,113,.13);
  --dy-warn-bg:rgba(251,191,36,.13);
  --dy-idle:#94a3b8;
  --dy-idle-bg:rgba(148,163,184,.14);
}
html{scroll-behavior:smooth}
body{
  margin:0;
  font-family:var(--dy-font);
  color:var(--dy-text);
  background:var(--dy-bg);
  background-image:
    radial-gradient(900px 600px at 8% -8%,var(--dy-glow-a),transparent 62%),
    radial-gradient(800px 560px at 96% 4%,var(--dy-glow-b),transparent 60%);
  background-attachment:fixed;
  line-height:1.65;
  -webkit-font-smoothing:antialiased;
}
a{color:inherit;text-decoration:none}
.dy-top{
  position:sticky;top:0;z-index:20;
  display:flex;align-items:center;gap:14px;
  padding:10px clamp(16px,4vw,42px);
  background:var(--dy-surface);
  border-bottom:1px solid var(--dy-border);
  backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
}
.dy-back{display:flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--dy-soft)}
.dy-back:hover{color:var(--dy-accent)}
.dy-back svg{width:15px;height:15px}
.dy-brand{font-size:12.5px;color:var(--dy-muted);padding-left:14px;border-left:1px solid var(--dy-border)}
.dy-top-spacer{flex:1}
.dy-top-link,.dy-theme{
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 11px;border-radius:999px;
  border:1px solid var(--dy-border-strong);
  background:transparent;color:var(--dy-soft);
  font:600 12px var(--dy-font);cursor:pointer;
}
.dy-top-link:hover,.dy-theme:hover{color:var(--dy-accent);border-color:var(--dy-accent)}
.dy-top-link svg,.dy-theme svg{width:14px;height:14px;fill:currentColor}
.dy-wrap{max-width:1080px;margin:0 auto;padding:0 clamp(16px,4vw,42px) 72px}
.dy-hero{padding:clamp(38px,6vw,68px) 0 30px}
.dy-kicker{
  display:inline-block;padding:4px 11px;border-radius:999px;
  background:var(--dy-chip);color:var(--dy-accent);
  font-size:11.5px;font-weight:700;letter-spacing:.04em;
}
.dy-hero h1{
  margin:16px 0 10px;font-size:clamp(28px,4.6vw,44px);
  line-height:1.2;letter-spacing:-.02em;font-weight:800;
  background:linear-gradient(100deg,var(--dy-accent),var(--dy-accent-2));
  -webkit-background-clip:text;background-clip:text;color:transparent;
}
.dy-hero p{margin:0;max-width:720px;color:var(--dy-soft);font-size:14.5px}
.dy-stats{display:flex;flex-wrap:wrap;gap:10px;margin-top:24px}
.dy-stat{
  flex:1 1 150px;min-width:130px;padding:13px 16px;
  border:1px solid var(--dy-border);border-radius:14px;
  background:var(--dy-surface);box-shadow:var(--dy-shadow);
}
.dy-stat span{display:block;font-size:11.5px;color:var(--dy-muted)}
.dy-stat strong{display:block;margin-top:2px;font-size:21px;line-height:1.3;font-weight:750}
.dy-rssbar{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin:8px 0 6px;padding:12px 16px;
  border:1px dashed var(--dy-border-strong);border-radius:12px;
  font-size:12.5px;color:var(--dy-muted);
}
.dy-rssbar code{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  color:var(--dy-soft);background:var(--dy-chip);padding:2px 7px;border-radius:6px;
  word-break:break-all;
}
.dy-rssbar a{color:var(--dy-accent);font-weight:650}
.dy-feed-links{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-top:9px}
.dy-feed-links .dy-flabel{font-size:11.5px;font-weight:700;color:var(--dy-muted)}
.dy-feed-chip{
  display:inline-flex;align-items:center;gap:5px;
  padding:4px 11px;border-radius:999px;
  border:1px solid var(--dy-border-strong);background:var(--dy-solid);
  font-size:11.5px;font-weight:650;color:var(--dy-soft);
}
.dy-feed-chip svg{width:12px;height:12px;fill:currentColor}
.dy-feed-chip:hover{color:var(--dy-accent);border-color:var(--dy-accent)}
/* AI 发现知识库：方向标签云 + 站内搜索（与按类型订阅正交） */
.dy-kb{
  margin:22px 0 4px;padding:16px 18px;border-radius:14px;
  border:1px solid var(--dy-border);background:var(--dy-surface);
  box-shadow:var(--dy-shadow);
}
.dy-kb-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:12px}
.dy-kb-title{font-size:13.5px;font-weight:750}
.dy-kb-hint{font-size:11px;color:var(--dy-muted)}
.dy-search{
  display:flex;align-items:center;gap:7px;margin-left:auto;
  padding:6px 11px;border-radius:999px;
  border:1px solid var(--dy-border-strong);background:var(--dy-solid);
  color:var(--dy-soft);
}
.dy-search svg{width:14px;height:14px;fill:currentColor;flex:0 0 auto}
.dy-search input{
  border:0;outline:0;background:transparent;color:var(--dy-text);
  font:500 12.5px var(--dy-font);width:150px;
}
.dy-search input::placeholder{color:var(--dy-muted)}
.dy-search:focus-within{border-color:var(--dy-accent);box-shadow:0 0 0 3px var(--dy-chip)}
.dy-tagcloud{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.dy-tagbtn{
  display:inline-flex;align-items:center;gap:6px;
  padding:5px 11px;border-radius:999px;
  border:1px solid var(--dy-border-strong);background:var(--dy-solid);
  color:var(--dy-soft);font:600 11.5px var(--dy-font);cursor:pointer;
  transition:background .15s ease,color .15s ease,border-color .15s ease;
}
.dy-tagbtn:hover{color:var(--dy-accent);border-color:var(--dy-accent)}
.dy-tagbtn .dy-tagn{font-size:10px;color:var(--dy-muted);font-weight:700}
.dy-tagbtn.active{background:var(--dy-accent);border-color:var(--dy-accent);color:#fff}
.dy-tagbtn.active .dy-tagn{color:rgba(255,255,255,.85)}
body.night .dy-tagbtn.active{color:#0b1020}
.dy-kb-status{margin-top:10px;font-size:11.5px;color:var(--dy-muted);min-height:1.2em}
.dy-kb-status b{color:var(--dy-accent)}
.dy-topic{
  display:inline-block;margin:2px 4px 5px 0;padding:1px 7px;border-radius:5px;
  background:var(--dy-icon-bg);border:1px solid var(--dy-border);
  color:var(--dy-soft);font-size:10px;font-weight:600;
}
.dy-card.filtered-out,.dy-day.filtered-out{display:none}
.dy-cards:empty::after{
  content:"当前筛选条件下没有匹配的站点";display:block;
  padding:18px;color:var(--dy-muted);font-size:12.5px;
}
@media (max-width:600px){
  .dy-search{margin-left:0;width:100%}
  .dy-search input{flex:1;width:auto}
}
.dy-timeline{position:relative;margin-top:34px;padding-left:26px}
.dy-timeline::before{
  content:"";position:absolute;left:6px;top:8px;bottom:8px;width:2px;
  background:linear-gradient(180deg,var(--dy-accent),var(--dy-accent-2),transparent);
  opacity:.45;border-radius:2px;
}
.dy-day{position:relative;margin-bottom:38px;scroll-margin-top:76px}
.dy-day::before{
  content:"";position:absolute;left:-26px;top:9px;width:14px;height:14px;
  border-radius:50%;background:var(--dy-solid);
  border:3px solid var(--dy-accent);box-shadow:0 0 0 4px var(--dy-chip);
}
.dy-day-head{display:flex;align-items:baseline;gap:11px;flex-wrap:wrap;margin-bottom:14px}
.dy-day-head h2{margin:0;font-size:19px;font-weight:750;letter-spacing:-.01em}
.dy-week{font-size:12.5px;color:var(--dy-muted)}
.dy-count{
  padding:2px 9px;border-radius:999px;background:var(--dy-chip);
  color:var(--dy-accent);font-size:11px;font-weight:700;
}
.dy-cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(268px,1fr));gap:12px}
.dy-card{
  display:flex;gap:12px;padding:15px;
  border:1px solid var(--dy-border);border-radius:14px;
  background:var(--dy-surface);box-shadow:var(--dy-shadow);
  transition:transform .18s ease,box-shadow .18s ease,border-color .18s ease;
}
.dy-card:hover{transform:translateY(-3px);box-shadow:var(--dy-shadow-hover);border-color:var(--dy-accent)}
.dy-icon{
  position:relative;flex:0 0 38px;width:38px;height:38px;border-radius:10px;
  background:var(--dy-icon-bg);overflow:hidden;
  display:flex;align-items:center;justify-content:center;
}
.dy-icon img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;padding:5px}
.dy-initial{font-size:16px;font-weight:750;color:var(--dy-accent)}
.dy-card-body{min-width:0;flex:1}
.dy-card-name{
  display:block;font-size:14px;font-weight:700;line-height:1.4;
  overflow-wrap:anywhere;
}
.dy-card:hover .dy-card-name{color:var(--dy-accent)}
.dy-tag{
  display:inline-block;margin:6px 0 5px;padding:1px 8px;border-radius:6px;
  background:var(--dy-chip);color:var(--dy-accent);font-size:10.5px;font-weight:650;
}
.dy-desc{margin:0;font-size:12.5px;color:var(--dy-soft);line-height:1.6}
/* 收录质量回执：卡片「已核验」徽章 + 页顶漏斗条 */
.dy-verify{
  display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;
  margin-top:9px;padding:2px 8px;border-radius:6px;
  border:1px solid var(--dy-ok-border);background:var(--dy-ok-bg);
  color:var(--dy-ok-text);font-size:10.5px;font-weight:650;line-height:1.5;
  cursor:help;
}
.dy-verify b{font-weight:750}
.dy-receipt{
  margin:22px 0 4px;padding:16px 18px;border-radius:14px;
  border:1px solid var(--dy-border);background:var(--dy-surface);
  box-shadow:var(--dy-shadow);
}
.dy-receipt-head{display:flex;align-items:center;gap:9px;flex-wrap:wrap;margin-bottom:10px}
.dy-receipt-title{font-size:13.5px;font-weight:750}
.dy-receipt-date{font-size:11px;color:var(--dy-muted)}
.dy-receipt-flow{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:12.5px;color:var(--dy-soft)}
.dy-receipt-node{
  padding:3px 10px;border-radius:8px;background:var(--dy-chip);
  color:var(--dy-accent);font-weight:700;
}
.dy-receipt-node.ok{border:1px solid var(--dy-ok-border);background:var(--dy-ok-bg);color:var(--dy-ok-text)}
.dy-receipt-arrow{color:var(--dy-muted);font-size:12px}
.dy-receipt-meta{margin-top:10px;font-size:11.5px;color:var(--dy-muted);line-height:1.7}
.dy-receipt-meta a{color:var(--dy-accent);font-weight:650}
/* 站点健康度：卡片小圆点 + 页顶汇总条（低频复检，非每日收录） */
.dy-health{
  display:inline-flex;align-items:center;gap:5px;
  margin-top:7px;padding:1px 8px;border-radius:999px;
  font-size:10px;font-weight:650;line-height:1.6;cursor:help;
}
.dy-health i{width:6px;height:6px;border-radius:50%;display:inline-block;flex:0 0 auto}
.dy-health.ok{color:var(--dy-good);background:var(--dy-good-bg)}
.dy-health.ok i{background:var(--dy-good)}
.dy-health.down{color:var(--dy-bad);background:var(--dy-bad-bg)}
.dy-health.down i{background:var(--dy-bad)}
.dy-health.unverified{color:var(--dy-warn);background:var(--dy-warn-bg)}
.dy-health.unverified i{background:var(--dy-warn)}
/* 站点新鲜度徽章：基于 pushed_at 的活跃度信号，与「站点健康度」正交
   （健康度问站是否可访问，新鲜度问项目最近有没有提交）。 */
.dy-fresh{
  display:inline-flex;align-items:center;gap:5px;
  margin-top:7px;padding:1px 8px;border-radius:999px;
  font-size:10px;font-weight:650;line-height:1.6;cursor:help;
}
.dy-fresh i{width:6px;height:6px;border-radius:50%;display:inline-block;flex:0 0 auto}
.dy-fresh.active{color:var(--dy-good);background:var(--dy-good-bg)}
.dy-fresh.active i{background:var(--dy-good);box-shadow:0 0 0 3px var(--dy-good-bg)}
.dy-fresh.recent{color:var(--dy-warn);background:var(--dy-warn-bg)}
.dy-fresh.recent i{background:var(--dy-warn)}
.dy-fresh.idle{color:var(--dy-idle);background:var(--dy-idle-bg)}
.dy-fresh.idle i{background:var(--dy-idle)}
.dy-card.dy-down{opacity:.62}
.dy-card.dy-down:hover{opacity:1}
.dy-healthbar{
  display:flex;align-items:center;gap:10px;flex-wrap:wrap;
  margin:22px 0 4px;padding:13px 18px;border-radius:14px;
  border:1px solid var(--dy-border);background:var(--dy-surface);
  box-shadow:var(--dy-shadow);font-size:12.5px;color:var(--dy-soft);
}
.dy-healthbar-title{font-size:13.5px;font-weight:750;color:var(--dy-text)}
.dy-healthbar-metrics{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.dy-hmetric{
  display:inline-flex;align-items:center;gap:6px;
  padding:3px 10px;border-radius:8px;font-weight:650;
}
.dy-hmetric i{width:7px;height:7px;border-radius:50%;display:inline-block}
.dy-hmetric.ok{color:var(--dy-good);background:var(--dy-good-bg)}
.dy-hmetric.ok i{background:var(--dy-good)}
.dy-hmetric.down{color:var(--dy-bad);background:var(--dy-bad-bg)}
.dy-hmetric.down i{background:var(--dy-bad)}
.dy-hmetric.unverified{color:var(--dy-warn);background:var(--dy-warn-bg)}
.dy-hmetric.unverified i{background:var(--dy-warn)}
.dy-healthbar-time{margin-left:auto;font-size:11px;color:var(--dy-muted)}
.dy-healthbar-note{flex-basis:100%;font-size:11px;color:var(--dy-muted);line-height:1.6}
.dy-watch{
  margin:14px 0 4px;padding:14px 18px;border-radius:14px;
  border:1px solid var(--dy-border);background:var(--dy-surface);
  box-shadow:var(--dy-shadow);font-size:12.5px;color:var(--dy-soft);
}
.dy-watch-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.dy-watch-title{
  display:inline-flex;align-items:center;gap:7px;
  font-size:13.5px;font-weight:750;color:var(--dy-text)
}
.dy-watch-dot{
  width:8px;height:8px;border-radius:50%;display:inline-block;
  background:var(--dy-accent-2);box-shadow:0 0 0 3px rgba(6,182,212,.16)
}
.dy-watch-metrics{display:flex;align-items:center;gap:7px;flex-wrap:wrap}
.dy-wmetric{
  padding:3px 9px;border-radius:8px;font-size:11.5px;
  background:var(--dy-chip);color:var(--dy-soft)
}
.dy-wmetric b{color:var(--dy-accent);font-weight:750}
.dy-watch-time{margin-left:auto;font-size:11px;color:var(--dy-muted)}
.dy-watch-list{
  margin-top:11px;display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:7px
}
.dy-witem{
  display:flex;align-items:center;gap:8px;flex-wrap:wrap;
  padding:8px 11px;border-radius:9px;text-decoration:none;
  border:1px solid var(--dy-border);background:var(--dy-icon-bg);
  transition:border-color .18s,transform .18s
}
.dy-witem:hover{border-color:var(--dy-accent-2);transform:translateY(-1px)}
.dy-witem-name{
  font-weight:650;color:var(--dy-text);font-size:12px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:150px
}
.dy-witem-badges{display:inline-flex;gap:5px;flex-wrap:wrap}
.dy-wtag{
  padding:2px 7px;border-radius:6px;font-size:10.5px;font-weight:700;white-space:nowrap
}
.dy-wtag.push{color:var(--dy-accent);background:var(--dy-chip)}
.dy-wtag.star{color:var(--dy-good);background:var(--dy-good-bg)}
.dy-witem-date{margin-left:auto;font-size:10.5px;color:var(--dy-muted)}
.dy-watch-empty{
  margin-top:11px;padding:10px 12px;border-radius:9px;
  background:var(--dy-icon-bg);font-size:11.5px;color:var(--dy-muted);line-height:1.6
}
.dy-watch-note{margin-top:10px;font-size:11px;color:var(--dy-muted);line-height:1.6}
/* 项目动态速递：可排序的变更流（复用雷达 recent 数据） */
.dy-changes{margin:14px 0 4px;padding:14px 18px;border-radius:14px;
  border:1px solid var(--dy-border);background:var(--dy-surface);
  box-shadow:var(--dy-shadow);font-size:12.5px;color:var(--dy-soft)}
.dy-changes-head{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.dy-changes-title{
  display:inline-flex;align-items:center;gap:7px;
  font-size:13.5px;font-weight:750;color:var(--dy-text)
}
.dy-changes-sorts{display:inline-flex;gap:5px;flex-wrap:wrap;align-items:center}
.dy-changes-sorts-label{font-size:11px;color:var(--dy-muted)}
.dy-sort-btn{
  padding:3px 10px;border-radius:8px;font-size:11px;font-weight:650;cursor:pointer;
  border:1px solid var(--dy-border);background:var(--dy-icon-bg);color:var(--dy-soft);
  transition:border-color .18s,color .18s,background .18s
}
.dy-sort-btn:hover{border-color:var(--dy-accent-2)}
.dy-sort-btn.active{
  color:var(--dy-accent);border-color:var(--dy-accent);background:var(--dy-chip)
}
.dy-changes-time{margin-left:auto;font-size:11px;color:var(--dy-muted)}
.dy-changes-list{margin-top:11px;display:flex;flex-direction:column;gap:6px}
.dy-change{
  display:flex;align-items:center;gap:9px;flex-wrap:wrap;
  padding:9px 12px;border-radius:9px;text-decoration:none;
  border:1px solid var(--dy-border);background:var(--dy-icon-bg);
  transition:border-color .18s,background .18s
}
.dy-change:hover{border-color:var(--dy-accent-2);background:var(--dy-chip)}
.dy-change-rank{
  min-width:22px;font-size:11px;font-weight:750;color:var(--dy-muted);text-align:center
}
.dy-change-name{
  font-weight:650;color:var(--dy-text);font-size:12px;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:260px
}
.dy-change-cat{
  padding:2px 7px;border-radius:6px;font-size:10px;font-weight:650;white-space:nowrap;
  color:var(--dy-muted);background:var(--dy-chip)
}
.dy-change-metrics{display:inline-flex;gap:8px;align-items:center;flex-wrap:wrap}
.dy-change-metric{font-size:11px;font-weight:700;white-space:nowrap}
.dy-change-metric.push{color:var(--dy-accent)}
.dy-change-metric.star{color:var(--dy-good)}
.dy-change-date{margin-left:auto;font-size:10.5px;color:var(--dy-muted);white-space:nowrap}
.dy-changes-note{margin-top:10px;font-size:11px;color:var(--dy-muted);line-height:1.6}
.dy-changes-empty{
  margin-top:11px;padding:10px 12px;border-radius:9px;
  background:var(--dy-icon-bg);font-size:11.5px;color:var(--dy-muted);line-height:1.6
}
.dy-footer{
  margin-top:46px;padding-top:20px;border-top:1px solid var(--dy-border);
  font-size:12px;color:var(--dy-muted);
}
.dy-footer a{color:var(--dy-accent)}
.dy-empty{padding:26px;border:1px dashed var(--dy-border-strong);border-radius:14px;color:var(--dy-muted)}
@media (max-width:600px){
  .dy-brand{display:none}
  .dy-top{padding:10px 16px;gap:9px}
  .dy-cards{grid-template-columns:1fr}
  .dy-timeline{padding-left:20px}
  .dy-day::before{left:-20px}
}
@media (prefers-reduced-motion:reduce){
  *{scroll-behavior:auto!important;transition:none!important}
}
/* 设计稿 03 号板：赛博态统一设计 token（与首页同一套本地字体）。
   经典态不覆盖任何规则，仍是原来的浅色控制台。 */
@font-face{font-family:"CM Orbitron";src:url("/fonts/cm-orbitron-latin.woff2") format("woff2");font-style:normal;font-weight:400 900;font-display:swap}
@font-face{font-family:"CM Chakra";src:url("/fonts/cm-chakra-600-latin.woff2") format("woff2");font-style:normal;font-weight:600;font-display:swap}
@font-face{font-family:"CM Mono";src:url("/fonts/cm-jetbrains-latin.woff2") format("woff2");font-style:normal;font-weight:400 700;font-display:swap}
body.night{
  --dy-bg:#05070b;
  --dy-surface:rgba(11,18,27,.82);
  --dy-solid:#0b121b;
  --dy-border:rgba(18,48,63,.9);
  --dy-border-strong:#12303f;
  --dy-text:#e6f5ff;
  --dy-soft:#b7c9df;
  --dy-muted:#8ba0bd;
  --dy-accent:#00e5ff;
  --dy-accent-2:#ff2ea6;
  --dy-chip:rgba(0,229,255,.12);
  --dy-icon-bg:rgba(12,26,38,.78);
  --dy-glow-a:rgba(0,229,255,.12);
  --dy-glow-b:rgba(255,46,166,.09);
  --dy-good:#39ff88;
  --dy-good-bg:rgba(57,255,136,.10);
  --dy-bad:#ff2ea6;
  --dy-bad-bg:rgba(255,46,166,.10);
  --dy-warn:#ffb020;
  --dy-warn-bg:rgba(255,176,32,.10);
}
body.night::after{
  content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;
  background:repeating-linear-gradient(180deg,rgba(127,239,255,.02) 0 1px,transparent 1px 4px)
}
body.night .dy-top{
  border-bottom:1px solid rgba(0,229,255,.22);
  background:rgba(7,14,23,.88);
}
body.night .dy-hero::before{
  content:"SECTION 03 // DAILY INTEL FEED   ·   VERIFIED DAILY DISCOVERIES";
  display:block;margin-bottom:14px;padding-bottom:7px;
  border-bottom:1px solid var(--dy-border);
  font-family:"CM Mono",monospace;font-size:10.5px;letter-spacing:.12em;
  color:var(--dy-accent);
}
body.night .dy-kicker{
  border-radius:3px;font-family:"CM Mono",monospace;letter-spacing:.14em
}
body.night .dy-hero h1{
  font-family:"CM Chakra",sans-serif;font-size:clamp(32px,4.2vw,48px);letter-spacing:-.02em
}
body.night .dy-hero p{font-family:"CM Chakra",sans-serif;font-size:13.5px}
body.night .dy-stats{gap:8px}
body.night .dy-stat{border-radius:3px}
body.night .dy-stat span{font-family:"CM Mono",monospace;font-size:9.5px;letter-spacing:.06em}
body.night .dy-stat strong{
  font-family:"CM Orbitron",sans-serif;font-size:23px;font-weight:900;color:var(--dy-accent)
}
body.night .dy-receipt,body.night .dy-healthbar,body.night .dy-watch,
body.night .dy-changes,body.night .dy-tagcloud,body.night .dy-search,
body.night .dy-rssbar{border-radius:3px}
body.night .dy-day-head{
  font-family:"CM Mono",monospace;color:var(--dy-accent);letter-spacing:.04em
}
body.night .dy-card{border-radius:3px}
body.night .dy-tagbtn,body.night .dy-feed-chip,body.night .dy-sort-btn{border-radius:3px}
body.night .dy-wtag.star{color:#39ff88;background:rgba(57,255,136,.10)}
body.night .dy-wmetric b{font-family:"CM Orbitron",sans-serif;font-weight:900;color:var(--dy-accent)}
/* 05 号板动效编排：HUD → 标题 → 副题 → 统计，同一条缓动曲线 */
@keyframes dy-token-in{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:none}}
body.night .dy-hero::before,body.night .dy-kicker,body.night .dy-hero h1,
body.night .dy-hero p,body.night .dy-stats{animation:dy-token-in .55s cubic-bezier(.16,1,.3,1) both}
body.night .dy-hero::before{animation-delay:.02s}
body.night .dy-kicker{animation-delay:.08s}
body.night .dy-hero h1{animation-delay:.14s}
body.night .dy-hero p{animation-delay:.20s}
body.night .dy-stats{animation-delay:.26s}
/* 03 号板：知识库区左右分栏——左侧时间轴，右侧方向标签与筛选状态 */
body.night .dy-kb{
  display:grid;grid-template-columns:minmax(0,1fr) 500px;
  gap:18px 24px;align-items:start
}
body.night .dy-kb-head{grid-column:1 / span 2}
body.night .dy-timeline{grid-column:1;grid-row:2}
body.night .dy-tagcloud{grid-column:2;grid-row:2;align-self:start}
body.night .dy-kb-status{grid-column:2;grid-row:3;align-self:start}
@media (max-width:991px){
  body.night .dy-kb{display:block}
}
@media (prefers-reduced-motion:reduce){
  body.night::after{background:none}
  body.night .dy-hero::before,body.night .dy-kicker,body.night .dy-hero h1,
  body.night .dy-hero p,body.night .dy-stats{animation:none!important}
}
"""

JS = r"""
(function(){
  var body=document.body;
  function isNight(){return /(?:^|;\s*)night=1(?:;|$)/.test(document.cookie);}
  function apply(){
    var cyber=isNight();
    body.classList.toggle('night',cyber);
    var b=document.getElementById('dy-theme');
    if(b){
      b.setAttribute('data-skin',cyber?'cyber':'classic');
      b.title=cyber?'当前：赛博模式 CYBER · 点击切换为经典模式':'当前：经典模式 CLASSIC · 点击切换为赛博模式';
      b.setAttribute('aria-label',b.title);
    }
  }
  apply();
  var btn=document.getElementById('dy-theme');
  if(btn){btn.addEventListener('click',function(){
    document.cookie=(isNight()?'night=0':'night=1')+';path=/;max-age=31536000';
    apply();
  });}
  // favicon 取不到时移除 <img>，露出底下的首字母占位
  Array.prototype.forEach.call(document.querySelectorAll('.dy-icon img'),function(img){
    img.addEventListener('error',function(){if(img.parentNode)img.parentNode.removeChild(img);});
  });
  // ---- AI 发现知识库：方向标签筛选 + 站内搜索（与按类型订阅正交） ----
  var kb=document.querySelector('.dy-kb');
  if(kb){
    var cards=Array.prototype.slice.call(document.querySelectorAll('.dy-card'));
    var days=Array.prototype.slice.call(document.querySelectorAll('.dy-day'));
    var tagbtns=Array.prototype.slice.call(kb.querySelectorAll('.dy-tagbtn'));
    var search=document.getElementById('dy-search');
    var status=document.getElementById('dy-kb-status');
    var activeTag='';
    function norm(s){return (s||'').toLowerCase();}
    function applyFilter(){
      var q=norm(search?search.value.trim():'');
      var shown=0;
      cards.forEach(function(card){
        var tags=norm(card.getAttribute('data-tags'));
        var hay=norm(card.getAttribute('data-search'));
        var tagOk=!activeTag||(' '+tags+' ').indexOf(' '+activeTag+' ')>-1;
        var searchOk=!q||hay.indexOf(q)>-1;
        var ok=tagOk&&searchOk;
        card.classList.toggle('filtered-out',!ok);
        if(ok)shown++;
      });
      // 某天下所有卡片都被过滤掉时，连同日期标题一起隐藏
      days.forEach(function(day){
        var any=Array.prototype.some.call(day.querySelectorAll('.dy-card'),function(c){
          return !c.classList.contains('filtered-out');
        });
        day.classList.toggle('filtered-out',!any);
      });
      if(status){
        status.innerHTML='显示 <b>'+shown+'</b> / '+cards.length+' 个站点'+
          (activeTag?' · 方向「'+activeTag+'」':'')+(q?' · 搜索「'+q+'」':'');
      }
    }
    tagbtns.forEach(function(btn){
      btn.addEventListener('click',function(){
        var tag=btn.getAttribute('data-tag')||'';
        if(activeTag===tag){activeTag='';}else{activeTag=tag;}
        tagbtns.forEach(function(b){b.classList.toggle('active',(b.getAttribute('data-tag')||'')===activeTag);});
        applyFilter();
      });
    });
    if(search){search.addEventListener('input',applyFilter);}
  }
  // ---- 项目动态速递：按涨星 / 新提交 / 日期排序（纯前端，不改数据） ----
  var chg=document.querySelector('.dy-changes');
  if(chg){
    var list=chg.querySelector('.dy-changes-list');
    var rows=list?Array.prototype.slice.call(list.querySelectorAll('.dy-change')):[];
    var btns=Array.prototype.slice.call(chg.querySelectorAll('.dy-sort-btn'));
    var current=chg.getAttribute('data-default-sort')||'star';
    function resort(){
      rows.sort(function(a,b){
        var av=parseInt(a.getAttribute('data-'+current)||'0',10);
        var bv=parseInt(b.getAttribute('data-'+current)||'0',10);
        if(av!==bv)return bv-av;
        // 同值时按日期新到旧，再按项目名稳定排序
        var ad=a.getAttribute('data-date')||'',bd=b.getAttribute('data-date')||'';
        if(ad!==bd)return bd>ad?1:-1;
        return (a.getAttribute('data-name')||'').localeCompare(b.getAttribute('data-name')||'');
      });
      rows.forEach(function(r,i){
        var rank=r.querySelector('.dy-change-rank');
        if(rank)rank.textContent=i+1;
        list.appendChild(r);
      });
    }
    btns.forEach(function(btn){
      btn.addEventListener('click',function(){
        current=btn.getAttribute('data-sort')||'star';
        btns.forEach(function(b){b.classList.toggle('active',b===btn);});
        resort();
      });
    });
    if(rows.length)resort();
  }
})();
"""

ICON_BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5M11 18l-6-6 6-6"/></svg>'
ICON_RSS = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 11a9 9 0 0 1 9 9h-3a6 6 0 0 0-6-6v-3zm0-6a15 15 0 0 1 15 15h-3A12 12 0 0 0 4 8V5zm1.8 12.2a2 2 0 1 1 0 4 2 2 0 0 1 0-4z"/></svg>'
ICON_MOON = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12.3 3a9 9 0 1 0 8.7 11.4A7.2 7.2 0 0 1 12.3 3z"/></svg>'
ICON_SEARCH = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M15.5 14h-.8l-.3-.3a6.5 6.5 0 1 0-.7.7l.3.3v.8l5 5 1.5-1.5-5-5zm-6 0a4.5 4.5 0 1 1 0-9 4.5 4.5 0 0 1 0 9z"/></svg>'


# ---------------------------------------------------------------- 数据读取
def esc(value) -> str:
    """所有来自 YAML / JSON 的文本统一转义，避免破坏 HTML 结构。"""
    return html.escape(str(value if value is not None else ""), quote=True)


def norm_url(url: str) -> str:
    """与 cybermap.py::norm 完全一致，用于按 URL 命中验证证据。"""
    from urllib.parse import urlparse
    raw = (url or "").strip().rstrip(",;'\"")
    p = urlparse(raw if "://" in raw else "https://" + raw)
    host = (p.hostname or "").lower().removeprefix("www.")
    path = (p.path or "/").rstrip("/").lower() or "/"
    if path.endswith(".git"):
        path = path[:-4]
    return f"{host}{path}"


def infer_tags(name: str, description: str) -> list[str]:
    """根据名称+描述推断方向标签，返回按规则优先级排序的标签列表。

    纯文本匹配、幂等：同样输入永远得到同样标签。全不命中时给 AI 应用兜底，
    保证每张卡片至少有一个可筛选的标签。
    """
    text = f"{name} {description}"
    hits = [label for label, pattern in TAG_RULE_PATTERNS if pattern.search(text)]
    return hits[:MAX_TAGS_PER_ITEM] or [FALLBACK_TAG]


def build_tag_cloud(entries: list[dict]) -> list[tuple[str, int]]:
    """统计全站条目的方向标签命中数，按数量降序、同数按规则表顺序。"""
    counter: dict[str, int] = {}
    for item in entries:
        for tag in item["tags"]:
            counter[tag] = counter.get(tag, 0) + 1
    order = {label: i for i, (label, _) in enumerate(TAG_RULES)}
    return sorted(counter.items(), key=lambda kv: (-kv[1], order.get(kv[0], 999)))


def load_verify(path: Path) -> tuple[dict, list[str]]:
    """读取收录质量回执数据。文件缺失/损坏时返回空数据（优雅降级，不阻断生成）。"""
    if not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("evidence"), dict):
            raise ValueError("verify.json 结构不完整")
        return data, data.get("warnings") or []
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, [f"verify.json 读取失败，已降级为无徽章模式：{exc}"]


def load_health(path: Path) -> tuple[dict, list[str]]:
    """读取站点健康复检数据。文件缺失/损坏时返回空数据（优雅降级，不显示健康模块）。"""
    if not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("sites"), dict):
            raise ValueError("health.json 结构不完整")
        return data, []
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, [f"health.json 读取失败，已跳过健康模块：{exc}"]


def load_updates(path: Path) -> tuple[dict, list[str]]:
    """读取上游变更雷达数据。文件缺失/损坏时返回空数据（优雅降级，不显示雷达模块）。"""
    if not path.is_file():
        return {}, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
            raise ValueError("updates.json 结构不完整")
        return data, []
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return {}, [f"updates.json 读取失败，已跳过上游变更雷达：{exc}"]


def load_entries(data_file: Path) -> tuple[list[dict], list[str]]:
    """返回 (条目列表, 警告列表)。条目按分类顺序、分类内原始顺序排列。"""
    if not data_file.is_file():
        raise FileNotFoundError(f"数据文件不存在：{data_file}")
    try:
        data = yaml.safe_load(data_file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"webstack.yml 解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("webstack.yml 顶层不是映射")

    entries, warnings = [], []
    for cat, (label, short) in CATEGORY_LABELS.items():
        block = data.get(cat)
        if block is None:
            warnings.append(f"分类 {cat} 不存在，按空处理")
            continue
        if not isinstance(block, list):
            raise ValueError(f"分类 {cat} 不是列表")
        for raw in block:
            if not isinstance(raw, dict):
                warnings.append(f"分类 {cat} 中有非映射条目，已跳过")
                continue
            name, url = raw.get("name"), raw.get("url")
            if not name or not url:
                warnings.append(f"分类 {cat} 中缺少 name/url，已跳过")
                continue
            desc = str(raw.get("description") or "").strip()
            match = DATE_TAG_RE.search(desc)
            day = match.group(1) if match else None
            if day:
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                except ValueError:
                    day, match = None, None
                    warnings.append(f"{name} 的日期尾注非法，归入早期收录")
            clean_desc = DATE_TAG_RE.sub("", desc).strip().rstrip("·").strip() if match else desc
            entries.append({
                "name": str(name),
                "url": str(url),
                "img": str(raw.get("img") or ""),
                "description": clean_desc,
                "category": cat,
                "label": label,
                "short": short,
                "day": day,
                "tags": infer_tags(str(name), clean_desc),
            })
    return entries, warnings


def group_by_day(entries: list[dict]):
    """按日期倒序分组；无日期的放到最后的「早期收录」。"""
    dated: dict[str, list[dict]] = {}
    undated = []
    for item in entries:
        if item["day"]:
            dated.setdefault(item["day"], []).append(item)
        else:
            undated.append(item)
    days = [(d, dated[d]) for d in sorted(dated, reverse=True)]
    return days, undated


# ---------------------------------------------------------------- HTML 生成
def day_heading(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d").date()
    return f"{d.year} 年 {d.month} 月 {d.day} 日", WEEKDAYS[d.weekday()]


def short_stars(n) -> str:
    """24188 → 24.2k，便于徽章里紧凑展示。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return ""
    return f"{v / 1000:.1f}k" if v >= 1000 else str(v)


def badge_html(item: dict, evidence: dict) -> str:
    """卡片上的「已核验」徽章：紧凑摘要 + title 悬停展开完整证据。"""
    ev = evidence.get(norm_url(item["url"]))
    if not ev or ev.get("verdict") != "pass":
        return ""
    bits = ["✓ 已核验"]
    if ev.get("http_status"):
        bits.append(f"HTTP {ev['http_status']}")
    stars = short_stars(ev.get("stars"))
    if stars:
        bits.append(f"★{stars}")
    if ev.get("ai_hits"):
        bits.append(f"AI×{ev['ai_hits']}")
    label = " · ".join(bits)

    details = [
        f"核验日期：{ev.get('date') or '—'}",
        f"HTTP 状态：{ev.get('http_status') or '—'}",
        f"页面标题：{ev.get('title') or '—'}",
    ]
    if ev.get("stars") is not None:
        details.append(f"GitHub stars：{ev['stars']}")
    if ev.get("pushed_at"):
        details.append(f"最近推送：{ev['pushed_at']}")
    if ev.get("license"):
        details.append(f"开源协议：{ev['license']}")
    if ev.get("ai_keywords"):
        details.append("AI 关键词命中：" + ", ".join(str(x) for x in ev["ai_keywords"]))
    if ev.get("checked_at"):
        details.append(f"核验时间：{ev['checked_at']}")
    details.append("判定：pass（可访问 / AI 相关 / 未重复）")
    return (
        f'<span class="dy-verify" title="{esc("；".join(details))}">'
        f'<b>{esc(bits[0])}</b>'
        + (" · " + esc(" · ".join(bits[1:])) if len(bits) > 1 else "")
        + "</span>"
    )


# ---------------------------------------------------------------- 站点新鲜度
# 回答「项目最近动了吗」，与 health（站是否可访问）正交。数据来自
# updates.json.repos[norm_url].pushed_at（真实最近提交）与 verify.json 的
# checked_at（核验时间）。三档阈值：7 天内活跃 / 90 天内近期 / 更久沉寂。
FRESH_ACTIVE_DAYS = 7
FRESH_IDLE_DAYS = 90


def parse_iso_dt(value: str):
    """解析 ISO 8601 时间为带时区的 datetime；兼容 Z 后缀与无时区的朴素串。"""
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def freshness_label(pushed_at, now: datetime) -> tuple[str, str, int | None] | None:
    """根据 pushed_at 与参考时间算出 (档位, 文案, 天数)。

    返回 None 表示无有效 pushed_at，调用方不渲染徽章（不猜测、不伪造）。
    """
    pushed = parse_iso_dt(pushed_at)
    if pushed is None:
        return None
    days = max(0, (now - pushed).days)
    if days < FRESH_ACTIVE_DAYS:
        return "active", "本周活跃", days
    if days < FRESH_IDLE_DAYS:
        months = days // 30
        return "recent", f"{months} 月前更新" if months else f"{days} 天前更新", days
    months = days // 30
    return "idle", f"沉寂 {months} 月", days


def freshness_badge_html(item: dict, updates: dict, evidence: dict,
                         now: datetime) -> str:
    """卡片新鲜度微徽章：三档文案 + title 悬停看提交与核验时间。

    只对有真实 pushed_at 的已跟踪 GitHub 项目渲染；工具官网 / 未纳入雷达
    的仓库不显示，避免把「没数据」误读成「沉寂」。
    """
    rec = (updates.get("repos") or {}).get(norm_url(item["url"]))
    if not rec:
        return ""
    result = freshness_label(rec.get("pushed_at"), now)
    if not result:
        return ""
    level, label, days = result
    pushed_at = rec.get("pushed_at") or "—"
    checked_at = rec.get("last_checked") or "—"
    ev = evidence.get(norm_url(item["url"])) or {}
    if ev.get("checked_at"):
        checked_at = f"{checked_at}（收录核验 {ev['checked_at']}）"
    title = (
        f"最近提交：{pushed_at}（距今约 {days} 天）；"
        f"雷达采集：{checked_at}。数据来自 /daily/updates.json，非实时。"
    )
    return (
        f'<span class="dy-fresh {level}" title="{esc(title)}">'
        f'<i></i>{esc(label)}</span>'
    )


HEALTH_STATUS_TEXT = {"ok": "持续在线", "down": "疑似失效", "unverified": "待核对"}


def health_badge_html(item: dict, health: dict) -> str:
    """卡片健康小圆点：三态文案 + title 悬停看复检证据（含检查时间）。"""
    rec = health.get(norm_url(item["url"]))
    if not rec:
        return ""
    status = rec.get("status")
    if status not in HEALTH_STATUS_TEXT:
        return ""
    note = rec.get("note") or ""
    title = f"{HEALTH_STATUS_TEXT[status]}；复检记录：{note}（{rec.get('checked_at') or '—'}）"
    return (
        f'<span class="dy-health {status}" title="{esc(title)}">'
        f'<i></i>{esc(HEALTH_STATUS_TEXT[status])}</span>'
    )


def healthbar_html(health: dict) -> str:
    """页顶「站点健康度」汇总条：在线 / 疑似失效 / 待核对三态计数 + 复检时间。"""
    if not health:
        return ""
    summary = health.get("summary") or {}
    checked = summary.get("checked")
    if not checked:
        return ""
    metrics = "".join(
        f'<span class="dy-hmetric {key}"><i></i>{HEALTH_STATUS_TEXT[key]} '
        f'{summary.get(key, 0)}</span>'
        for key in ("ok", "down", "unverified")
    )
    generated = health.get("generated_at") or ""
    time_str = generated.replace("T", " ")[:16]
    return (
        '<section class="dy-healthbar" aria-label="站点健康度">'
        '<span class="dy-healthbar-title">站点健康度</span>'
        f'<span class="dy-healthbar-metrics">{metrics}</span>'
        f'<span class="dy-healthbar-time">复检 {esc(time_str)}</span>'
        '<span class="dy-healthbar-note">低频人工复检的结果，反映最近一次探测时的站点状态；'
        '「待核对」为本机网络策略不可判定（超时/代理/反爬），不代表站点失效。'
        '完整明细：<a href="/daily/health.json" style="color:var(--dy-accent);font-weight:650">/daily/health.json</a></span>'
        "</section>"
    )


def watchbar_html(updates: dict) -> str:
    """页顶「上游变更雷达」：展示最近 7 天已收录 GitHub 项目的提交/star 动态。

    与「站点健康度」正交：health 回答站是否还活着，本区块回答项目最近有没有更新。
    冷启动（只建基线、recent 为空）时显示覆盖率与建立进度提示，不伪造变更。
    """
    if not updates:
        return ""
    summary = updates.get("summary") or {}
    total = summary.get("total_repos") or 0
    tracked = summary.get("tracked") or 0
    if not total:
        return ""
    recent = updates.get("recent") or []
    generated = (updates.get("generated_at") or "").replace("T", " ")[:16]
    coverage = round(tracked / total * 100) if total else 0

    metrics = (
        f'<span class="dy-wmetric"><b>{tracked}</b>/{total} 项目</span>'
        f'<span class="dy-wmetric"><b>{len(recent)}</b> 项近期动态</span>'
        f'<span class="dy-wmetric">覆盖 {coverage}%</span>'
    )

    if recent:
        rows = []
        for r in recent:
            badges = []
            if r.get("has_push"):
                badges.append('<span class="dy-wtag push">新提交</span>')
            if r.get("star_delta"):
                badges.append(f'<span class="dy-wtag star">+{r["star_delta"]} 星</span>')
            if not badges:
                continue
            rows.append(
                f'<a class="dy-witem" href="{esc(r.get("url") or "")}" '
                'target="_blank" rel="noopener noreferrer">'
                f'<span class="dy-witem-name">{esc(r.get("name") or "")}</span>'
                f'<span class="dy-witem-badges">{"".join(badges)}</span>'
                f'<span class="dy-witem-date">{esc(r.get("date") or "")}</span></a>'
            )
        listing = f'<div class="dy-watch-list">{"".join(rows)}</div>' if rows else ""
    else:
        listing = (
            '<div class="dy-watch-empty">正在建立基线：首次采集只记录各项目当前状态，'
            '从下一次起即可对比出「有新提交 / 涨星」等真实动态（不伪造变更）。</div>'
        )

    pending = summary.get("pending") or 0
    note = (f'另有 {pending} 个项目因 GitHub 匿名 API 配额分批建立基线，将在后续每日收录中自动补齐。'
            if pending else '')
    return (
        '<section class="dy-watch" aria-label="上游变更雷达">'
        '<div class="dy-watch-head">'
        '<span class="dy-watch-title"><i class="dy-watch-dot"></i>上游变更雷达</span>'
        f'<span class="dy-watch-metrics">{metrics}</span>'
        f'<span class="dy-watch-time">更新 {esc(generated)}</span>'
        "</div>"
        f"{listing}"
        f'<div class="dy-watch-note">每天对比已收录 GitHub 项目的 pushed_at 与 stars，'
        f'只报确有变化的项；未变更的走 ETag 条件请求（不耗 API 配额）。{note}'
        '完整数据：<a href="/daily/updates.json" style="color:var(--dy-accent);font-weight:650">/daily/updates.json</a></div>'
        "</section>"
    )


def changes_html(updates: dict) -> str:
    """项目动态速递：把雷达 recent 的提交/star 变更渲染为可排序动态流。

    与 watchbar（汇总雷达状态）正交：这里给出逐条明细 + 前端排序，
    数据完全来自 updates.json，不额外采集、不伪造任何变更。
    recent 为空（冷启动基线期）或数据损坏时优雅降级、不渲染本区块。
    """
    if not updates:
        return ""
    recent = [r for r in (updates.get("recent") or []) if isinstance(r, dict)]
    if not recent:
        return ""

    generated = (updates.get("generated_at") or "").replace("T", " ")[:16]
    CAT_LABEL = {"githubGPT": "GitHub", "aiFrameworks": "框架", "GPTModels": "模型",
                 "ragKnowledge": "RAG", "agentFrameworks": "智能体框架",
                 "aiChat": "对话", "aiImage": "图像", "aiVideo": "视频", "aiCode": "代码",
                 "aiOffice": "办公", "aiAgent": "智能体", "studyGPT": "教程",
                 "techBlog": "博客", "aiNav": "导航", "likeGPT": "社区", "hotTools": "常用"}

    rows = []
    for r in recent:
        name = r.get("name") or ""
        url = r.get("url") or ""
        has_push = bool(r.get("has_push"))
        delta = int(r.get("star_delta") or 0)
        stars = r.get("stars")
        star_total = short_stars(stars) if stars is not None else ""
        date = r.get("date") or ""

        metrics = []
        if has_push:
            metrics.append('<span class="dy-change-metric push">新提交</span>')
        if delta:
            metrics.append(f'<span class="dy-change-metric star">+{delta} 星</span>')
        if not metrics:
            continue  # 无实质变更的不渲染，保持动态流干净
        cat_label = CAT_LABEL.get(r.get("category") or "", "")
        cat_html = f'<span class="dy-change-cat">{esc(cat_label)}</span>' if cat_label else ""
        star_html = f'<span class="dy-change-metric">{esc(star_total)}★</span>' if star_total else ""
        rows.append(
            f'<a class="dy-change" href="{esc(url)}" target="_blank" rel="noopener noreferrer" '
            f'data-star="{delta}" data-push="{1 if has_push else 0}" data-date="{esc(date)}" '
            f'data-name="{esc(name)}">'
            '<span class="dy-change-rank"></span>'
            f'<span class="dy-change-name">{esc(name)}</span>'
            f'{cat_html}'
            f'<span class="dy-change-metrics">{"".join(metrics)}{star_html}</span>'
            f'<span class="dy-change-date">{esc(date)}</span></a>'
        )

    if not rows:
        return ""

    sorts = (
        '<span class="dy-changes-sorts"><span class="dy-changes-sorts-label">排序</span>'
        '<button type="button" class="dy-sort-btn active" data-sort="star">涨星最多</button>'
        '<button type="button" class="dy-sort-btn" data-sort="push">最近提交</button>'
        '<button type="button" class="dy-sort-btn" data-sort="date">发现日期</button>'
        '</span>'
    )
    return (
        '<section class="dy-changes" aria-label="项目动态速递" data-default-sort="star">'
        '<div class="dy-changes-head">'
        '<span class="dy-changes-title"><i class="dy-watch-dot"></i>项目动态速递</span>'
        f'{sorts}'
        f'<span class="dy-changes-time">更新 {esc(generated)}</span>'
        '</div>'
        f'<div class="dy-changes-list">{"".join(rows)}</div>'
        '<div class="dy-changes-note">已收录项目最近被检测到的新提交与涨星，每条都可点开直达项目；'
        '排序只改变展示顺序，不改变任何数据。'
        f'订阅这份动态流：<a href="/daily/{UPDATES_FEED}" style="color:var(--dy-accent);font-weight:650">RSS</a>'
        '　完整明细：<a href="/daily/updates.json" style="color:var(--dy-accent);font-weight:650">updates.json</a></div>'
        '</section>'
    )


def knowledgebar_html(entries: list[dict]) -> str:
    """AI 发现知识库工具条：搜索框 + 方向标签云，筛选下方时间轴。

    标签云统计所有条目（含早期收录）的命中数，按数量降序；点选标签或输入
    关键词即时过滤卡片，与「按类型订阅」完全正交。
    """
    cloud = build_tag_cloud(entries)
    if not cloud:
        return ""
    chips = "".join(
        f'<button class="dy-tagbtn" type="button" data-tag="{esc(tag)}" '
        f'title="只看「{esc(tag)}」方向的收录">{esc(tag)}'
        f'<span class="dy-tagn">{count}</span></button>'
        for tag, count in cloud
    )
    return (
        '<section class="dy-kb" aria-label="AI 发现知识库">'
        '<div class="dy-kb-head">'
        '<span class="dy-kb-title">AI 发现知识库</span>'
        '<span class="dy-kb-hint">按方向筛选 · 支持站内搜索</span>'
        f'<label class="dy-search">{ICON_SEARCH}'
        '<input id="dy-search" type="search" autocomplete="off" '
        'placeholder="搜索名称 / 描述 / 标签" aria-label="搜索收录站点"></label>'
        "</div>"
        '<div class="dy-tagcloud">'
        '<button class="dy-tagbtn active" type="button" data-tag="" '
        f'title="显示全部方向">全部<span class="dy-tagn">{len(entries)}</span></button>'
        f'{chips}</div>'
        '<div class="dy-kb-status" id="dy-kb-status"></div>'
        "</section>"
    )


def receipt_html(verify: dict, days) -> str:
    """页顶「收录质量回执」：展示最新一日的候选→通过→收录漏斗与累计数据。"""
    vdays = verify.get("days") or {}
    if not vdays or not days:
        return ""
    latest = days[0][0]
    stat = vdays.get(latest)
    if not stat:
        return ""
    totals = verify.get("totals") or {}
    nodes = [
        (f"候选 {stat.get('checked', 0)}", ""),
        (f"通过 {stat.get('pass', 0)}", ""),
        (f"复核 {stat.get('review', 0)}", ""),
        (f"淘汰 {stat.get('fail', 0)}", ""),
        (f"收录 {stat.get('added', 0)}", "ok"),
    ]
    flow = '<span class="dy-receipt-arrow">→</span>'.join(
        f'<span class="dy-receipt-node {cls}">{esc(text)}</span>' for text, cls in nodes
    )
    total_checked = totals.get("checked", 0)
    total_pass = totals.get("pass", 0)
    total_added = totals.get("added", 0)
    rate = (total_added / total_checked * 100) if total_checked else 0
    return (
        '<section class="dy-receipt" aria-label="收录质量回执">'
        '<div class="dy-receipt-head">'
        '<span class="dy-receipt-title">收录质量回执</span>'
        f'<span class="dy-receipt-date">最近核验日 {esc(latest)} · 每条均经 HTTP 实探、AI 相关性与去重校验</span>'
        "</div>"
        f'<div class="dy-receipt-flow">{flow}</div>'
        '<div class="dy-receipt-meta">'
        f'累计核验 <b>{total_checked}</b> 个候选、通过 <b>{total_pass}</b> 条、'
        f'实际收录 <b>{total_added}</b> 个站点（收录率 {rate:.0f}%）。'
        '「复核 / 淘汰」为经人工判断未收录的候选，不代表站点失效。'
        '完整证据数据：<a href="/daily/verify.json">/daily/verify.json</a>，'
        '每张卡片的徽章可悬停查看单条明细。'
        "</div></section>"
    )


def card_html(item: dict, evidence: dict, health: dict | None = None,
              updates: dict | None = None, now: datetime | None = None) -> str:
    health = health or {}
    updates = updates or {}
    now = now or datetime.now(CST)
    initial = esc(next((c for c in item["name"] if not c.isspace()), "A").upper())
    icon = ""
    if item["img"]:
        icon = f'<img src="{esc(item["img"])}" alt="" loading="lazy">'
    desc = f'<p class="dy-desc">{esc(item["description"])}</p>' if item["description"] else ""
    tags = item.get("tags") or [FALLBACK_TAG]
    data_tags = esc(" ".join(tags))
    data_search = esc(f"{item['name']} {item['description']} {' '.join(tags)} {item['url']}")
    topics = "".join(f'<span class="dy-topic">{esc(t)}</span>' for t in tags)
    hrec = health.get(norm_url(item["url"]))
    down_cls = " dy-down" if hrec and hrec.get("status") == "down" else ""
    return (
        f'<a class="dy-card{down_cls}" href="{esc(item["url"])}" target="_blank" rel="noopener noreferrer" '
        f'data-tags="{data_tags}" data-search="{data_search}">'
        f'<span class="dy-icon"><span class="dy-initial">{initial}</span>{icon}</span>'
        f'<span class="dy-card-body">'
        f'<span class="dy-card-name">{esc(item["name"])}</span>'
        f'<span class="dy-tag">{esc(item["label"])}</span>'
        f'{desc}<span class="dy-topics">{topics}</span>'
        f'{badge_html(item, evidence)}{health_badge_html(item, health)}'
        f'{freshness_badge_html(item, updates, evidence, now)}</span></a>'
    )


def build_html(entries: list[dict], days, undated, site_url: str, generated: datetime,
               verify: dict | None = None, health: dict | None = None,
               updates: dict | None = None) -> str:
    verify = verify or {}
    health = health or {}
    updates = updates or {}
    evidence = verify.get("evidence") or {}
    health_sites = health.get("sites") or {}
    dated_count = sum(len(v) for _, v in days)
    latest = days[0][0] if days else "—"
    root = site_url.rstrip("/")
    alternates = ''.join(
        f'<link rel="alternate" type="application/rss+xml" '
        f'title="cyberMap · 每日 AI 速递 · {label}" href="/daily/{filename}">'
        for filename, (label, _cats) in CATEGORY_FEEDS.items()
    )
    alternates += (
        '<link rel="alternate" type="application/rss+xml" '
        'title="cyberMap · 项目动态速递" href="/daily/' + UPDATES_FEED + '">'
    )
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        "<title>每日 AI 速递 · cyberMap</title>",
        '<meta name="description" content="cyberMap 每日核验收录的 AI 开源项目、工具官网与模型框架，按收录日期倒序回看，支持 RSS 订阅。">',
        f'<link rel="canonical" href="{root}/daily/">',
        '<link rel="icon" href="/favicon.ico">',
        '<link rel="alternate" type="application/rss+xml" title="cyberMap 每日 AI 速递" href="/daily/feed.xml">',
        alternates,
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        '<header class="dy-top">',
        f'<a class="dy-back" href="/" title="返回 cyberMap 导航首页">{ICON_BACK}<span>cyberMap 导航</span></a>',
        '<span class="dy-brand">每日 AI 速递</span>',
        '<span class="dy-top-spacer"></span>',
        f'<a class="dy-top-link" href="/daily/feed.xml" title="RSS 2.0 订阅源">{ICON_RSS}<span>RSS 订阅</span></a>',
        f'<button class="dy-theme" id="dy-theme" type="button" title="切换外观：经典模式 / 赛博模式" aria-label="切换外观：经典模式或赛博模式">{ICON_MOON}</button>',
        "</header>",
        '<main class="dy-wrap">',
        '<section class="dy-hero">',
        '<span class="dy-kicker">每日更新 · 逐条核验</span>',
        "<h1>每日 AI 速递</h1>",
        "<p>每天从公开来源核验后至少收录 3 个 AI 站点（合格候选多则多收），按性质归入首页最合适的分类（开源项目 / 工具官网 / 模型框架 / 提示词与教程 / 技术博客等）。"
        "这里按收录日期倒序回看，每条都附可核验的证据；下方知识库可按方向标签筛选或站内搜索，"
        "「项目动态速递」则汇总已收录项目的最近提交与涨星，让沉淀下来的站点随时可查、更新可见。</p>",
        '<div class="dy-stats">',
        f'<div class="dy-stat"><span>累计收录</span><strong>{len(entries)}</strong></div>',
        f'<div class="dy-stat"><span>每日期数</span><strong>{len(days)}</strong></div>',
        f'<div class="dy-stat"><span>最近更新</span><strong>{esc(latest)}</strong></div>',
        f'<div class="dy-stat"><span>生成时间</span><strong>{generated.strftime("%m-%d %H:%M")}</strong></div>',
        "</div></section>",
        receipt_html(verify, days),
        healthbar_html(health),
        watchbar_html(updates),
        changes_html(updates),
        '<div class="dy-rssbar">',
        '<div>订阅每天的新收录 · 全部类型地址 <code>' + esc(f"{root}/daily/feed.xml") +
        '</code>，也可按类型单独订阅（统一为 RSS 2.0）。</div>',
        '<div class="dy-feed-links"><span class="dy-flabel">订阅源</span>'
        f'<a class="dy-feed-chip" href="/daily/feed.xml" title="全部类型">{ICON_RSS}<span>全部</span></a>'
        + ''.join(
            f'<a class="dy-feed-chip" href="/daily/{filename}" title="只订阅{label}">'
            f'{ICON_RSS}<span>{label}</span></a>'
            for filename, (label, _cats) in CATEGORY_FEEDS.items()
        )
        + f'<a class="dy-feed-chip" href="/daily/{UPDATES_FEED}" title="订阅已收录项目的更新动态">'
        f'{ICON_RSS}<span>项目动态</span></a>',
        '</div></div>',
        knowledgebar_html(entries),
        '<div class="dy-timeline">',
    ]

    if not days and not undated:
        parts.append('<div class="dy-empty">暂无已收录站点，等待第一次每日收录。</div>')

    for day, items in days:
        title, week = day_heading(day)
        parts.append(f'<section class="dy-day" id="day-{esc(day)}">')
        parts.append(
            '<div class="dy-day-head">'
            f'<h2>{esc(title)}</h2><span class="dy-week">{esc(week)}</span>'
            f'<span class="dy-count">{len(items)} 个站点</span></div>'
        )
        parts.append('<div class="dy-cards">' + "".join(card_html(i, evidence, health_sites, updates, generated) for i in items) + "</div>")
        parts.append("</section>")

    if undated:
        parts.append('<section class="dy-day" id="day-early">')
        parts.append(
            '<div class="dy-day-head"><h2>早期收录</h2>'
            '<span class="dy-week">描述中没有日期尾注</span>'
            f'<span class="dy-count">{len(undated)} 个站点</span></div>'
        )
        parts.append('<div class="dy-cards">' + "".join(card_html(i, evidence, health_sites, updates, generated) for i in undated) + "</div>")
        parts.append("</section>")

    parts += [
        "</div>",  # /dy-timeline
        '<footer class="dy-footer">',
        f'数据来源：<a href="{esc(root)}/">cyberMap</a> 全站导航分类，'
        "每条收录前均经过 HTTP 实探、GitHub 元数据与 AI 相关性核验；"
        '徽章明细见 <a href="/daily/verify.json">收录质量回执数据</a>。'
        "日期取自描述尾注「· YYYY-MM-DD 收录」。",
        f'<br>共 {len(entries)} 个站点、{len(days)} 期（其中 {dated_count} 条有明确日期）；'
        f'最后生成于 {generated.strftime("%Y-%m-%d %H:%M")} (UTC+8)。',
        "</footer>",
        "</main>",
        f"<script>{JS}</script>",
        "</body></html>",
    ]
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------- RSS 生成
def build_feed(days, site_url: str, generated: datetime,
               label: str | None = None, categories: tuple | None = None) -> bytes:
    """每天一个 item；无日期的「早期收录」不进 RSS，避免伪造发布时间。

    ``categories`` 为 None 时输出混合全量流（feed.xml）；给定分类 key 元组时
    只保留这些分类的条目，且某天该组分类无条目则跳过这一天，不产生空 item。
    """
    root = site_url.rstrip("/")
    suffix = f" · {label}" if label else ""
    title = f"cyberMap · 每日 AI 速递{suffix}"
    desc = (
        f"cyberMap 每日核验收录的 AI {label}，每天一期。"
        if label else
        "cyberMap 每日核验收录的 AI 站点（开源项目、工具官网、模型框架、教程博客等），每天一期。"
    )
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = f"{root}/daily/"
    ET.SubElement(channel, "description").text = desc
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "generator").text = "cybermap-daily/build_daily.py"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    ET.SubElement(channel, "ttl").text = "1440"

    for day, all_items in days:
        items = ([i for i in all_items if i["category"] in categories]
                 if categories else all_items)
        if not items:
            continue  # 该组分类当天无收录，跳过，避免空 item
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"每日 AI 速递{suffix} · {day}（{len(items)} 个站点）"
        )
        link = f"{root}/daily/#day-{day}"
        ET.SubElement(item, "link").text = link
        # guid 必须跨 feed 唯一：否则同时订阅「全部」与「某分类」时，
        # 阅读器会因同日期 guid 相同而把两类内容误判为同一篇。
        # 分类流 guid 用流名（如 feed-learn）+ 日期，不再绑定单一分类 key。
        feed_key = (categories[0] if len(categories) == 1
                    else re.sub(r"\W+", "-", label or "cat").lower()) if categories else None
        guid = f"{root}/daily/#day-{day}" if not categories else f"cybermap-daily-{feed_key}-{day}"
        ET.SubElement(item, "guid", {"isPermaLink": "false" if categories else "true"}).text = guid
        d = datetime.strptime(day, "%Y-%m-%d").date()
        ET.SubElement(item, "pubDate").text = format_datetime(
            datetime.combine(d, time(0, 0), tzinfo=CST)
        )
        lines = [f'{i["name"]}［{i["label"]}］{i["description"]} — {i["url"]}' for i in items]
        ET.SubElement(item, "description").text = "\n".join(lines)
        ET.SubElement(item, "category").text = label or "AI"

    if hasattr(ET, "indent"):
        ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def build_updates_feed(updates: dict, site_url: str, generated: datetime) -> bytes:
    """项目动态速递 RSS：每条 recent 变更一个 item（不是按天聚合）。

    日期语义与收录流不同：这里的 pubDate 取条目自带的 date（雷达发现变更的
    日期）、描述里写明 pushed_at（项目真实提交时间），不伪造任何时间。
    guid 用「项目 URL + 发现日期」保证跨期唯一，避免阅读器把不同批动态判重。
    recent 为空（冷启动基线期）时仍生成合法空 channel，不伪造条目。
    """
    root = site_url.rstrip("/")
    recent = [r for r in ((updates or {}).get("recent") or []) if isinstance(r, dict)]
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = "cyberMap · 项目动态速递"
    ET.SubElement(channel, "link").text = f"{root}/daily/"
    ET.SubElement(channel, "description").text = (
        "已收录 AI 项目最近被检测到的新提交与涨星动态，来源上游变更雷达。"
    )
    ET.SubElement(channel, "language").text = "zh-CN"
    ET.SubElement(channel, "generator").text = "cybermap-daily/build_daily.py"
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(generated)
    ET.SubElement(channel, "ttl").text = "1440"

    for r in recent:
        name = r.get("name") or ""
        url = r.get("url") or ""
        has_push = bool(r.get("has_push"))
        delta = int(r.get("star_delta") or 0)
        if not has_push and not delta:
            continue
        day = r.get("date") or ""
        item = ET.SubElement(channel, "item")
        changes = []
        if has_push:
            changes.append("新提交")
        if delta:
            changes.append(f"+{delta} 星")
        ET.SubElement(item, "title").text = f"{name} · {' · '.join(changes)}"
        ET.SubElement(item, "link").text = url or f"{root}/daily/"
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = (
            f"cybermap-change-{norm_url(url or name)}-{day}"
        )
        try:
            d = datetime.strptime(day, "%Y-%m-%d").date()
            pub = datetime.combine(d, time(0, 0), tzinfo=CST)
        except (ValueError, TypeError):
            pub = generated
        ET.SubElement(item, "pubDate").text = format_datetime(pub)
        desc_lines = [f"{name}：{'，'.join(changes)}。"]
        pushed = r.get("pushed_at")
        if pushed:
            desc_lines.append(f"项目最近推送：{str(pushed).replace('T', ' ')[:16]} UTC。")
        if r.get("stars") is not None:
            desc_lines.append(f"当前 stars：{short_stars(r['stars'])}。")
        desc_lines.append(f"发现日期：{day}。项目地址：{url}")
        ET.SubElement(item, "description").text = "".join(desc_lines)
        ET.SubElement(item, "category").text = "项目动态"

    if hasattr(ET, "indent"):
        ET.indent(rss, space="  ")
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- 写入与入口
def atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def fail(message: str) -> None:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    sys.exit(1)


def main() -> None:
    here = Path(__file__).resolve()
    default_repo = Path(os.environ.get("CYBERMAP_REPO", here.parent.parent))
    ap = argparse.ArgumentParser(description="生成 cyberMap 每日 AI 速递时间轴与 RSS")
    ap.add_argument("--repo", type=Path, default=default_repo, help="cyberMap 仓库根目录")
    ap.add_argument("--out", type=Path, default=None, help="输出目录（默认 <repo>/source/daily）")
    ap.add_argument("--site-url", default=SITE_URL_DEFAULT, help="站点根 URL（用于 RSS 绝对链接）")
    ap.add_argument("--check", action="store_true", help="只校验数据，不写文件")
    args = ap.parse_args()

    repo = args.repo.resolve()
    data_file = repo / DATA_REL
    out_dir = (args.out or (repo / OUT_REL)).resolve()
    site_url = args.site_url.rstrip("/")

    try:
        entries, warnings = load_entries(data_file)
    except (FileNotFoundError, ValueError) as exc:
        fail(str(exc))

    verify, verify_warnings = load_verify(repo / VERIFY_REL)
    warnings += verify_warnings
    health, health_warnings = load_health(repo / HEALTH_REL)
    warnings += health_warnings
    health_map = health.get("sites") or {}
    updates, update_warnings = load_updates(repo / UPDATES_REL)
    warnings += update_warnings
    days, undated = group_by_day(entries)
    generated = datetime.now(CST)
    summary = {
        "ok": True,
        "sites": len(entries),
        "days": len(days),
        "undated": len(undated),
        "latest": days[0][0] if days else None,
        "verified_badges": sum(
            1 for e in entries
            if (verify.get("evidence") or {}).get(norm_url(e["url"]))
        ),
        "quality_receipt": bool(verify.get("days") and days),
        "health_checked": len(health_map),
        "health_down": sum(1 for r in health_map.values() if r.get("status") == "down"),
        "health_bar": bool(health.get("summary", {}).get("checked")),
        "watch_tracked": (updates.get("summary") or {}).get("tracked", 0),
        "watch_recent": len(updates.get("recent") or []),
        "watch_bar": bool((updates.get("summary") or {}).get("total_repos")),
        "changes_feed": bool(updates.get("recent")),
        "fresh_badges": sum(
            1 for e in entries
            if freshness_label(
                ((updates.get("repos") or {}).get(norm_url(e["url"])) or {}).get("pushed_at"),
                generated,
            )
        ),
        "warnings": warnings,
    }
    if args.check:
        print(json.dumps({**summary, "check_only": True}, ensure_ascii=False, indent=2))
        return

    html_text = build_html(entries, days, undated, site_url, generated, verify, health, updates)
    # 混合全量流 + 四份分类流（按性质大类聚合多个分类），共用同一套过滤/渲染逻辑
    feeds = {"feed.xml": build_feed(days, site_url, generated)}
    for filename, (label, cats) in CATEGORY_FEEDS.items():
        feeds[filename] = build_feed(days, site_url, generated, label=label, categories=cats)
    # 项目动态流：来源 updates.json.recent，与收录日期流正交（空 recent 时为空 channel）
    feeds[UPDATES_FEED] = build_updates_feed(updates, site_url, generated)

    # 写完再自检一遍，避免把语法错误的产物发布出去
    for name, blob in feeds.items():
        root = ET.fromstring(blob)  # XML 可解析
        if root.tag != "rss":
            fail(f"{name} 根节点不是 rss，未写入")
    if "<html" not in html_text or html_text.count('<section class="dy-day"') != (
        len(days) + (1 if undated else 0)
    ):
        fail("生成的 HTML 结构自检未通过，未写入")
    # 分类订阅条必须出现全部入口（feed.xml + 4 份分类流 + 动态流）
    for filename in feeds:
        if f'href="/daily/{filename}"' not in html_text:
            fail(f"index.html 缺少订阅入口 {filename}，未写入")
    # AI 发现知识库工具条必须存在（搜索框 + 标签云 + 每张卡片带方向标签）
    if 'class="dy-kb"' not in html_text or 'id="dy-search"' not in html_text:
        fail("index.html 缺少 AI 发现知识库工具条，未写入")
    if f'data-tags="{FALLBACK_TAG}"' not in html_text and 'data-tags="' not in html_text:
        fail("index.html 卡片缺少方向标签数据，未写入")
    # 有健康数据时，汇总条与卡片健康标记必须渲染出来（防止读到了但没用上）
    if health_map:
        if 'class="dy-healthbar"' not in html_text:
            fail("index.html 缺少站点健康度汇总条，未写入")
        if 'class="dy-health ' not in html_text:
            fail("index.html 卡片缺少健康标记，未写入")
    # 有上游变更数据时，雷达区块必须渲染出来（防止读到了但没用上）
    if (updates.get("summary") or {}).get("total_repos"):
        if 'class="dy-watch"' not in html_text:
            fail("index.html 缺少上游变更雷达区块，未写入")
    # 有具体变更明细时，项目动态速递区块必须渲染（含排序按钮与动态 RSS 入口）
    if updates.get("recent"):
        if 'class="dy-changes"' not in html_text or 'class="dy-sort-btn' not in html_text:
            fail("index.html 缺少项目动态速递区块，未写入")
        if f'href="/daily/{UPDATES_FEED}"' not in html_text:
            fail(f"index.html 缺少动态流订阅入口 {UPDATES_FEED}，未写入")
    # 有已跟踪仓库时，卡片新鲜度徽章必须渲染出来（防止读到数据但没用上）
    if (updates.get("repos") or {}) and 'class="dy-fresh ' not in html_text:
        fail("index.html 卡片缺少站点新鲜度徽章，未写入")

    index_path = out_dir / "index.html"
    try:
        atomic_write(index_path, html_text.encode("utf-8"))
        for filename, blob in feeds.items():
            atomic_write(out_dir / filename, blob)
    except OSError as exc:
        fail(f"写入产物失败：{exc}")

    summary["outputs"] = {
        "index": str(index_path),
        "index_bytes": index_path.stat().st_size,
        "feeds": {name: str(out_dir / name) for name in feeds},
        "feed_items": {name: len(ET.fromstring(blob).findall("./channel/item"))
                       for name, blob in feeds.items()},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
