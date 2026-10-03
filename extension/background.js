import './site-rules.js';
export function validLink(value) {
  try {
    const u = new URL(value);
    return ['http:', 'https:'].includes(u.protocol) && !u.username && !u.password;
  } catch { return false; }
}

async function sendToSnag(url) {
  if (!validLink(url)) throw new Error('Open a regular website or choose a web link first.');
  try {
    const response = await fetch('http://127.0.0.1:8765/', {signal: AbortSignal.timeout(3000)});
    if (!response.ok || !(await response.text()).includes('id="grabForm"')) {
      throw new Error('Unexpected app');
    }
  } catch {
    throw new Error('Start SNAG on Windows first and leave it running in the system tray, then try again.');
  }
  // A separate tab prevents replacing a running download in an existing SNAG tab.
  const tab = await chrome.tabs.create({url: 'http://127.0.0.1:8765/'});
  const deadline = Date.now() + 10000;
  while (Date.now() < deadline) {
    const current = await chrome.tabs.get(tab.id);
    if (current.status === 'complete') {
      const results = await chrome.scripting.executeScript({
        target: {tabId: tab.id},
        func: (link) => {
          const input = document.querySelector('#url');
          const form = document.querySelector('#grabForm');
          if (!input || !form) return false;
          input.value = link;
          input.dispatchEvent(new Event('input', {bubbles: true}));
          form.requestSubmit();
          return true;
        },
        args: [url]
      });
      if (!results[0]?.result) throw new Error('This SNAG version has an unsupported interface.');
      return;
    }
    await new Promise(resolve => setTimeout(resolve, 150));
  }
  throw new Error('SNAG took too long to open. Try again.');
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({id: 'snag-link', title: 'Send link to SNAG', contexts: ['link'], targetUrlPatterns: ['http://*/*', 'https://*/*']});
    chrome.contextMenus.create({id: 'snag-page', title: 'Send this page to SNAG', contexts: ['page'], documentUrlPatterns: ['http://*/*', 'https://*/*']});
  });
});

chrome.runtime.onMessage.addListener((message, sender, reply) => {
  if (sender.id !== chrome.runtime.id) return;
  let url;
  if (sender.url === chrome.runtime.getURL('popup.html') && message.type === 'send') {
    url = message.url;
  } else if (['send-youtube', 'send-page', 'choose-folder'].includes(message.type) && sender.tab && sender.frameId === 0) {
    // Trust the browser's sender URL, never a URL supplied by the page.
    try {
      const host = new URL(sender.url).hostname.replace(/^www\./, '');
      if (!['youtube.com','tiktok.com','x.com','twitter.com','instagram.com','vimeo.com','twitch.tv','clips.twitch.tv','soundcloud.com','reddit.com'].includes(host)) return;
    } catch { return; }
    // sender.url can remain the original document URL after YouTube SPA navigation.
    chrome.tabs.get(sender.tab.id).then(tab => {
      const page = new URL(tab.url);
      if (message.type === 'send-page' || (message.type === 'choose-folder' && message.pageUrl)) {
        const target = new URL(message.pageUrl);
        if (!globalThis.snagVideoPage(target.href) || target.origin !== page.origin) throw new Error('Open a supported video or audio post first.');
        const feedSite = /^(www\.)?(x\.com|twitter\.com|instagram\.com|tiktok\.com)$/.test(page.hostname);
        if (!feedSite && message.pageUrl !== tab.url) throw new Error('The page changed. Open the SNAG menu again.');
        handleYoutube(message, target.href, reply);
        return;
      }
      if (!globalThis.snagVideoPage(tab.url)) throw new Error('Open a supported video or audio page first.');
      const id = page.searchParams.get('v');
      if (page.origin !== 'https://www.youtube.com' || page.pathname !== '/watch' || !/^[A-Za-z0-9_-]{11}$/.test(id || '')) throw new Error('Open a YouTube video first.');
      if (message.videoId && message.videoId !== id) throw new Error('The video changed. Open the SNAG menu again.');
      handleYoutube(message, 'https://www.youtube.com/watch?v=' + id, reply);
    }).catch(error => reply({ok: false, error: error.message}));
    return true;
  } else return;
  sendToSnag(url).then(() => reply({ok: true}), error => reply({ok: false, error: error.message}));
  return true;
});

function handleYoutube(message, url, reply) {
  if (message.type === 'choose-folder') {
    fetch('http://127.0.0.1:8765/api/folder', {method: 'POST', headers: {'X-Snag-Desktop': '1'}})
      .then(async response => {
        const result = await response.json();
        if (!response.ok || !result.ok) throw new Error(result.error || 'Use the updated SNAG tray app for folder selection.');
        reply(result);
      }).catch(error => reply({ok: false, error: error.message === 'Failed to fetch' ? 'Start the updated SNAG tray app first.' : error.message}));
    return true;
  }
  if (['send-youtube', 'send-page'].includes(message.type) && message.quality !== undefined) {
    if (!['auto', '1080', '720', '480', 'mp3'].includes(message.quality)) {
      reply({ok: false, error: 'Choose a supported quality.'});
      return;
    }
    downloadInSnag(url, message.quality).then(job => reply({ok: true, jobId: job}), error => reply({ok: false, error: error.message}));
  } else sendToSnag(url).then(() => reply({ok: true}), error => reply({ok: false, error: error.message}));
}

async function downloadInSnag(url, quality) {
  let response;
  try {
    response = await fetch('http://127.0.0.1:8765/api/download', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url, quality}),
      signal: AbortSignal.timeout(10000)
    });
  } catch {
    throw new Error('Could not reach SNAG. Start the Windows app and leave it running in the system tray. Check SNAG before retrying to avoid a duplicate download.');
  }
  const result = await response.json();
  if (!response.ok || !result.ok || !result.job_id) throw new Error(result.error || 'SNAG could not start the download.');
  return result.job_id;
}

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!['snag-link', 'snag-page'].includes(info.menuItemId)) return;
  try {
    await sendToSnag(info.menuItemId === 'snag-link' ? info.linkUrl : (info.pageUrl || tab?.url));
    await chrome.storage.local.remove('lastError');
    await chrome.action.setBadgeText({text: ''});
  } catch (error) {
    await chrome.storage.local.set({lastError: error.message});
    await chrome.action.setBadgeBackgroundColor({color: '#b42318'});
    await chrome.action.setBadgeText({text: '!'});
    await chrome.action.setTitle({title: error.message});
  }
});
