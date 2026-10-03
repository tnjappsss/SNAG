globalThis.snagVideoPage = function(value) {
  try {
    const u = new URL(value);
    if (u.protocol !== 'https:' || u.username || u.password) return false;
    const host = u.hostname.replace(/^www\./, '');
    const path = u.pathname;
    if (host === 'youtube.com') return path === '/watch' && /^[\w-]{11}$/.test(u.searchParams.get('v') || '');
    if (host === 'tiktok.com') return /^\/@[^/]+\/video\/\d+\/?$/.test(path);
    if (host === 'x.com' || host === 'twitter.com') return /^\/(?:[^/]+\/status|i\/web\/status)\/\d+(?:\/.*)?$/.test(path);
    if (host === 'instagram.com') return /^\/(?:[^/]+\/)?(reel|reels|p|tv)\/[^/]+\/?$/.test(path);
    if (host === 'vimeo.com') return /^\/\d+\/?$/.test(path);
    if (host === 'twitch.tv') return /^\/videos\/\d+\/?$/.test(path) || /^\/[^/]+\/clip\/[^/]+\/?$/.test(path);
    if (host === 'clips.twitch.tv') return /^\/[^/]+\/?$/.test(path);
    if (host === 'soundcloud.com') return /^\/[^/]+\/[^/]+\/?$/.test(path) && !path.includes('/sets/');
    if (host === 'reddit.com') return /^\/r\/[^/]+\/comments\/[^/]+(?:\/.*)?$/.test(path);
    return false;
  } catch { return false; }
};
