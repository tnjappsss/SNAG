(() => {
  let scheduled = false;
  let busy = false;
  let currentVideo = '';
  let notice;
  let noticeTimer;
  let menu;
  function resetButton() {
    const live = document.querySelector('#snag-youtube-button');
    if (live) {
      live.disabled = busy;
      const label = busy ? 'Sending…' : 'SNAG';
      if (live.textContent !== label) live.textContent = label;
    }
  }
  function closeMenu() {
    menu?.remove(); menu = null;
    document.querySelector('#snag-youtube-button')?.setAttribute('aria-expanded', 'false');
  }
  document.addEventListener('click', event => {
    if (menu && !menu.contains(event.target) && event.target.id !== 'snag-youtube-button') closeMenu();
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu) { closeMenu(); document.querySelector('#snag-youtube-button')?.focus(); }
  });
  window.addEventListener('resize', closeMenu);
  window.addEventListener('scroll', closeMenu, {passive: true});

  function videoId() {
    if (location.hostname !== 'www.youtube.com') {
      if (globalThis.snagVideoPage(location.href)) return location.href;
      // Feeds do not put the selected video's permalink in the address bar.
      if (/^(www\.)?(x\.com|twitter\.com|instagram\.com|tiktok\.com)$/.test(location.hostname)) {
        const visible = [...document.querySelectorAll('video')].filter(video => {
          const r = video.getBoundingClientRect();
          return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight;
        }).sort((a,b) => Math.abs(a.getBoundingClientRect().top) - Math.abs(b.getBoundingClientRect().top));
        for (const video of visible) {
          const card = video.closest('article') || video.closest('[role="dialog"]');
          if (!card) continue;
          for (const link of card.querySelectorAll('a[href]')) {
            if (globalThis.snagVideoPage(link.href) && new URL(link.href).origin === location.origin) return link.href;
          }
          // TikTok's feed carries no permalink anchor at all. The handle is on
          // the author link and the video id on the overflow button, so build
          // the permalink from the two and let snagVideoPage validate it.
          if (/^(www\.)?tiktok\.com$/.test(location.hostname)) {
            const handle = [...card.querySelectorAll('a[href^="/@"]')]
              .map(a => a.getAttribute('href'))
              .find(href => /^\/@[^/]+$/.test(href || ''));
            const id = card.querySelector('[data-more-menu-item-id]')
              ?.getAttribute('data-more-menu-item-id');
            if (handle && /^\d+$/.test(id || '')) {
              const composed = `${location.origin}${handle}/video/${id}`;
              if (globalThis.snagVideoPage(composed)) return composed;
            }
          }
        }
      }
      return '';
    }
    const page = new URL(location.href);
    const id = page.searchParams.get('v');
    return page.pathname === '/watch' && /^[A-Za-z0-9_-]{11}$/.test(id || '') ? id : '';
  }

  function showNotice(text) {
    if (!notice) {
      notice = document.createElement('div');
      notice.id = 'snag-youtube-notice';
      notice.setAttribute('role', 'status');
      notice.setAttribute('aria-live', 'polite');
      document.body.append(notice);
    }
    notice.textContent = text;
    notice.hidden = false;
    clearTimeout(noticeTimer);
    noticeTimer = setTimeout(() => { notice.hidden = true; }, 8000);
  }

  function mount() {
    scheduled = false;
    const id = videoId();
    const old = document.querySelector('#snag-youtube-button');
    const alwaysShow = /^(www\.)?(x\.com|twitter\.com|instagram\.com)$/.test(location.hostname);
    if (!id && !alwaysShow) { old?.remove(); closeMenu(); currentVideo = ''; return; }
    if (currentVideo !== id) {
      currentVideo = id;
      closeMenu();
      if (notice) notice.hidden = true;
    }
    let row = document.querySelector('ytd-watch-metadata #actions #top-level-buttons-computed')
      || document.querySelector('ytd-watch-metadata #top-level-buttons-computed')
      || document.querySelector('ytd-watch-flexy #menu-container #top-level-buttons-computed');
    if (location.hostname !== 'www.youtube.com') {
      row = document.querySelector('#snag-floating-controls');
      if (!row) {
        row = document.createElement('div'); row.id = 'snag-floating-controls';
        if (/^(www\.)?instagram\.com$/.test(location.hostname)) row.classList.add('snag-instagram');
        document.body.append(row);
      }
    }
    if (!row) return;
    if (old?.parentElement === row) { resetButton(); return; }
    old?.remove();
    const button = document.createElement('button');
    button.id = 'snag-youtube-button';
    button.type = 'button';
    button.textContent = 'SNAG';
    button.style.setProperty('--snag-logo', `url("${chrome.runtime.getURL('logo.png')}")`);
    button.title = 'Send this video to the SNAG Windows app';
    button.setAttribute('aria-label', 'Send this video to SNAG');
    button.setAttribute('aria-expanded', 'false');
    button.disabled = busy;
    row.append(button);
  }

  // Delegate from the document: YouTube can clone or replace the button's row,
  // which would discard a listener attached directly to our original button.
  document.addEventListener('click', async event => {
      const button = event.target.closest?.('#snag-youtube-button');
      if (!button) return;
      // Ignore scripted clicks dispatched by the website.
      if (!event.isTrusted || busy) return;
      event.preventDefault();
      event.stopPropagation();
      if (!videoId()) {
        showNotice('Open the video’s individual post or reel, then click SNAG. This feed layout could not be read.');
        return;
      }
      if (menu) { closeMenu(); return; }
      const selectedVideo = videoId();
      menu = document.createElement('div');
      menu.id = 'snag-quality-menu';
      menu.style.setProperty('--snag-logo', `url("${chrome.runtime.getURL('logo.png')}")`);
      menu.setAttribute('aria-label', 'Download quality');
      const heading = document.createElement('strong');
      heading.textContent = 'Download with SNAG';
      menu.append(heading);
      for (const [quality, label] of [['auto', 'Best available'], ['1080', '1080p'], ['720', '720p'], ['480', '480p'], ['mp3', 'Audio · MP3']]) {
        const choice = document.createElement('button');
        choice.type = 'button'; choice.textContent = label;
        choice.addEventListener('click', async event => {
          if (!event.isTrusted || busy || videoId() !== selectedVideo) return;
          event.preventDefault(); event.stopPropagation();
          closeMenu();
      busy = true;
      button.disabled = true;
      button.textContent = 'Sending…';
      try {
        const result = await chrome.runtime.sendMessage(location.hostname === 'www.youtube.com'
          ? {type: 'send-youtube', quality, videoId: selectedVideo}
          : {type: 'send-page', quality, pageUrl: selectedVideo});
        if (!result?.ok) throw new Error(result?.error || 'Could not send this video. Refresh YouTube and try again.');
        showNotice('Download started in SNAG. Use the tray menu to open your download folder.');
      } catch (error) {
        showNotice(error.message || 'Reload the extension and refresh YouTube.');
      } finally {
        busy = false;
        resetButton();
      }
        });
        menu.append(choice);
      }
      const folder = document.createElement('button');
      folder.type = 'button'; folder.textContent = 'Choose download folder…';
      folder.addEventListener('click', async event => {
        if (!event.isTrusted || busy || videoId() !== selectedVideo) return;
        event.preventDefault(); event.stopPropagation(); closeMenu();
        busy = true;
        showNotice('Choose a folder in the Windows dialog.');
        try {
          const result = await chrome.runtime.sendMessage(location.hostname === 'www.youtube.com'
            ? {type: 'choose-folder', videoId: selectedVideo}
            : {type: 'choose-folder', pageUrl: selectedVideo});
          if (!result?.ok) throw new Error(result?.error || 'Could not choose folder.');
          showNotice((result.cancelled ? 'Folder unchanged: ' : 'Downloads will save to: ') + result.folder);
        } catch (error) { showNotice(error.message); }
        finally { busy = false; resetButton(); }
      });
      menu.append(folder);
      document.body.append(menu);
      const rect = button.getBoundingClientRect();
      menu.style.left = Math.max(8, Math.min(rect.left, innerWidth - 232)) + 'px';
      menu.style.top = Math.max(8, Math.min(rect.bottom + 8, innerHeight - menu.offsetHeight - 8)) + 'px';
      button.setAttribute('aria-expanded', 'true');
      menu.querySelector('button').focus();
    }, true);

  function schedule() {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(mount);
  }
  new MutationObserver(schedule).observe(document.documentElement, {childList: true, subtree: true});
  document.addEventListener('yt-navigate-start', closeMenu);
  document.addEventListener('yt-navigate-finish', () => {
    closeMenu();
    // Do not rely on an animation-frame callback from the previous page.
    scheduled = false;
    mount();
  });
  window.addEventListener('popstate', schedule);
  window.addEventListener('scroll', schedule, {passive: true});
  // Some sites update history without a DOM change or a navigation event.
  setInterval(() => { if (videoId() !== currentVideo) schedule(); }, 750);
  schedule();
})();
