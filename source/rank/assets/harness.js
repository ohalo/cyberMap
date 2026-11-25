(function () {
  'use strict';
  var state = { data: null, category: 'all', q: '', sort: 'score', curatedOnly: false };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var fmt = function (n) { return Number(n || 0).toLocaleString('en-US'); };
  function lang() { return (window.RANK_I18N && window.RANK_I18N.lang === 'en') ? 'en' : 'zh'; }
  function bi(zh, en) { return lang() === 'en' ? en : zh; }
  // 榜单有两套入口：/rank/harness.html（文件）与 /rank/harness/、/rank/harness/index.html（目录）。
  // 目录页的相对路径基准是 /rank/harness/，数据实际在 /rank/data/，需要回退一级。
  function isDirEntry() { return /\/harness\/(?:index\.html)?$/.test(location.pathname); }
  function dataUrls() {
    var rel = 'data/harness/top.json';
    return isDirEntry() ? ['../' + rel, rel] : [rel, '../' + rel];
  }
  function detailHref(x) {
    var url = String(x.detail_url || '');
    return isDirEntry() ? url.replace(/^harness\//, '') : url;
  }
  function catName(x) {
    var labels = state.data.meta.categories || {};
    var c = labels[x.category] || {};
    return lang() === 'en' ? (c.label_en || x.category) : (c.label || x.category);
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
    var watch = state.category === 'watchlist';
    var items = watch ? (d.watchlist || []).slice() :
      (state.category === 'all' ? d.overall : (d.by_category[state.category] || [])).slice();

    var q = state.q.trim().toLowerCase();
    if (q) {
      items = items.filter(function (x) {
        return (x.name + ' ' + x.slug + ' ' + x.description + ' ' + x.category + ' ' +
          (x.category_label || '')).toLowerCase().indexOf(q) !== -1;
      });
    }
    if (state.curatedOnly && !watch) {
      items = items.filter(function (x) { return x.origin === 'curated'; });
    }
    if (state.sort === 'stars') items.sort(function (a, b) { return (b.stars || 0) - (a.stars || 0); });
    if (state.sort === 'delta') items.sort(function (a, b) { return (b.star_delta || 0) - (a.star_delta || 0); });
    if (state.sort === 'pushed') items.sort(function (a, b) {
      return String(b.pushed_at || '').localeCompare(String(a.pushed_at || ''));
    });

    var hasBaseline = d.meta.scoring.history_baseline_date != null;
    var html = items.map(function (x) {
      if (watch) {
        return '<div class="row h-watch"><span class="rank">—</span>' +
          '<span><span class="pname">' + esc(x.name) + '</span><span class="pdesc">' + esc(x.reason) + '</span></span>' +
          '<span>' + esc(x.category) + '</span><span class="score">—</span>' +
          '<span class="delta flat">' + bi('观察', 'Watch') + '</span><span class="stars">—</span></div>';
      }
      return '<a class="row" href="' + esc(detailHref(x)) + '">' +
        '<span class="rank">' + x.rank + '</span>' +
        '<span><span class="pname">' + esc(x.name) +
        (x.origin === 'discovered' ? ' <span class="badge">' + bi('发现', 'Discovered') + '</span>' : '') +
        '</span><span class="pdesc">' + esc(x.slug) + ' · ' + esc(x.description) + '</span></span>' +
        '<span>' + esc(catName(x)) + '</span>' +
        '<span class="score">' + Number(x.score).toFixed(1) + '</span>' +
        deltaCell(x, hasBaseline) +
        '<span class="stars">' + fmt(x.stars) + '</span></a>';
    }).join('');
    $('h-list').innerHTML = html || '<div class="empty">' +
      bi('没有匹配的 harness，换个关键词试试', 'No matching harnesses. Try another keyword.') + '</div>';

    var label = watch ? bi('闭源观察名单', 'Closed-source watchlist') :
      (state.category === 'all' ? bi('总榜', 'Overall') :
        ((d.meta.categories[state.category] || {}).label || state.category));
    var note = bi('共 ' + items.length + ' 条', items.length + ' entries');
    if (q) note += bi(' · 已按「' + state.q.trim() + '」筛选', ' · filtered by "' + state.q.trim() + '"');
    $('h-list-foot').textContent = label + '：' + note;
  }

  function renderTabs() {
    var d = state.data;
    var defs = [{ key: 'all', label: bi('全部 · 总榜', 'All · Overall'), count: d.overall.length }];
    Object.keys(d.meta.categories).forEach(function (k) {
      defs.push({ key: k, label: lang() === 'en' ? d.meta.categories[k].label_en : d.meta.categories[k].label,
        count: (d.by_category[k] || []).length });
    });
    defs.push({ key: 'watchlist', label: bi('闭源观察', 'Watchlist'), count: (d.watchlist || []).length });
    $('h-tabs').innerHTML = defs.map(function (t) {
      return '<button class="tab' + (state.category === t.key ? ' on' : '') + '" data-key="' + t.key + '">' +
        esc(t.label) + ' <span class="muted">' + t.count + '</span></button>';
    }).join('');
    Array.prototype.forEach.call($('h-tabs').querySelectorAll('.tab'), function (btn) {
      btn.addEventListener('click', function () {
        state.category = btn.getAttribute('data-key');
        Array.prototype.forEach.call($('h-tabs').querySelectorAll('.tab'), function (b) { b.classList.remove('on'); });
        btn.classList.add('on');
        try {
          var u = new URL(location.href);
          if (state.category === 'all') u.searchParams['delete']('category');
          else u.searchParams.set('category', state.category);
          history.replaceState(null, '', u.toString());
        } catch (e) { /* ignore */ }
        render();
      });
    });
  }

  function boot(d) {
    state.data = d;
    try {
      var requested = new URLSearchParams(location.search).get('category');
      if (requested && (requested === 'all' || requested === 'watchlist' || d.meta.categories[requested])) {
        state.category = requested;
      }
    } catch (e) { /* ignore */ }
    $('h-stat-total').textContent = fmt(d.meta.total_harnesses);
    $('h-stat-top').textContent = d.overall.length;
    $('h-stat-curated').textContent = fmt(d.meta.curated);
    $('h-stat-discovered').textContent = fmt(d.meta.discovered);
    $('h-stat-date').textContent = d.date;
    $('h-foot-time').textContent = bi('本次构建：' + d.generated_at + ' · 每日 09:50 (UTC+8) 自动更新',
      'Built: ' + d.generated_at + ' · auto-updated daily 09:50 (UTC+8)');
    if (!d.meta.scoring.momentum_available) $('h-baseline-note').hidden = false;
    syncStaticLabels();
    renderTabs();
    render();
  }

  function syncStaticLabels() {
    var ph = $('h-search');
    if (ph) ph.placeholder = ph.getAttribute(lang() === 'en' ? 'data-ph-en' : 'data-ph-zh') || ph.placeholder;
    var sort = $('h-sort');
    if (sort) Array.prototype.forEach.call(sort.options, function (o) {
      o.textContent = o.getAttribute(lang() === 'en' ? 'data-en' : 'data-zh') || o.textContent;
    });
  }

  if (window.RANK_I18N) {
    window.RANK_I18N.on(function () {
      syncStaticLabels();
      if (state.data) { renderTabs(); render(); }
    });
  }
  $('h-search').addEventListener('input', function (e) { state.q = e.target.value; render(); });
  $('h-sort').addEventListener('change', function (e) { state.sort = e.target.value; render(); });
  $('h-curated-only').addEventListener('change', function (e) { state.curatedOnly = e.target.checked; render(); });

  function fetchFirst(urls, i) {
    i = i || 0;
    if (i >= urls.length) return Promise.reject(new Error('HTTP 404'));
    return fetch(urls[i] + '?t=' + Date.now(), { cache: 'no-store' })
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .catch(function (e) {
        if (i + 1 < urls.length) return fetchFirst(urls, i + 1);
        throw e;
      });
  }

  fetchFirst(dataUrls())
    .then(boot)
    .catch(function (e) {
      $('h-list').innerHTML = '<div class="empty">' +
        bi('榜单数据加载失败，请稍后刷新重试', 'Failed to load ranking data, please retry') +
        ' (' + esc(e.message) + ')</div>';
    });
})();
