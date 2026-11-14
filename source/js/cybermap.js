/* ==========================================================================
   cyberMap · Redesign 交互增强
   --------------------------------------------------------------------------
   通过 source/_data/webstack.yml 的 custom.body 注入，位于 </body> 之前。
   只做「增强」：不接管搜索、锚点跳转、侧栏折叠、lozad 懒加载等主题原有逻辑。
   ========================================================================== */
(function () {
  'use strict';

  var REPO_URL = 'https://github.com/ohalo/cyberMap';
  var reduceMotion = window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function svgPlaceholder(name) {
    var ch = (name || '?').trim().charAt(0).toUpperCase();
    ch = ch.replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
    var svg = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
      '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
      '<stop offset="0" stop-color="#6366f1"/><stop offset="1" stop-color="#06b6d4"/>' +
      '</linearGradient></defs>' +
      '<rect width="64" height="64" rx="16" fill="url(#g)"/>' +
      '<text x="32" y="43" text-anchor="middle" font-family="sans-serif" ' +
      'font-size="31" font-weight="700" fill="#ffffff">' + ch + '</text></svg>';
    return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
  }

  /* 图标加载失败 → 生成首字母渐变占位图（捕获阶段，error 不冒泡） */
  document.addEventListener('error', function (e) {
    var img = e.target;
    if (!img || img.tagName !== 'IMG' || img.dataset.cmFallback) return;
    if (!img.classList.contains('lozad')) return;
    img.dataset.cmFallback = '1';
    var card = img.closest ? img.closest('.xe-widget') : null;
    var nameEl = card && card.querySelector('.xe-user-name');
    img.src = svgPlaceholder(nameEl ? nameEl.textContent : 'AI');
  }, true);

  function boot() {
    var main = document.querySelector('.main-content');
    if (!main) return;

    var heads = Array.prototype.slice.call(main.querySelectorAll('h4.text-gray'));
    var cols = Array.prototype.slice.call(main.querySelectorAll('.row > .col-sm-3'));

    /* ---- 1. 顶栏工具：自定义 GitHub 按钮 + 主题切换文案 ---- */
    var ul = document.querySelector('.user-info-navbar .user-info-menu');
    var switchItem = ul && ul.querySelector('li.switch-mode');
    if (ul) {
      if (!ul.querySelector('.cyber-top-gh-li')) {
        var ghLi = el('li', 'cyber-top-gh-li hover-line');
        ghLi.appendChild(el('a', 'cyber-top-gh',
          '<i class="fab fa-github" aria-hidden="true"></i><span>GitHub</span>'));
        ghLi.firstChild.setAttribute('href', REPO_URL);
        ghLi.firstChild.setAttribute('target', '_blank');
        ghLi.firstChild.setAttribute('rel', 'noopener');
        ul.insertBefore(ghLi, switchItem || null);
      }
      if (switchItem) {
        var modeLink = switchItem.querySelector('a');
        if (modeLink) {
          modeLink.addEventListener('click', function (ev) { ev.preventDefault(); });
          var syncMode = function () {
            var dark = document.body.classList.contains('night');
            modeLink.innerHTML = '<i class="' + (dark ? 'fas fa-sun' : 'fas fa-moon') +
              '" aria-hidden="true"></i><span class="cyber-mode-label">' +
              (dark ? '浅色' : '深色') + '</span>';
          };
          syncMode();
          if (window.MutationObserver) {
            new MutationObserver(syncMode).observe(document.body,
              { attributes: true, attributeFilter: ['class'] });
          }
        }
      }
    }

    /* ---- 2. Hero 品牌区 + 实时统计 ---- */
    var sousuo = main.querySelector('section.sousuo');
    if (sousuo && !main.querySelector('.cyber-hero')) {
      var hero = el('div', 'cyber-hero',
        '<div class="cyber-kicker"><span>&#10022;</span> CYBERMAP · AI NAVIGATION</div>' +
        '<h1>发现好用的 <span class="cyber-gradient">AI 工具</span></h1>' +
        '<p>精选 AI 网站、开源项目与模型资源，每个链接都经过真实访问验证 · 每日自动收录</p>');
      var stats = el('div', 'cyber-stats');
      [
        [String(cols.length), '收录站点'],
        [String(heads.length), '精选分类'],
        ['每日', '自动更新']
      ].forEach(function (pair) {
        stats.appendChild(el('div', 'cyber-stat',
          '<strong>' + pair[0] + '</strong><span>' + pair[1] + '</span>'));
      });
      hero.appendChild(stats);
      sousuo.insertBefore(hero, sousuo.firstChild);
    }

    /* ---- 3. 分组标题加站点计数徽章 ---- */
    heads.forEach(function (h) {
      if (h.querySelector('.cyber-count')) return;
      var node = h.nextElementSibling;
      while (node && node.tagName === 'BR') node = node.nextElementSibling;
      if (!node || !node.classList.contains('row')) return;
      var n = node.querySelectorAll('.col-sm-3').length;
      h.appendChild(el('span', 'cyber-count', n + ' 个站点'));
    });

    /* ---- 4. 滚动时高亮侧栏当前分组 ---- */
    var links = Array.prototype.slice.call(
      document.querySelectorAll('#main-menu a.smooth'));
    var currentId = null;
    function updateActive() {
      var found = null;
      for (var i = 0; i < heads.length; i++) {
        var icon = heads[i].querySelector('i.linecons-tag');
        if (!icon || !icon.id) continue;
        if (heads[i].getBoundingClientRect().top <= 118) found = icon.id;
      }
      if (found === currentId) return;
      currentId = found;
      links.forEach(function (a) {
        a.classList.toggle('cyber-active',
          !!found && a.getAttribute('href') === '#' + found);
      });
    }
    var ticking = false;
    window.addEventListener('scroll', function () {
      if (ticking) return;
      ticking = true;
      window.requestAnimationFrame(function () { updateActive(); ticking = false; });
    }, { passive: true });
    window.addEventListener('resize', updateActive, { passive: true });
    updateActive();

    /* ---- 5. 卡片入场动画（带兜底，绝不留下隐藏卡片） ---- */
    if (!reduceMotion && 'IntersectionObserver' in window && cols.length) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          entry.target.classList.add('is-visible');
          io.unobserve(entry.target);
        });
      }, { rootMargin: '0px 0px 80px 0px', threshold: 0.02 });
      cols.forEach(function (c) { c.classList.add('cyber-reveal'); io.observe(c); });
      window.setTimeout(function () {
        cols.forEach(function (c) { c.classList.add('is-visible'); });
      }, 2200);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
