(function () {
  'use strict';
  var PAGE_SIZE = 50;
  var state = {
    catalog: null, rank: null, detailMap: {}, platform: 'all', q: '',
    sort: 'default', verifiableOnly: false, page: 0, filtered: []
  };
  var $ = function (id) { return document.getElementById(id); };
  var esc = function (s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  };
  var fmt = function (n) { return Number(n || 0).toLocaleString('en-US'); };
  var safeUrl = function (u) { return /^https?:\/\//.test(u || '') ? u : null; };
  var PLAT_LABEL = { codex: 'Codex', claude_code: 'Claude Code', dsh: 'dsh', workbuddy: 'WorkBuddy' };

  function metricCell(x) {
    var parts = [];
    if (x.verified_stars != null) parts.push('★ ' + fmt(x.verified_stars));
    if (x.verified_downloads != null) parts.push('↓ ' + fmt(x.verified_downloads) + '/周');
    if (x.verified_license) parts.push(esc(x.verified_license));
    if (!parts.length) return '<span class="muted">无公开指标</span>';
    return '<span class="mkt-metric">' + parts.join('<br>') + '</span>';
  }

  function linksCell(x) {
    var out = [];
    var repo = safeUrl(x.repo_url || (x.repo ? 'https://github.com/' + x.repo : null));
    if (repo) out.push('<a href="' + esc(repo) + '" target="_blank" rel="noopener">仓库 ↗</a>');
    var npm = safeUrl(x.npm_url);
    if (npm) out.push('<a href="' + esc(npm) + '" target="_blank" rel="noopener">npm ↗</a>');
    var home = safeUrl(x.homepage);
    if (home && home !== repo) out.push('<a href="' + esc(home) + '" target="_blank" rel="noopener">官网 ↗</a>');
    var detail = x.repo && state.detailMap[String(x.repo).toLowerCase()];
    if (detail) out.push('<a class="strong" href="' + esc(detail) + '">榜单详情 →</a>');
    return out.join('') || '<span class="muted">—</span>';
  }

  function render() {
    var c = state.catalog;
    // by_platform 存的是 items 下标，避免同一份数据序列化两遍
    var items = state.platform === 'all' ? c.items :
      (c.by_platform[state.platform] || []).map(function (i) { return c.items[i]; });
    var q = state.q.trim().toLowerCase();
    if (q) {
      items = items.filter(function (x) {
        return (x.name + ' ' + x.marketplace + ' ' + x.description + ' ' +
                (x.repo || '') + ' ' + (x.npm_package || '') + ' ' + (x.author || ''))
          .toLowerCase().indexOf(q) !== -1;
      });
    }
    if (state.verifiableOnly) items = items.filter(function (x) { return x.verifiable; });
    if (state.sort === 'stars') {
      items = items.slice().sort(function (a, b) {
        return (b.verified_stars || -1) - (a.verified_stars || -1);
      });
    } else if (state.sort === 'downloads') {
      items = items.slice().sort(function (a, b) {
        return (b.verified_downloads || -1) - (a.verified_downloads || -1);
      });
    }
    state.filtered = items;
    var pages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
    if (state.page >= pages) state.page = pages - 1;
    var slice = items.slice(state.page * PAGE_SIZE, (state.page + 1) * PAGE_SIZE);

    $('list').innerHTML = slice.map(function (x) {
      return '<div class="mkt-row">' +
        '<span><span class="pname">' + esc(x.name) +
        (x.verifiable ? ' <span class="badge ok">已核验</span>' : '') + '</span>' +
        '<span class="pdesc">' + esc((x.description || '').slice(0, 150)) + '</span></span>' +
        '<span><span class="badge">' + esc(PLAT_LABEL[x.platform] || x.platform) + '</span></span>' +
        '<span class="mkt-market" title="' + esc(x.source_file) + '">' + esc(x.marketplace) +
        (x.version ? '<br><span class="muted">' + esc(String(x.version).slice(0, 18)) + '</span>' : '') + '</span>' +
        metricCell(x) +
        '<span class="mkt-links">' + linksCell(x) + '</span></div>';
    }).join('') || '<div class="empty">没有匹配的条目，换个关键词试试</div>';

    $('pager').hidden = pages <= 1;
    $('page-info').textContent = '第 ' + (state.page + 1) + ' / ' + pages + ' 页 · 共 ' + items.length + ' 条';
    $('prev').disabled = state.page === 0;
    $('next').disabled = state.page >= pages - 1;
    var label = state.platform === 'all' ? '全部平台' : (PLAT_LABEL[state.platform] || state.platform);
    var note = label + '：显示 ' + slice.length + ' / ' + items.length + ' 条';
    if (state.verifiableOnly) note += ' · 仅显示有公开可核验指标的条目';
    if (q) note += ' · 已按「' + esc(state.q.trim()) + '」筛选';
    $('list-foot').textContent = note;
  }

  function renderTabs() {
    var c = state.catalog, bp = c.by_platform || {};
    var defs = [{ key: 'all', label: '全部平台', count: c.items.length }];
    Object.keys(PLAT_LABEL).forEach(function (k) {
      defs.push({ key: k, label: PLAT_LABEL[k], count: (bp[k] || []).length });
    });
    $('tabs').innerHTML = defs.map(function (t) {
      return '<button class="tab' + (state.platform === t.key ? ' on' : '') + '" data-key="' + t.key + '">' +
        esc(t.label) + ' <span class="muted">' + t.count + '</span></button>';
    }).join('');
    Array.prototype.forEach.call($('tabs').querySelectorAll('.tab'), function (btn) {
      btn.addEventListener('click', function () {
        state.platform = btn.getAttribute('data-key'); state.page = 0;
        Array.prototype.forEach.call($('tabs').querySelectorAll('.tab'), function (b) { b.classList.remove('on'); });
        btn.classList.add('on'); render();
      });
    });
  }

  function boot(catalog, rank) {
    state.catalog = catalog; state.rank = rank;
    if (rank) {
      var all = (rank.overall || []).slice();
      Object.keys(rank.by_platform || {}).forEach(function (k) {
        all = all.concat(rank.by_platform[k] || []);
      });
      all.forEach(function (x) { state.detailMap[String(x.canonical).toLowerCase()] = x.detail_url; });
    }
    $('stat-total').textContent = fmt(catalog.meta.total);
    $('stat-verifiable').textContent = fmt(catalog.meta.verifiable);
    $('stat-inrank').textContent = fmt((rank && rank.meta && rank.meta.official_count) || 0);
    $('stat-mode').textContent = catalog.meta.mode === 'local' ? '本机清单' : '提交快照';
    $('stat-date').textContent = catalog.date;
    $('foot-time').textContent = '本次构建：' + catalog.generated_at + ' · 每日 08:00 (UTC+8) 自动更新';
    renderTabs(); render();
  }

  $('search').addEventListener('input', function (e) { state.q = e.target.value; state.page = 0; render(); });
  $('sort').addEventListener('change', function (e) { state.sort = e.target.value; state.page = 0; render(); });
  $('verifiable-only').addEventListener('change', function (e) {
    state.verifiableOnly = e.target.checked; state.page = 0; render();
  });
  $('prev').addEventListener('click', function () { if (state.page > 0) { state.page--; render(); window.scrollTo(0, 0); } });
  $('next').addEventListener('click', function () { state.page++; render(); window.scrollTo(0, 0); });

  var bust = '?t=' + Date.now();
  Promise.all([
    fetch('data/marketplace.json' + bust, { cache: 'no-store' }).then(function (r) {
      if (!r.ok) throw new Error('marketplace.json HTTP ' + r.status); return r.json();
    }),
    fetch('data/top100.json' + bust, { cache: 'no-store' }).then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
  ]).then(function (res) { boot(res[0], res[1]); })
    .catch(function (e) {
      $('list').innerHTML = '<div class="empty">目录数据加载失败：' + esc(e.message) +
        '<br>请先运行 pipelines/run_daily.py 生成 data/marketplace.json，并通过 HTTP 服务打开本页。</div>';
    });
})();
