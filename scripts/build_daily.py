#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cyberMap · 每日 AI 速递生成器

读取 ``source/_data/webstack.yml`` 里 ``dailyAI_oss`` / ``dailyAI_tool`` /
``dailyAI_model`` 三个分类，按描述尾注「· YYYY-MM-DD 收录」聚合成时间轴页面
``source/daily/index.html``，并输出 RSS 2.0 订阅源：一份混合流
``source/daily/feed.xml`` + 三份按分类过滤的独立流 ``feed-oss.xml`` /
``feed-tool.xml`` / ``feed-model.xml``（供读者只订阅自己关心的类型）。

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

# 分类 -> (中文标签, 短名)。顺序决定同一天内卡片的展示顺序。
CATEGORY_LABELS = OrderedDict([
    ("dailyAI_oss", ("开源项目", "oss")),
    ("dailyAI_tool", ("工具官网", "tool")),
    ("dailyAI_model", ("模型框架", "model")),
])

# 分类订阅源：category -> (文件名, 分类中文名)。feed.xml 仍是混合全量流。
CATEGORY_FEEDS = OrderedDict([
    ("dailyAI_oss", ("feed-oss.xml", "开源项目")),
    ("dailyAI_tool", ("feed-tool.xml", "工具官网")),
    ("dailyAI_model", ("feed-model.xml", "模型框架")),
])

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
"""

JS = r"""
(function(){
  var body=document.body;
  function isNight(){return /(?:^|;\s*)night=1(?:;|$)/.test(document.cookie);}
  function apply(){body.classList.toggle('night',isNight());}
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


def card_html(item: dict, evidence: dict, health: dict | None = None) -> str:
    health = health or {}
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
        f'{badge_html(item, evidence)}{health_badge_html(item, health)}</span></a>'
    )


def build_html(entries: list[dict], days, undated, site_url: str, generated: datetime,
               verify: dict | None = None, health: dict | None = None) -> str:
    verify = verify or {}
    health = health or {}
    evidence = verify.get("evidence") or {}
    health_sites = health.get("sites") or {}
    dated_count = sum(len(v) for _, v in days)
    latest = days[0][0] if days else "—"
    root = site_url.rstrip("/")
    alternates = ''.join(
        f'<link rel="alternate" type="application/rss+xml" '
        f'title="cyberMap · 每日 AI 速递 · {label}" href="/daily/{filename}">'
        for filename, label in CATEGORY_FEEDS.values()
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
        f'<button class="dy-theme" id="dy-theme" type="button" title="切换深浅色" aria-label="切换深浅色">{ICON_MOON}</button>',
        "</header>",
        '<main class="dy-wrap">',
        '<section class="dy-hero">',
        '<span class="dy-kicker">每日更新 · 逐条核验</span>',
        "<h1>每日 AI 速递</h1>",
        "<p>每天从公开来源核验后至少收录 3 个 AI 站点（合格候选多则多收），按类型归入开源项目 / 工具官网 / 模型框架。"
        "这里按收录日期倒序回看，每条都附可核验的证据；下方知识库可按方向标签筛选或站内搜索，让沉淀下来的站点随时可查。</p>",
        '<div class="dy-stats">',
        f'<div class="dy-stat"><span>累计收录</span><strong>{len(entries)}</strong></div>',
        f'<div class="dy-stat"><span>每日期数</span><strong>{len(days)}</strong></div>',
        f'<div class="dy-stat"><span>最近更新</span><strong>{esc(latest)}</strong></div>',
        f'<div class="dy-stat"><span>生成时间</span><strong>{generated.strftime("%m-%d %H:%M")}</strong></div>',
        "</div></section>",
        receipt_html(verify, days),
        healthbar_html(health),
        '<div class="dy-rssbar">',
        '<div>订阅每天的新收录 · 全部类型地址 <code>' + esc(f"{root}/daily/feed.xml") +
        '</code>，也可按类型单独订阅（统一为 RSS 2.0）。</div>',
        '<div class="dy-feed-links"><span class="dy-flabel">订阅源</span>'
        f'<a class="dy-feed-chip" href="/daily/feed.xml" title="全部类型">{ICON_RSS}<span>全部</span></a>'
        + ''.join(
            f'<a class="dy-feed-chip" href="/daily/{filename}" title="只订阅{label}">'
            f'{ICON_RSS}<span>{label}</span></a>'
            for filename, label in CATEGORY_FEEDS.values()
        ),
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
        parts.append('<div class="dy-cards">' + "".join(card_html(i, evidence, health_sites) for i in items) + "</div>")
        parts.append("</section>")

    if undated:
        parts.append('<section class="dy-day" id="day-early">')
        parts.append(
            '<div class="dy-day-head"><h2>早期收录</h2>'
            '<span class="dy-week">描述中没有日期尾注</span>'
            f'<span class="dy-count">{len(undated)} 个站点</span></div>'
        )
        parts.append('<div class="dy-cards">' + "".join(card_html(i, evidence, health_sites) for i in undated) + "</div>")
        parts.append("</section>")

    parts += [
        "</div>",  # /dy-timeline
        '<footer class="dy-footer">',
        f'数据来源：<a href="{esc(root)}/">cyberMap</a> 的 <code>dailyAI_*</code> 分类，'
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
def build_feed(days, site_url: str, generated: datetime, category: str | None = None) -> bytes:
    """每天一个 item；无日期的「早期收录」不进 RSS，避免伪造发布时间。

    ``category`` 为 None 时输出混合全量流（feed.xml）；给定分类 key 时只保留
    该分类的条目，且某天该分类无条目则跳过这一天，不产生空 item。
    """
    root = site_url.rstrip("/")
    label = CATEGORY_LABELS[category][0] if category else None
    suffix = f" · {label}" if label else ""
    title = f"cyberMap · 每日 AI 速递{suffix}"
    desc = (
        f"cyberMap 每日核验收录的 AI {label}，每天一期。"
        if label else
        "cyberMap 每日核验收录的 AI 开源项目、工具官网与模型框架，每天一期。"
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
        items = [i for i in all_items if i["category"] == category] if category else all_items
        if not items:
            continue  # 该分类当天无收录，跳过，避免空 item
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = (
            f"每日 AI 速递{suffix} · {day}（{len(items)} 个站点）"
        )
        link = f"{root}/daily/#day-{day}"
        ET.SubElement(item, "link").text = link
        # guid 必须跨 feed 唯一：否则同时订阅「全部」与「某分类」时，
        # 阅读器会因同日期 guid 相同而把两类内容误判为同一篇。
        guid = f"{root}/daily/#day-{day}" if not category else f"cybermap-daily-{category}-{day}"
        ET.SubElement(item, "guid", {"isPermaLink": "false" if category else "true"}).text = guid
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
        "warnings": warnings,
    }
    if args.check:
        print(json.dumps({**summary, "check_only": True}, ensure_ascii=False, indent=2))
        return

    html_text = build_html(entries, days, undated, site_url, generated, verify, health)
    # 混合全量流 + 三份分类流，共用同一套过滤/渲染逻辑
    feeds = {"feed.xml": build_feed(days, site_url, generated)}
    for category, (filename, _label) in CATEGORY_FEEDS.items():
        feeds[filename] = build_feed(days, site_url, generated, category=category)

    # 写完再自检一遍，避免把语法错误的产物发布出去
    for name, blob in feeds.items():
        root = ET.fromstring(blob)  # XML 可解析
        if root.tag != "rss":
            fail(f"{name} 根节点不是 rss，未写入")
    if "<html" not in html_text or html_text.count('<section class="dy-day"') != (
        len(days) + (1 if undated else 0)
    ):
        fail("生成的 HTML 结构自检未通过，未写入")
    # 分类订阅条必须出现全部 4 个入口
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
