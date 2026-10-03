const field = document.querySelector('#page');
const button = document.querySelector('#send');
const status = document.querySelector('#status');

// Read the version from the manifest rather than repeating it in the markup,
// where it drifts out of date the moment the manifest is bumped. Guarded so a
// failure here can never stop the rest of the popup wiring itself up.
try {
  document.querySelector('#ver').textContent = chrome.runtime.getManifest().version;
} catch { document.querySelector('#ver').closest('footer').textContent =
  'Start the SNAG Windows app first.'; }

const usable = value => /^https?:\/\/\S+$/i.test((value || '').trim());

function refresh() {
  button.disabled = !usable(field.value);
  button.textContent = 'Send this page to SNAG';
}

(async () => {
  button.disabled = true;
  const [tab] = await chrome.tabs.query({active: true, currentWindow: true});
  field.value = tab?.url || '';
  const {lastError} = await chrome.storage.local.get('lastError');
  if (lastError) status.textContent = lastError;
  if (!usable(field.value)) {
    field.placeholder = 'Paste a link';
    status.textContent = 'Open a website first, or paste a link above. Browser settings pages cannot be sent.';
  }
  refresh();
})();

field.addEventListener('input', () => { status.textContent = ''; refresh(); });
field.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !button.disabled) button.click();
});

button.addEventListener('click', async () => {
  button.disabled = true;
  status.textContent = 'Connecting to SNAG…';
  try {
    const result = await chrome.runtime.sendMessage({type: 'send', url: field.value.trim()});
    if (!result?.ok) throw new Error(result?.error || 'Could not connect. Try again.');
    await chrome.storage.local.remove('lastError');
    await chrome.action.setBadgeText({text: ''});
    await chrome.action.setTitle({title: 'Send to SNAG'});
    status.textContent = 'Sent. Choose your quality in the SNAG tab.';
  } catch (error) { status.textContent = error.message; }
  finally { refresh(); }
});
