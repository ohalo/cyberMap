#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成「每日外联发送页」—— 按当天最新榜单，列出还没发过 issue 的插件作者。

背景：
    /rank/ 榜单每天 09:30 由独立流水线更新并同步到本仓库的 source/rank/data/top100.json。
    新插件每天上榜、排名每天变化，需要一个「每天一份」的手动发送页：
      · 数据源直接用当天最新的 top100.json（不是缓存的 outreach-data.json）
      · 和 issue-status.json 去重：已经发过的不再列
      · 标题/正文复用 send_issues.py，保证 scan 能认领、不重复打扰
      · 按日期归档到 outreach/daily-queue/YYYY-MM-DD.html
      · 维护一个 index.html 列出最近 N 天的归档页

用法：
    python3 scripts/build_daily_queue.py                 # 用当天日期生成
    python3 scripts/build_daily_queue.py --date 2026-11-17
    python3 scripts/build_daily_queue.py --include-org   # 把大厂也列进来（默认排除）
    python3 scripts/build_daily_queue.py --all           # 不去重，列全部（核对用）

产物：
    outreach/daily-queue/YYYY-MM-DD.html
    outreach/daily-queue/index.html
"""
import argparse
import html
import io
import json
import os
import sys
import urllib.parse
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "outreach")
QUEUE_DIR = os.path.join(OUT_DIR, "daily-queue")
TOP100 = os.path.join(ROOT, "source", "rank", "data", "top100.json")
STATUS = os.path.join(OUT_DIR, "issue-status.json")

sys.path.insert(0, os.path.join(ROOT, "scripts"))

# 大厂/组织 owner 名单：与 build_outreach.py 的 ORG_HINT 保持一致，避免给大厂发无意义 issue
ORG_HINT = {
    "google", "microsoft", "anthropics", "openai", "deepseek-ai", "tencent", "tensorflow",
    "meta", "amazon", "aws", "awslabs", "nvidia", "vercel", "cloudflare", "github",
    "huggingface", "mongodb", "stripe", "supabase", "atlassian", "salesforce", "adobe",
    "oracle", "ibm", "jetbrains", "figma", "slack", "datadog", "sentry", "grafana",
    "browser-use", "langchain-ai", "mistralai", "cohere-ai", "replicate", "huggingface",
    "alibaba", "bytedance", "baidu", "huawei", "xiaomi", "jingdong", "meituan",
}


def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with io.open(path, encoding="utf-8") as f:
        return json.load(f)


def import_send_issues():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "send_issues", os.path.join(ROOT, "scripts", "send_issues.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def normalize_repo(url):
    """从 url/canonical 推导 owner/repo。"""
    if not url:
        return ""
    if "github.com/" in url:
        p = url.split("github.com/", 1)[1]
    else:
        p = url
    p = p.split("?")[0].split("#")[0].strip("/")
    parts = [x for x in p.split("/") if x]
    return "%s/%s" % (parts[0], parts[1]) if len(parts) >= 2 else ""


def build_rows(si, date_str, include_org=False, no_dedup=False):
    top = load_json(TOP100, {})
    status = load_json(STATUS, {})
    items = status.get("items", {})

    # 已发的两类 key：owner|plugin 和 repo_path（小写）
    sent_keys, sent_repos = set(), set()
    for it in items.values():
        if it.get("status") == "sent":
            sent_keys.add((it.get("owner") or "").lower() + "|" + (it.get("plugin") or ""))
            if it.get("repo_path"):
                sent_repos.add(it["repo_path"].lower())

    overall = top.get("overall", []) or []
    blocked = si.load_blocked()  # 作者明确拒绝的 owner/repo —— 永不列入发送页
    rows, seen = [], set()
    for it in overall:
        canonical = it.get("canonical") or ""
        owner = canonical.split("/")[0] if "/" in canonical else (it.get("name") or "")
        if si.is_blocked({"owner": owner, "repo_path": canonical or owner}, blocked):
            continue
        if not include_org and owner.lower() in ORG_HINT:
            continue
        repo = normalize_repo(it.get("url") or canonical)
        if not repo or "/" not in repo:
            continue
        if si.is_blocked({"owner": owner, "repo_path": repo}, blocked):
            continue
        plugin = it.get("name") or repo.split("/")[1]
        dedup_key = owner.lower() + "|" + plugin
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        already = dedup_key in sent_keys or repo.lower() in sent_repos
        if already and not no_dedup:
            continue

        rec = {
            "owner": owner, "plugin": plugin, "repo": it.get("url") or canonical,
            "repo_path": repo, "rank": it.get("rank"), "rank_delta": it.get("rank_delta"),
            "stars": it.get("stars"), "is_new": it.get("is_new"),
            "platform": it.get("primary_platform"),
        }
        rec["_title"] = si.build_title(rec)
        rec["_body"] = si.build_body(rec)
        rows.append(rec)

    def prio(r):
        # 新上榜优先，其次排名靠前、涨幅大
        return (0 if r.get("is_new") else 1, r.get("rank") or 999, -(r.get("rank_delta") or 0))
    rows.sort(key=prio)
    return rows, (top.get("date") or date_str)


TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>cyberMap · 每日外联 __DATE__</title>
<style>
:root{--bg:#fbfbfa;--panel:#fff;--ink:#2c2c2a;--ink2:#5f5e5a;--ink3:#8a8984;
--line:#e6e4dd;--blue:#185fa5;--bluebg:#e6f1fb;--green:#0f6e56;--greenbg:#e1f5ee;
--amber:#854f0b;--amberbg:#faeeda;--red:#c0392b;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC","Helvetica Neue",Arial,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:28px 20px 90px}
h1{font-size:20px;font-weight:500;margin:0 0 6px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 18px}
.sub a{color:var(--blue);text-decoration:none}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(132px,1fr));gap:10px;margin-bottom:16px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:12px 14px}
.card .lbl{color:var(--ink3);font-size:12px;margin:0 0 4px}
.card .val{font-size:22px;font-weight:500;margin:0;font-variant-numeric:tabular-nums}
.card.done .val{color:var(--green)}
.bar{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.btn{display:inline-block;padding:8px 14px;border:1px solid var(--line);border-radius:8px;
background:#fff;color:var(--ink);font-size:13px;cursor:pointer;text-decoration:none;line-height:1.4}
.btn:hover{border-color:#b4b2a9;background:#f5f4f1}
.btn.primary{background:var(--blue);border-color:var(--blue);color:#fff}
.btn.primary:hover{background:#14518c}
.btn.green{background:var(--greenbg);border-color:#9fe1cb;color:var(--green)}
.hint{background:var(--amberbg);border:1px solid #fac775;border-radius:10px;
padding:13px 17px;font-size:13px;color:#5c3a08;margin:0 0 18px}
.hint b{font-weight:600}
table{width:100%;border-collapse:collapse;background:var(--panel);
border:1px solid var(--line);border-radius:12px;overflow:hidden}
th{text-align:left;font-weight:500;font-size:12px;color:var(--ink3);padding:10px 12px;
background:#f5f4f1;border-bottom:1px solid var(--line);white-space:nowrap}
td{padding:9px 12px;border-bottom:1px solid var(--line);vertical-align:middle;font-size:13px}
tr:last-child td{border-bottom:none}
tr:hover{background:#faf9f7}
tr.done{background:#f7fbf9}
tr.done .p{color:var(--ink3);text-decoration:line-through}
.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.p{font-weight:500}
.o{color:var(--ink3);font-size:12px;overflow-wrap:anywhere}
.up{color:var(--red);font-weight:500}
.down{color:var(--green);font-weight:500}
.acts{white-space:nowrap}
.acts .btn{margin:2px 3px 2px 0;padding:4px 9px;font-size:12px}
.chk{width:17px;height:17px;vertical-align:-3px;cursor:pointer;accent-color:var(--green)}
.pill{display:inline-block;padding:2px 8px;border-radius:5px;font-size:11px;
background:#f1efe8;color:#8a8984;border:0.5px solid var(--line)}
.pill.done{background:var(--greenbg);color:var(--green);border-color:#9fe1cb}
.pill.new{background:var(--bluebg);color:var(--blue);border-color:#b5d4f4}
#toast{position:fixed;left:50%;bottom:28px;transform:translateX(-50%);
background:#2c2c2a;color:#fff;padding:10px 20px;border-radius:9px;font-size:13px;
opacity:0;pointer-events:none;transition:opacity .18s}
#toast.on{opacity:1}
.empty{padding:40px;text-align:center;color:var(--ink3);font-size:15px}
</style></head><body><div class="wrap">
<h1>cyberMap · 每日外联发送页 <span style="font-size:15px;color:var(--ink3);font-weight:400">__DATE__</span></h1>
<p class="sub">榜单数据日期 __DATA_DATE__ · 共 <span id="total">0</span> 个待发作者（已自动扣除历史发过的）· <a href="index.html">← 返回归档</a></p>

<div class="cards">
  <div class="card"><p class="lbl">待发</p><p class="val" id="cTotal">0</p></div>
  <div class="card done"><p class="lbl">今日已发</p><p class="val" id="cDone">0</p></div>
  <div class="card"><p class="lbl">剩余</p><p class="val" id="cLeft">0</p></div>
  <div class="card"><p class="lbl">今日新上榜</p><p class="val" id="cNew">0</p></div>
</div>

<div class="hint"><b>今天怎么发：</b>点「下一个待发」→ GitHub 页面标题正文已自动填好 → 点 Submit → 回来点「✔ 记已发」。
进度存在本机浏览器，刷新不丢。发完跑一次 <code>send_issues.py scan</code> 会自动认领，不会重复。</div>

<div class="bar">
  <button class="btn primary" id="nextBtn">▶ 下一个待发</button>
  <button class="btn green" id="copyNext">⧉ 复制标题+正文</button>
  <button class="btn" id="exportBtn">⭳ 导出进度</button>
  <span style="margin-left:auto;font-size:12px;color:var(--ink3)" id="pct"></span>
</div>

__TABLE__
</div>
<div id="toast"></div>
<script>
const KEY='cybermap-daily-queue-__DATE__';
const mem={};
function lsGet(k){try{return localStorage.getItem(k);}catch(e){return mem[k]||null;}}
function lsSet(k,v){try{localStorage.setItem(k,v);}catch(e){mem[k]=v;}}
let done={};try{done=JSON.parse(lsGet(KEY)||'{}')||{};}catch(e){done={};}
const rows=[...document.querySelectorAll('tbody tr')];
const total=rows.length;
function save(){lsSet(KEY,JSON.stringify(done));}
function toast(t){const e=document.getElementById('toast');e.textContent=t;e.classList.add('on');
  setTimeout(()=>e.classList.remove('on'),1600);}
function refresh(){
  let d=0,n=0;
  rows.forEach(r=>{
    const k=r.dataset.key,is=!!done[k];
    r.classList.toggle('done',is);
    r.querySelector('.chk').checked=is;
    const pill=r.querySelector('.pill');
    if(is){pill.textContent='今日已发';pill.className='pill done';}
    else if(r.dataset.new==='1'){pill.textContent='新上榜';pill.className='pill new';}
    else{pill.textContent='待发';pill.className='pill';}
    if(is)d++;
    if(r.dataset.new==='1')n++;
  });
  document.getElementById('cTotal').textContent=total;
  document.getElementById('cDone').textContent=d;
  document.getElementById('cLeft').textContent=total-d;
  document.getElementById('cNew').textContent=n;
  document.getElementById('total').textContent=total;
  document.getElementById('pct').textContent='今日完成 '+d+' / '+total+'（'+(total?Math.round(d/total*100):0)+'%）';
}
rows.forEach(r=>{
  const k=r.dataset.key;
  r.querySelector('.chk').addEventListener('change',e=>{
    if(e.target.checked)done[k]=new Date().toISOString();else delete done[k];
    save();refresh();
  });
  r.querySelector('.mark').addEventListener('click',()=>{
    done[k]=new Date().toISOString();save();refresh();toast('已记账 ✓');
  });
});
function nextPending(){return rows.find(r=>!done[r.dataset.key]);}
document.getElementById('nextBtn').addEventListener('click',()=>{
  const r=nextPending();if(!r){toast('今天全发完了 🎉');return;}
  window.open(r.dataset.url,'_blank');
  r.querySelector('.p').scrollIntoView({block:'center',behavior:'smooth'});
});
document.getElementById('copyNext').addEventListener('click',async()=>{
  const r=nextPending();if(!r){toast('今天全发完了 🎉');return;}
  try{await navigator.clipboard.writeText('标题：'+r.dataset.title+'\n\n正文：\n'+r.dataset.body);toast('已复制 ✓');}
  catch(e){toast('复制失败，请手动选中');}
});
document.getElementById('exportBtn').addEventListener('click',()=>{
  const blob=new Blob([JSON.stringify(done,null,2)],{type:'application/json'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='cybermap-daily-__DATE__.json';a.click();toast('已导出 ✓');
});
refresh();
</script></body></html>
"""

INDEX_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>cyberMap · 每日外联归档</title>
<style>
:root{--bg:#fbfbfa;--panel:#fff;--ink:#2c2c2a;--ink2:#5f5e5a;--ink3:#8a8984;--line:#e6e4dd;--blue:#185fa5}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",Arial,sans-serif}
.wrap{max-width:720px;margin:0 auto;padding:32px 20px 80px}
h1{font-size:20px;font-weight:500;margin:0 0 6px}
.sub{color:var(--ink2);font-size:13px;margin:0 0 20px}
a{color:var(--blue);text-decoration:none}
a:hover{text-decoration:underline}
ul{list-style:none;padding:0;margin:0}
li{background:var(--panel);border:1px solid var(--line);border-radius:10px;margin-bottom:8px;padding:12px 16px;display:flex;justify-content:space-between;align-items:center}
li .d{font-variant-numeric:tabular-nums;font-weight:500}
li .n{color:var(--ink3);font-size:12px}
</style></head><body><div class="wrap">
<h1>cyberMap · 每日外联归档</h1>
<p class="sub">每天按最新榜单生成一份待发清单。点日期进入当天发送页。</p>
<ul>__ROWS__</ul>
</div></body></html>
"""


def write_index(keep=14):
    files = []
    for fn in os.listdir(QUEUE_DIR):
        if len(fn) == 15 and fn.endswith(".html") and fn[:10].count("-") == 2:
            date = fn[:-5]
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                continue
            count = 0
            fp = os.path.join(QUEUE_DIR, fn)
            with io.open(fp, encoding="utf-8") as f:
                txt = f.read()
            count = txt.count("data-key=")
            files.append((date, count))
    files.sort(reverse=True)
    rows = []
    for date, count in files[:keep]:
        rows.append('<li><a class="d" href="%s.html">%s</a><span class="n">%d 个待发</span></li>' % (date, date, count))
    doc = INDEX_TEMPLATE.replace("__ROWS__", "\n".join(rows) or "<li>暂无归档</li>")
    with io.open(os.path.join(QUEUE_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(doc)
    return len(files[:keep])


def main():
    ap = argparse.ArgumentParser(description="生成每日外联发送页")
    ap.add_argument("--date", help="指定日期 YYYY-MM-DD，默认今天")
    ap.add_argument("--include-org", action="store_true", help="包含大厂组织（默认排除）")
    ap.add_argument("--all", action="store_true", help="不去重，列全部榜单插件（核对用）")
    args = ap.parse_args()

    date_str = args.date or datetime.now().strftime("%Y-%m-%d")
    os.makedirs(QUEUE_DIR, exist_ok=True)

    si = import_send_issues()
    rows, data_date = build_rows(si, date_str, args.include_org, args.all)

    if rows:
        body = []
        for r in rows:
            url = "https://github.com/%s/issues/new?title=%s&body=%s" % (
                r["repo_path"], urllib.parse.quote(r["_title"]), urllib.parse.quote(r["_body"]))
            key = r["owner"].lower() + "|" + r["plugin"]
            delta = r.get("rank_delta")
            if delta is None:
                dcell = "<span class='d muted'>—</span>"
            elif delta > 0:
                dcell = "<span class='up'>▲ %d</span>" % delta
            elif delta < 0:
                dcell = "<span class='down'>▼ %d</span>" % abs(delta)
            else:
                dcell = "<span class='d muted'>—</span>"
            is_new = "1" if r.get("is_new") else "0"
            body.append(
                "<tr data-key='{key}' data-new='{is_new}' data-url='{url}' "
                "data-title='{title}' data-body='{body}'>"
                "<td><input type='checkbox' class='chk'></td>"
                "<td class='num'>{rank}</td>"
                "<td><div class='p'>{plugin}</div><div class='o'>{repo}</div></td>"
                "<td class='num'>{delta}</td>"
                "<td class='num'>{stars}</td>"
                "<td class='o'>{owner}</td>"
                "<td><span class='pill'>待发</span></td>"
                "<td class='acts'><a class='btn' href='{url}' target='_blank' rel='noopener'>打开并预填</a>"
                "<button class='btn green mark'>✔ 记已发</button></td></tr>".format(
                    key=html.escape(key, quote=True), is_new=is_new,
                    url=html.escape(url, quote=True), title=html.escape(r["_title"], quote=True),
                    body=html.escape(r["_body"], quote=True),
                    rank=r.get("rank") or "-", plugin=html.escape(str(r["plugin"])),
                    repo=html.escape(r["repo_path"]), delta=dcell,
                    stars=r.get("stars") or "-", owner=html.escape(str(r["owner"]))))
        table = "<table><thead><tr><th style='width:36px'></th><th>排名</th><th>插件</th><th>较昨日</th><th>Stars</th><th>作者</th><th>状态</th><th>操作</th></tr></thead><tbody>%s</tbody></table>" % "\n".join(body)
    else:
        table = '<div class="empty">今天没有新的待发作者了 🎉 全部历史都发过了。</div>'

    doc = (TEMPLATE.replace("__DATE__", date_str)
           .replace("__DATA_DATE__", data_date)
           .replace("__TABLE__", table))
    out = os.path.join(QUEUE_DIR, date_str + ".html")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(doc)

    n_new = sum(1 for r in rows if r.get("is_new"))
    n = write_index()
    print("生成 %s：%d 个待发（其中今日新上榜 %d）" % (out, len(rows), n_new))
    print("数据日期: %s | 归档索引已更新（%d 天）: %s" % (data_date, n, os.path.join(QUEUE_DIR, "index.html")))


if __name__ == "__main__":
    main()
