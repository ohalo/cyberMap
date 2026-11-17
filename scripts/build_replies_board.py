#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 outreach/replies.json 渲染成「作者回复看板」outreach/replies-board.html。

看板用途：
  · 一处看全所有外联 Issue 的作者/维护者回复（原话 + 时间 + 直达链接）
  · 自动识别「需要跟进」的反馈（数据纠错、要求补信息、模板问题等）并高亮
  · 已落实的反馈（如 DDDMUC 的 npm 映射纠错）给出状态标注
  · 顶部统计 + 筛选，链接到每日外联发送页

纯标准库、幂等、无副作用（只写 replies-board.html）。
用法：python3 scripts/build_replies_board.py
"""
import html
import io
import json
import os
import re
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outreach")
REPLIES = os.path.join(OUT_DIR, "replies.json")
BOARD = os.path.join(OUT_DIR, "replies-board.html")

# 已落实/已回应的反馈：repo_path -> 说明（人工维护，随处理进度更新）
RESOLVED = {
    "dddmuc/dsh-free-search": "已修复：新增可核验 npm 映射，页面周下载量已显示真实值（41,061）",
}

# 关键词 -> 跟进类型
FOLLOWUP_RULES = [
    (r"npm|下载|download|包名|映射|n/?a|数据.{0,4}错", "数据纠错"),
    (r"模板|template|必填|issue 表单|重新发起|自动关闭", "流程/模板"),
    (r"needs-info|replay|复现|env|环境信息|提供|补充", "需补信息"),
]


def load_json(path, default):
    if not os.path.exists(path):
        return default
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def followup_type(body):
    for pat, label in FOLLOWUP_RULES:
        if re.search(pat, body, re.I):
            return label
    return ""


def fmt_date(iso):
    if not iso:
        return ""
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso)
    return m.group(0) if m else iso[:10]


def esc(s):
    return html.escape(str(s) if s is not None else "", quote=True)


def build():
    data = load_json(REPLIES, {"items": [], "fetched_at": ""})
    items = [it for it in data.get("items", []) if it.get("comments")]
    # 最近回复优先
    def latest(it):
        ds = [c.get("created_at", "") for c in it["comments"]]
        return max(ds) if ds else ""
    items.sort(key=latest, reverse=True)

    total_comments = sum(len(it["comments"]) for it in items)
    actionable = sum(1 for it in items
                     if followup_type(" ".join(c.get("body", "") for c in it["comments"]))
                     and it["repo_path"].lower() not in {k.lower() for k in RESOLVED})
    resolved_n = sum(1 for it in items if it["repo_path"].lower() in {k.lower() for k in RESOLVED})

    cards = []
    for it in items:
        repo = it.get("repo_path", "")
        url = it.get("issue_url", "")
        is_resolved = repo.lower() in {k.lower() for k in RESOLVED}
        bodies = " ".join(c.get("body", "") for c in it["comments"])
        ftype = followup_type(bodies)
        badge = ""
        if is_resolved:
            badge = '<span class="tag tag-done">已落实</span>'
        elif ftype:
            badge = '<span class="tag tag-follow">需跟进 · %s</span>' % esc(ftype)

        resolved_note = ""
        for k, v in RESOLVED.items():
            if k.lower() == repo.lower():
                resolved_note = '<div class="resolved">✅ %s</div>' % esc(v)
                break

        comments_html = []
        for c in it["comments"]:
            author = c.get("author") or "unknown"
            atype = c.get("author_type") or ""
            is_bot = atype.endswith("Bot") or author.endswith("[bot]")
            body = c.get("body", "").strip()
            # 折叠超长自动评论，保留可读片段
            long = len(body) > 700
            shown = body[:700] + "\n…（完整内容见原 Issue）" if long else body
            who = esc(author) + (' <span class="bot">bot</span>' if is_bot else "")
            comments_html.append(
                '<div class="cmt">'
                '<div class="cmt-h"><span class="who">%s</span>'
                '<span class="when">%s</span>'
                '<a class="cmt-link" href="%s" target="_blank" rel="noopener">原文↗</a></div>'
                '<div class="cmt-body">%s</div></div>' % (
                    who, esc(fmt_date(c.get("created_at"))), esc(c.get("html_url") or url),
                    esc(shown)))

        cards.append(
            '<article class="card">'
            '<div class="card-h">'
            '<div class="repo"><a href="%s" target="_blank" rel="noopener">%s</a>'
            '<span class="issue">#%s</span></div>'
            '<div class="tags">%s</div></div>'
            '%s'
            '<div class="cmts">%s</div>'
            '</article>' % (
                esc(url), esc(repo), esc(it.get("issue_number")), badge,
                resolved_note, "".join(comments_html)))

    if not cards:
        cards = ['<div class="empty">暂无作者回复。采集脚本跑过后会自动更新。</div>']

    fetched = data.get("fetched_at", "")
    try:
        dt = datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        fetched_disp = dt.strftime("%Y-%m-%d %H:%M UTC")
    except Exception:
        fetched_disp = fetched or "—"

    tpl = TEMPLATE
    repl = {
        "__FETCHED__": esc(fetched_disp),
        "__ISSUES__": str(len(items)),
        "__COMMENTS__": str(total_comments),
        "__ACTIONABLE__": str(actionable),
        "__RESOLVED__": str(resolved_n),
        "__CARDS__": "\n".join(cards),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)

    with io.open(BOARD, "w", encoding="utf-8") as f:
        f.write(tpl)
    print("WROTE %s (%d issues, %d comments, %d actionable, %d resolved)" % (
        BOARD, len(items), total_comments, actionable, resolved_n))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cyberMap · 作者回复看板</title>
<style>
:root{--bg:#fbfbfa;--panel:#fff;--ink:#2c2c2a;--ink2:#5f5e5a;--ink3:#8a8984;
--line:#e6e4dd;--blue:#185fa5;--bluebg:#e6f1fb;--green:#0f6e56;--greenbg:#e1f5ee;
--amber:#854f0b;--amberbg:#faeeda;--red:#c0392b;--redbg:#fbe9e7}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",Arial,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:30px 20px 90px}
h1{font-size:21px;font-weight:500;margin:0 0 6px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 18px}
.sub a{color:var(--blue);text-decoration:none}
.cards-top{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-bottom:18px}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:12px 14px}
.stat .lbl{color:var(--ink3);font-size:12px;margin:0 0 4px}
.stat .val{font-size:23px;font-weight:500;margin:0;font-variant-numeric:tabular-nums}
.stat.act .val{color:var(--amber)}
.stat.ok .val{color:var(--green)}
.hint{background:var(--amberbg);border:1px solid #fac775;border-radius:10px;
padding:12px 16px;font-size:13px;color:#5c3a08;margin:0 0 18px}
.bar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:0 0 16px}
.btn{display:inline-block;padding:7px 13px;border:1px solid var(--line);border-radius:8px;
background:#fff;color:var(--ink2);font-size:13px;cursor:pointer;text-decoration:none;line-height:1.4}
.btn:hover{border-color:#b4b2a9;background:#f5f4f1}
.btn.on{background:var(--blue);border-color:var(--blue);color:#fff}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;
padding:16px 18px;margin-bottom:12px}
.card-h{display:flex;justify-content:space-between;align-items:flex-start;gap:12px;
border-bottom:1px solid var(--line);padding-bottom:10px;margin-bottom:10px}
.repo{font-size:15px;font-weight:500}
.repo a{color:var(--blue);text-decoration:none}
.repo a:hover{text-decoration:underline}
.issue{color:var(--ink3);font-weight:400;margin-left:6px;font-size:13px}
.tags{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
.tag{font-size:11px;padding:3px 8px;border-radius:20px;white-space:nowrap}
.tag-follow{background:var(--amberbg);color:var(--amber);border:1px solid #fac775}
.tag-done{background:var(--greenbg);color:var(--green);border:1px solid #9fe1cb}
.resolved{background:var(--greenbg);color:#0b5c47;border-radius:8px;
padding:8px 12px;font-size:13px;margin:0 0 12px}
.cmt{padding:9px 0;border-top:1px dashed #eee}
.cmt:first-child{border-top:0;padding-top:0}
.cmt-h{display:flex;align-items:center;gap:10px;margin-bottom:4px;flex-wrap:wrap}
.who{font-weight:500;color:var(--ink)}
.bot{font-size:10px;color:var(--ink3);background:#f0efeb;border-radius:4px;padding:1px 5px}
.when{color:var(--ink3);font-size:12px;font-variant-numeric:tabular-nums}
.cmt-link{margin-left:auto;color:var(--blue);font-size:12px;text-decoration:none}
.cmt-link:hover{text-decoration:underline}
.cmt-body{color:var(--ink2);font-size:13px;white-space:pre-wrap;word-break:break-word}
.empty{text-align:center;color:var(--ink3);padding:50px 0;border:1px dashed var(--line);border-radius:12px}
.foot{color:var(--ink3);font-size:12px;margin-top:26px;text-align:center}
@media(max-width:560px){.card-h{flex-direction:column}.tags{justify-content:flex-start}}
</style></head><body><div class="wrap">
<h1>cyberMap · 作者回复看板</h1>
<p class="sub">外联 Issue 的作者/维护者回复，一处看全。采集时间 __FETCHED__ ·
<a href="daily-queue/index.html">每日外联发送页 →</a></p>
<div class="cards-top">
  <div class="stat"><p class="lbl">有回复的 Issue</p><p class="val">__ISSUES__</p></div>
  <div class="stat"><p class="lbl">回复总数</p><p class="val">__COMMENTS__</p></div>
  <div class="stat act"><p class="lbl">待跟进</p><p class="val">__ACTIONABLE__</p></div>
  <div class="stat ok"><p class="lbl">已落实</p><p class="val">__RESOLVED__</p></div>
</div>
<div class="hint">💡 本页随每日排行榜自动更新。带「需跟进」标签的是作者对网站/数据提出的意见，
点「原文↗」到 GitHub 查看完整讨论；已落实的反馈在卡片里标注了处理结果。</div>
<div class="bar">
  <button class="btn on" data-f="all">全部</button>
  <button class="btn" data-f="follow">需跟进</button>
  <button class="btn" data-f="done">已落实</button>
</div>
<div id="list">__CARDS__</div>
<p class="foot">数据来自 GitHub 公开 Issue 评论 · 仅供内部跟进，不构成投资建议</p>
</div>
<script>
(function(){
  var btns=document.querySelectorAll('.btn[data-f]'),list=document.getElementById('list');
  function apply(f){
    [].forEach.call(list.querySelectorAll('.card'),function(c){
      var isDone=!!c.querySelector('.tag-done');
      var isFollow=!!c.querySelector('.tag-follow');
      var show=(f==='all')||(f==='done'&&isDone)||(f==='follow'&&isFollow);
      c.style.display=show?'':'none';
    });
    [].forEach.call(btns,function(b){b.classList.toggle('on',b.getAttribute('data-f')===f);});
  }
  [].forEach.call(btns,function(b){b.addEventListener('click',function(){apply(b.getAttribute('data-f'));});});
})();
</script></body></html>
"""

if __name__ == "__main__":
    build()
