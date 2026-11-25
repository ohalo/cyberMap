/* ==========================================================================
   AI 插件排行榜 · cyberMap 嵌入层交互
   --------------------------------------------------------------------------
   1) 读取 cyberMap 主题写入的 night cookie，让榜单页与导航站同明暗；
   2) 榜单页内可自行切换主题（写回同一个 cookie，回导航站保持同步）；
   3) 按当前路径 / ?platform= 高亮导航条。
   不依赖 jQuery、不接管榜单自身的渲染逻辑。
   ========================================================================== */
(function () {
  'use strict';

  var MOON = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M12.3 3a9 9 0 1 0 8.7 11.4A7.2 7.2 0 0 1 12.3 3z"/></svg>';
  var SUN = '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zm0-6h1v3h-1V1zm0 19h1v3h-1v-3zM1 11h3v1H1v-1zm19 0h3v1h-3v-1zM4.2 5.6l.7-.7 2.1 2.1-.7.7-2.1-2.1zm12.8 12.8.7-.7 2.1 2.1-.7.7-2.1-2.1zM19.8 5.6l-.7-.7-2.1 2.1.7.7 2.1-2.1zM7 18.4l-.7-.7-2.1 2.1.7.7 2.1-2.1z"/></svg>';

  function isNight() {
    var m = document.cookie.match(/(?:^|;\s*)night\s*=\s*([^;]*)/);
    return !!(m && m[1] === '1');
  }

  function setNight(on) {
    document.body.classList.toggle('night', !!on);
    document.cookie = 'night=' + (on ? '1' : '0') + ';path=/;max-age=31536000';
    var btn = document.getElementById('cm-rank-theme');
    if (btn) {
      btn.innerHTML = on ? SUN : MOON;
      btn.setAttribute('title', on ? '切换到浅色模式' : '切换到深色模式');
      btn.setAttribute('aria-label', btn.getAttribute('title'));
    }
    syncDesignCopy();
  }

  /* 设计稿 04 号板：顶部 HUD 时钟 / 数据日期 / 英文表头。
     只在赛博态改写，切回经典态立即还原原中文表头。 */
  var originalHead = null;
  function syncDesignCopy() {
    var cyber = document.body.classList.contains('night');
    var heads = document.querySelectorAll('.list-head span');
    var design = ['RANK', 'PLUGIN', 'PLATFORM', 'SCORE', 'CHANGE', 'STARS'];
    if (cyber) {
      if (!originalHead) {
        originalHead = [];
        Array.prototype.forEach.call(heads, function (s) { originalHead.push(s.textContent); });
      }
      Array.prototype.forEach.call(heads, function (s, i) {
        if (design[i]) s.textContent = design[i];
      });
    } else if (originalHead) {
      Array.prototype.forEach.call(heads, function (s, i) {
        if (originalHead[i] != null) s.textContent = originalHead[i];
      });
    }
    var dateEl = document.querySelector('.cm-rank-hud-date');
    var statDate = document.getElementById('stat-date');
    if (dateEl && statDate && statDate.textContent && statDate.textContent !== '—') {
      dateEl.textContent = statDate.textContent;
    }
  }
  function tickRankClock() {
    var clock = document.querySelector('.cm-rank-hud-clock');
    if (!clock) return;
    var d = new Date(), p = function (n) { return (n < 10 ? '0' : '') + n; };
    clock.textContent = p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }

  function markActive() {
    var path = location.pathname.replace(/index\.html$/, '');
    var platform = new URLSearchParams(location.search).get('platform');
    var links = document.querySelectorAll('.cm-rank-nav a');
    Array.prototype.forEach.call(links, function (a) {
      var href = a.getAttribute('href') || '';
      var key = a.getAttribute('data-key') || '';
      var on = false;
      if (key === 'platform') {
        on = !!platform && href.indexOf('platform=' + platform) !== -1;
      } else if (key === 'harness') {
        on = path.indexOf('/rank/harness') === 0;
      } else if (key === 'category') {
        var category = new URLSearchParams(location.search).get('category');
        on = path.indexOf('/rank/harness') === 0 &&
          (a.getAttribute('data-cat') || '') === (category || '');
      } else if (key === 'all') {
        on = !platform && href.indexOf('?') === -1 &&
          (path === '/rank/' || path === '/rank' || path.indexOf('/rank/p/') === 0);
      } else {
        var file = href.split('/').pop().split('?')[0];
        on = file && path.indexOf('/' + file) !== -1;
      }
      a.classList.toggle('on', on);
    });
  }

  function boot() {
    setNight(isNight());
    var btn = document.getElementById('cm-rank-theme');
    if (btn) {
      btn.addEventListener('click', function () {
        setNight(!document.body.classList.contains('night'));
      });
    }
    markActive();
    syncDesignCopy();
    tickRankClock();
    setTimeout(syncDesignCopy, 400);
    setInterval(tickRankClock, 1000);
    setInterval(syncDesignCopy, 3000);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
