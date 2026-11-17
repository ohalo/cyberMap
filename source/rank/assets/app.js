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
