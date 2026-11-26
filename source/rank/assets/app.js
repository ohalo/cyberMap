(function () {
  'use strict';
  var state = { data: null, platform: 'all', q: '', sort: 'score', officialOnly: false };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var fmt = function (n) { return Number(n || 0).toLocaleString('en-US'); };
  /* i18n：当前语言 + 双语文本选择。index.html 已加载 i18n.js。 */
  function lang() { return (window.RANK_I18N && window.RANK_I18N.lang === 'en') ? 'en' : 'zh'; }
  function bi(zh, en) { return lang() === 'en' ? en : zh; }
  function desc(x) { return lang() === 'en' ? (x.description_en || x.description) : (x.description_zh || x.description); }
  function cat(x) { return lang() === 'en' ? (x.category_en || x.category) : (x.category_zh || x.category); }

  function platformBadges(platforms, labels) {
    return '<div class="badges">' + platforms.map(function (p) {
      return '<span class="badge">' + esc((labels[p] && labels[p].label) || p) + '</span>';
    }).join('') + '</div>';
  }

  function deltaCell(x, hasBaseline) {
    if (!hasBaseline) return '<span class="delta flat">' + bi('基线', 'Base') + '</span>';
    if (x.rank_delta == null) return '<span class="delta up">NEW</span>';
    if (x.rank_delta > 0) return '<span class="delta up">▲ ' + x.rank_delta + '</span>';
    if (x.rank_delta < 0) return '<span class="delta down">▼ ' + Math.abs(x.rank_delta) + '</span>';
    return '<span class="delta flat">—</span>';
  }

  function render() {
    var d = state.data;
    var labels = d.meta.platforms;
    var items = state.platform === 'all' ? d.overall : d.by_platform[state.platform] || [];

    var q = state.q.trim().toLowerCase();
    if (q) {
      items = items.filter(function (x) {
        return (x.name + ' ' + x.canonical + ' ' + x.description + ' ' + x.description_zh + ' ' +
                x.description_en + ' ' + x.category + ' ' + x.category_zh + ' ' + x.category_en)
          .toLowerCase().indexOf(q) !== -1;
      });
    }
    if (state.officialOnly) items = items.filter(function (x) { return x.official; });
    if (state.sort === 'stars') items = items.slice().sort(function (a, b) { return b.stars - a.stars; });
    if (state.sort === 'pushed') items = items.slice().sort(function (a, b) {
      return String(b.pushed_at || '').localeCompare(String(a.pushed_at || ''));
    });

    var html = items.map(function (x) {
      return '<a class="row" href="' + esc(x.detail_url) + '">' +
        '<span class="rank">' + x.rank + '</span>' +
        '<span><span class="pname">' + esc(x.name) +
        (x.official ? ' <span class="badge ok">' + bi('官方', 'Official') + '</span>' : '') + '</span>' +
        '<span class="pdesc">' + esc(cat(x)) + ' · ' + esc(desc(x)) + '</span></span>' +
        platformBadges(x.platforms, labels) +
        '<span class="score">' + Number(x.score).toFixed(1) + '</span>' +
        deltaCell(x, d.meta.scoring.history_baseline_date != null) +
        '<span class="stars">' + fmt(x.stars) + '</span></a>';
    }).join('');

    $('list').innerHTML = html || '<div class="empty">' + bi('没有匹配的插件，换个关键词试试', 'No matching plugins. Try another keyword.') + '</div>';

    var label = state.platform === 'all' ? bi('总榜', 'Overall') : (labels[state.platform] || {}).label;
    var note = bi('共 ' + items.length + ' 条', items.length + ' entries');
    if (state.platform !== 'all' && items.length < d.meta.top_n) {
      note += lang() === 'en'
        ? ' · Only ' + items.length + ' publicly verifiable samples on this platform, short of ' + d.meta.top_n + ' (no lower standards to fill)'
        : ' · 该平台公开可核验样本仅 ' + items.length + ' 条，未凑满 ' + d.meta.top_n + ' 条（不降低标准补数）';
    }
    if (q) note += lang() === 'en' ? ' · filtered by "' + esc(state.q.trim()) + '"' : ' · 已按「' + esc(state.q.trim()) + '」筛选';
    if (state.officialOnly) note += lang() === 'en' ? ' · official only' : ' · 仅显示官方市场收录';
    $('list-foot').textContent = label + '：' + note;
  }

  function renderTabs() {
    var d = state.data, labels = d.meta.platforms;
    var defs = [{ key: 'all', label: bi('全部 · 总榜', 'All · Overall'), count: d.overall.length }];
    Object.keys(labels).forEach(function (k) {
      defs.push({ key: k, label: labels[k].label, count: (d.by_platform[k] || []).length });
    });
    $('tabs').innerHTML = defs.map(function (t) {
      return '<button class="tab' + (state.platform === t.key ? ' on' : '') + '" data-key="' + t.key + '">' +
        esc(t.label) + ' <span class="muted">' + t.count + '</span></button>';
    }).join('');
    Array.prototype.forEach.call($('tabs').querySelectorAll('.tab'), function (btn) {
      btn.addEventListener('click', function () {
        state.platform = btn.getAttribute('data-key');
        Array.prototype.forEach.call($('tabs').querySelectorAll('.tab'), function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
        /* 同步到 URL：导航站的「平台分榜」按钮可直接深链到指定分榜 */
        try {
          var u = new URL(location.href);
          if (state.platform === 'all') u.searchParams['delete']('platform');
          else u.searchParams.set('platform', state.platform);
          history.replaceState(null, '', u.toString());
        } catch (e) { /* 旧浏览器忽略，功能不受影响 */ }
        render();
      });
    });
  }

  function boot(d) {
    state.data = d;
    /* 支持 /rank/?platform=codex 之类的深链（导航站侧栏与榜单页导航条用） */
    try {
      var requested = new URLSearchParams(location.search).get('platform');
      if (requested && (requested === 'all' || d.meta.platforms[requested])) {
        state.platform = requested;
      }
    } catch (e) { /* 忽略不支持 URLSearchParams 的环境 */ }
    $('stat-total').textContent = fmt(d.meta.total_plugins);
    $('stat-top').textContent = d.overall.length;
    $('stat-official').textContent = fmt(d.meta.official_count || 0);
    $('stat-platforms').textContent = Object.keys(d.meta.platforms).length;
    $('stat-date').textContent = d.date;
    $('foot-time').textContent = lang() === 'en'
      ? 'Built: ' + d.generated_at + ' · auto-updated daily 08:00 (UTC+8)'
      : '本次构建：' + d.generated_at + ' · 每日 08:00 (UTC+8) 自动更新';
    if (!d.meta.scoring.momentum_available) $('baseline-note').hidden = false;
    syncStaticLabels();
    renderTabs();
    render();
  }

  /* 语言切换时刷新由 JS 接管的表单文案（placeholder / option / foot-time），并重绘列表 */
  function syncStaticLabels() {
    var ph = $('search');
    if (ph) ph.placeholder = ph.getAttribute(lang() === 'en' ? 'data-ph-en' : 'data-ph-zh') || ph.placeholder;
    var sort = $('sort');
    if (sort) Array.prototype.forEach.call(sort.options, function (o) {
      o.textContent = o.getAttribute(lang() === 'en' ? 'data-en' : 'data-zh') || o.textContent;
    });
  }

  /* 语言切换：重绘列表与标签页（i18n.js 在 head 同步加载，on() 会立即回调一次） */
  if (window.RANK_I18N) {
    window.RANK_I18N.on(function () {
      syncStaticLabels();
      if (state.data) { renderTabs(); render(); }
    });
  }

  $('search').addEventListener('input', function (e) { state.q = e.target.value; render(); });
  $('sort').addEventListener('change', function (e) { state.sort = e.target.value; render(); });
  $('official-only').addEventListener('change', function (e) {
    state.officialOnly = e.target.checked; render();
  });

  fetch('data/top100.json?t=' + Date.now(), { cache: 'no-store' })
    .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then(boot)
    .catch(function (e) {
      var msg = lang() === 'en'
        ? 'Failed to load chart data: ' + esc(e.message) +
          '<br>For local preview, open via an HTTP server instead of double-clicking index.html (browsers block file:// fetch).'
        : '榜单数据加载失败：' + esc(e.message) +
          '<br>本地预览请通过 HTTP 服务打开，不要直接双击 index.html（浏览器会拦截 file:// 的 fetch）。';
      $('list').innerHTML = '<div class="empty">' + msg + '</div>';
    });
})();

/* ==========================================================================
   cyberMap 设计稿 04 号板 · 排行榜赛博增强（抗每日快照覆盖）
   --------------------------------------------------------------------------
   index.html / rank-frame.css / rank-frame.js 由独立排行榜流水线每日重写，
   写进去的赛博节点会被覆盖。本模块放在稳定的 app.js 末尾，运行时：
     1) 动态注入 05 设计 token 与 04 号板样式（<style> 置于 head 末尾，
        特异性高于 rank-frame.css 的旧紫蓝 token）；
     2) 幂等注入 SECTION 04 HUD / TOP 100 页眉 / SCORING MATRIX 三组节点；
     3) MutationObserver 跟随 body.night 切换，经典态全部隐藏、样式不生效。
   不改写榜单自身渲染，不依赖被覆盖的文件，网络/节点缺失时静默降级。
   ========================================================================== */
(function () {
  'use strict';
  var STYLE_ID = 'cm-rank-cyber-style';
  if (document.getElementById(STYLE_ID)) return;

  var css = '' +
    'body.night.rank-embedded{' +
      '--cm-bg:#05070b;--cm-glow-a:rgba(0,229,255,.13);--cm-glow-b:rgba(255,46,166,.11);' +
      '--cm-grid:rgba(0,229,255,.055);--cm-surface:rgba(11,18,27,.78);--cm-surface-solid:#0b121b;' +
      '--cm-topbar:rgba(11,18,27,.82);--cm-border:rgba(18,48,63,.9);--cm-border-strong:#12303f;' +
      '--cm-text:#e6f5ff;--cm-text-soft:#b7c9df;--cm-text-muted:#8ba0bd;--cm-text-faint:#6b7f99;' +
      '--cm-accent:#00e5ff;--cm-accent-2:#ff2ea6;--cm-accent-soft:rgba(255,46,166,.55);' +
      '--cm-accent-wash:rgba(255,46,166,.12);--cm-chip:rgba(0,229,255,.12);' +
      '--cm-shadow-sm:0 2px 14px rgba(0,0,0,.4);--cm-shadow-topbar:0 10px 30px rgba(0,0,0,.45)}' +
    '.cm-rank-cyber-node{display:none!important}' +
    'body.night.rank-embedded::after{' +
      'content:"";position:fixed;inset:0;pointer-events:none;z-index:9999;' +
      'background:repeating-linear-gradient(0deg,rgba(0,0,0,.12) 0 1px,transparent 1px 3px);opacity:.45}' +
    'body.night .cm-rank-cyber-hud{' +
      'display:flex!important;position:sticky;top:0;z-index:90;align-items:center;gap:12px;' +
      'height:28px;padding:0 24px;background:#07121c;border-bottom:1px solid var(--cm-border);' +
      'font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.1em;color:var(--cm-text-faint)}' +
    'body.night .cm-rank-cyber-hud::before{' +
      'content:"";width:6px;height:6px;border-radius:50%;background:var(--cm-accent);box-shadow:0 0 8px var(--cm-accent)}' +
    'body.night .cm-rank-cyber-hud b{color:var(--cm-accent);font-weight:700}' +
    'body.night .cm-rank-cyber-hud .cm-rank-cyber-right{margin-left:auto}' +
    'body.night .cm-rank-cyber-clock{font-family:"CM Orbitron",sans-serif;color:var(--cm-accent);font-weight:900}' +
    'body.night.rank-embedded .cm-rank-bar{top:28px}' +
    'body.night.rank-embedded .wrap{max-width:1180px;margin:0 auto;padding-top:26px}' +
    'body.night.rank-embedded .site-head{display:block;margin-bottom:18px;padding-bottom:14px;border-bottom:1px solid var(--cm-border)}' +
    'body.night.rank-embedded .site-head h1{font-family:"CM Chakra","Chakra Petch",sans-serif;font-size:clamp(30px,3.4vw,44px);font-weight:900;letter-spacing:-.02em;color:var(--cm-text)}' +
    'body.night.rank-embedded .site-head .sub{display:none}' +
    'body.night .cm-rank-cyber-head{display:flex!important;align-items:flex-end;gap:18px;flex-wrap:wrap;margin-bottom:8px}' +
    'body.night .cm-rank-cyber-kicker{flex:1 1 auto;font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px;letter-spacing:.14em;color:var(--cm-accent)}' +
    'body.night .cm-rank-cyber-topnum{font-family:"CM Orbitron",sans-serif;font-size:26px;font-weight:900;line-height:1;color:var(--cm-accent-2);text-shadow:0 0 18px rgba(255,46,166,.45)}' +
    'body.night .cm-rank-cyber-sub{flex:1 1 100%;font-family:"CM Chakra","Chakra Petch",sans-serif;font-size:12px;color:var(--cm-text-muted)}' +
    'body.night.rank-embedded .stats{display:none}' +
    'body.night.rank-embedded .toolbar{margin-bottom:12px;padding:10px 0;border-top:1px solid var(--cm-border);border-bottom:1px solid var(--cm-border)}' +
    'body.night.rank-embedded .tab,body.night.rank-embedded input[type=search],body.night.rank-embedded select{border-radius:2px;border-color:var(--cm-border);background:rgba(11,18,27,.86);font-family:"CM Mono","JetBrains Mono",monospace;font-size:10.5px}' +
    'body.night.rank-embedded .tab.on{background:rgba(255,46,166,.16);border-color:var(--cm-accent-2);color:var(--cm-accent-2)}' +
    'body.night.rank-embedded .list-head,body.night.rank-embedded .row{grid-template-columns:52px minmax(0,1fr) 188px 80px 88px 108px;gap:10px;padding-left:10px;padding-right:10px}' +
    'body.night.rank-embedded .list-head{border-bottom-color:var(--cm-border-strong);font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.08em;color:var(--cm-text-faint)}' +
    'body.night.rank-embedded .row{border-bottom:1px solid var(--cm-border);padding-top:10px;padding-bottom:10px}' +
    'body.night.rank-embedded .row:nth-child(-n+4){background:linear-gradient(90deg,rgba(0,229,255,.05),transparent 60%)}' +
    'body.night.rank-embedded .row:hover{background:rgba(0,229,255,.08)}' +
    'body.night.rank-embedded .rank{font-family:"CM Orbitron",sans-serif;font-size:18px;font-weight:900;color:var(--cm-accent)}' +
    'body.night.rank-embedded .pname{font-family:"CM Chakra","Chakra Petch",sans-serif;font-size:13px;font-weight:600}' +
    'body.night.rank-embedded .muted,body.night.rank-embedded .pdesc{font-size:11px;color:var(--cm-text-muted)}' +
    'body.night.rank-embedded .badges{font-family:"CM Mono","JetBrains Mono",monospace;font-size:9.5px}' +
    'body.night.rank-embedded .score{font-family:"CM Orbitron",sans-serif;font-size:20px;font-weight:900;color:var(--cm-accent-2)}' +
    'body.night.rank-embedded .delta{font-family:"CM Mono","JetBrains Mono",monospace;font-size:11px}' +
    'body.night.rank-embedded .stars{font-family:"CM Mono","JetBrains Mono",monospace;font-size:10.5px;color:var(--cm-text-soft)}' +
    'body.night .cm-rank-cyber-scoring{display:block!important;margin-top:22px;padding:16px 18px;border:1px solid var(--cm-border);border-radius:3px;background:rgba(11,18,27,.86)}' +
    'body.night .cm-cyber-scoring-title{margin-bottom:12px;font-family:"CM Mono","JetBrains Mono",monospace;font-size:10px;letter-spacing:.1em;color:var(--cm-accent-2)}' +
    'body.night .cm-cyber-scoring-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}' +
    'body.night .cm-cyber-scoring-node b{display:block;font-family:"CM Orbitron",sans-serif;font-size:34px;font-weight:900;line-height:1.1;color:var(--cm-accent)}' +
    'body.night .cm-cyber-scoring-node:nth-child(2) b{color:#39ff88}' +
    'body.night .cm-cyber-scoring-node:nth-child(3) b{color:#ffb020}' +
    'body.night .cm-cyber-scoring-node span{display:block;margin-top:4px;font-size:11px;color:var(--cm-text-muted);line-height:1.5}' +
    'body.night .cm-cyber-scoring-source{margin-left:auto;font-family:"CM Mono","JetBrains Mono",monospace;font-size:9.5px;color:var(--cm-text-faint)}' +
    '@media(max-width:900px){' +
      'body.night.rank-embedded .list-head{display:none}' +
      'body.night.rank-embedded .row{grid-template-columns:40px minmax(0,1fr) 66px 76px}' +
      'body.night.rank-embedded .row .badges,body.night.rank-embedded .row .stars{display:none}' +
      'body.night .cm-cyber-scoring-grid{grid-template-columns:1fr;gap:10px}}';

  function injectStyle() {
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = css;
    document.head.appendChild(s);
  }

  function node(html) {
    var box = document.createElement('div');
    box.innerHTML = html;
    return box.firstChild;
  }

  function tick() {
    var clock = document.querySelector('.cm-rank-cyber-clock');
    if (!clock) return;
    var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
    clock.textContent = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function inject() {
    if (document.querySelector('.cm-rank-cyber-hud')) return;
    var body = document.body;

    var hud = node('<div class="cm-rank-cyber-hud cm-rank-cyber-node">' +
      '<b>SECTION 04 // PLUGIN LEADERBOARD</b>' +
      '<span class="cm-rank-cyber-right">DATA UPDATED ' +
      '<span class="cm-rank-cyber-date">—</span> · DAILY · ' +
      '<span class="cm-rank-cyber-clock">--:--:--</span></span></div>');
    body.insertBefore(hud, body.firstChild);

    var head = document.querySelector('.site-head');
    if (head) {
      head.insertBefore(node('<div class="cm-rank-cyber-head cm-rank-cyber-node">' +
        '<span class="cm-rank-cyber-kicker">// 04 &nbsp; AI PLUGIN LEADERBOARD</span>' +
        '<span class="cm-rank-cyber-topnum">TOP 100</span>' +
        '<span class="cm-rank-cyber-sub">5 平台 · 综合分 + 涨星 + 活跃度 三维评分</span></div>'), head.firstChild);
    }

    var foot = document.getElementById('list-foot');
    if (foot) {
      foot.parentNode.insertBefore(node('<section class="cm-rank-cyber-scoring cm-rank-cyber-node" ' +
        'aria-label="三维评分模型"><div class="cm-cyber-scoring-title">SCORING MATRIX / 三维评分模型' +
        '<span class="cm-cyber-scoring-source">DATA SOURCE / api.github.com 实探 · 每日重算</span></div>' +
        '<div class="cm-cyber-scoring-grid">' +
        '<div class="cm-cyber-scoring-node"><b>60%</b><span>生态权重<br>跨平台安装量与适配广度</span></div>' +
        '<div class="cm-cyber-scoring-node"><b>25%</b><span>涨星动能<br>GitHub stars 近 30 天增速</span></div>' +
        '<div class="cm-cyber-scoring-node"><b>15%</b><span>活跃度<br>最近提交与版本发布节奏</span></div>' +
        '</div></section>'), foot.nextSibling);
    }

    var dateEl = document.querySelector('.cm-rank-cyber-date');
    var syncDate = function () {
      var statDate = document.getElementById('stat-date');
      if (dateEl && statDate && statDate.textContent && statDate.textContent !== '—') {
        dateEl.textContent = statDate.textContent;
      }
    };
    syncDate();
    setTimeout(syncDate, 600);
    tick();
    setInterval(tick, 1000);
  }

  injectStyle();
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', inject);
  } else {
    inject();
  }
})();
