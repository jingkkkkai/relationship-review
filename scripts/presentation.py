"""Privacy-aware text, explicit outbound links and portable attachment presentation."""
import base64
import html
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit, unquote, parse_qsl

EMAIL = re.compile(r'(?<![A-Za-z0-9_.+-])([A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)')
PHONE = re.compile(r'(?<![A-Za-z0-9])(?:\+?886[ .()-]*9(?:[ .()-]*\d){8}|09(?:[ .()-]*\d){8}|\+(?:[ .()-]*\d){8,15}|\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4})(?![A-Za-z0-9])')


def mask(value):
    text = str(value)
    # Match full-width contact spellings without normalizing unrelated chat text.
    text = re.sub(r'[A-Za-z0-9\uff01-\uff5e@.+_() -]+',
                  lambda m: _mask_ascii(unicodedata.normalize('NFKC', m[0]))
                  if EMAIL.search(unicodedata.normalize('NFKC', m[0])) or PHONE.search(unicodedata.normalize('NFKC', m[0])) else m[0], text)
    return _mask_ascii(text)


def _mask_ascii(text):
    text = EMAIL.sub(lambda m: m[1][:1] + '***@' + m[2][:1] + '***.' + m[2].rsplit('.', 1)[-1], text)
    return PHONE.sub(lambda m: ('+' if m[0].startswith('+') else '') + re.sub(r'\D', '', m[0])[:3] + '****' + re.sub(r'\D', '', m[0])[-3:], text)


def esc(value):
    return html.escape(mask(value), quote=True)


def attr(value):
    """Structural IDs, never user text. Preserve exact IDs for working anchors."""
    return html.escape(str(value), quote=True)


SOCIAL_DOMAINS = ('instagram.com', 'threads.net', 'threads.com')
PRIVATE_QUERY_KEYS = {'access_token', 'token', 'auth', 'authorization', 'password', 'secret', 'signature', 'credential', 'x-amz-signature', 'x-amz-credential'}


def social_host(host):
    return bool(host) and any(host == domain or host.endswith('.' + domain) for domain in SOCIAL_DOMAINS)


def safe_url(value, platform=None):
    """Validate URL structure, never redact identifiers or rewrite the target."""
    if not isinstance(value, str) or not value or any(ord(c) <= 32 or ord(c) == 127 for c in value):
        return None
    try:
        url = urlsplit(value)
        host = url.hostname
        if url.scheme not in ('http', 'https') or not host or url.username or url.password:
            return None
        _ = url.port
        if '\\' in value:
            return None
        allowed = {'reel': ('instagram.com',), 'threads_post': ('threads.net', 'threads.com')}
        if platform in allowed and not any(host == d or host.endswith('.' + d) for d in allowed[platform]):
            return None
    except ValueError:
        return None
    return value


def private_text_url(value):
    """Check prose links separately; social profile paths are identifiers, not contacts."""
    parsed = urlsplit(value)
    path = '' if social_host(parsed.hostname) else parsed.path
    probe = unquote(unquote(path + '?' + parsed.query + '#' + parsed.fragment))
    return mask(probe) != probe or any(key.lower() in PRIVATE_QUERY_KEYS for key, _ in parse_qsl(parsed.query))


def link(url, label, platform=None, *, attachment=False):
    target = safe_url(url, platform)
    if target and not attachment and private_text_url(target):
        target = None
    if not target:
        return '（連結含個資或無法安全顯示，先不提供）' if str(label).startswith(('http://', 'https://')) else esc(label)
    # A validated URL label must not go through the contact regex a second time.
    caption = attr(label) if str(label) == target else esc(label)
    return f'<a href="{attr(target)}" target="_blank" rel="noopener noreferrer" referrerpolicy="no-referrer">{caption}</a>'


def linked_text(value):
    text = str(value)
    result, start = [], 0
    for match in re.finditer(r'https?://[^\s<>"\x27）。，；！？]+', text):
        url = match.group().rstrip('.,;!')
        result.append(esc(text[start:match.start()]))
        result.append(link(url, url))
        start = match.start() + len(url)
    result.append(esc(text[start:]))
    return ''.join(result)


MIMES = {
    'image/png': ('image', 'sticker'), 'image/jpeg': ('image', 'sticker'),
    'image/gif': ('image', 'sticker'), 'image/webp': ('image', 'sticker'),
    'audio/mpeg': ('audio',), 'audio/mp4': ('audio',), 'audio/ogg': ('audio',),
    'audio/wav': ('audio',), 'video/mp4': ('video',), 'video/webm': ('video',),
    'application/pdf': ('file',), 'text/plain': ('file',)
}
LABELS = {'image': '(圖片)', 'sticker': '(貼圖)', 'video': '(影片)', 'audio': '(語音)', 'file': '(附件)'}


class Materials:
    """Embed only supplied local files under an explicitly chosen root. No fetching."""
    def __init__(self, root=None):
        self.root = Path(root).resolve() if root is not None else None
        self.total = 0
        self.cache = {}

    def render(self, item):
        if not isinstance(item, dict) or item.get('type') not in LABELS:
            raise ValueError('media 須有已確認的 type：image/sticker/video/audio/file')
        kind = item['type']
        label = LABELS[kind]
        if not item.get('path') and not item.get('url'):
            return '<p class="media">' + esc(label + ' ' + item.get('reason', '匯出檔沒有附原檔')) + '</p>'
        if not item.get('path'):
            if item.get('url') and safe_url(item['url']):
                return '<p class="media">' + link(item['url'], label + ' 開啟原始連結', attachment=True) + '（只有外部連結，不會自動開啟）</p>'
            return '<p class="media">' + esc(label + ' ' + item.get('reason', '匯出檔沒有附原檔')) + '</p>'
        if self.root is None:
            raise ValueError('嵌入本機附件時須指定 --materials-root，不可默默只留標記')
        raw = item['path']
        if not isinstance(raw, str) or Path(raw).is_absolute():
            raise ValueError('media.path 須為 materials-root 下的相對路徑')
        path = (self.root / raw).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError('附件路徑超出本次資料範圍')
        if not path.is_file():
            return '<p class="media">' + esc(label + ' 找不到原檔') + '</p>'
        mime = item.get('mime')
        if mime not in MIMES or kind not in MIMES[mime]:
            raise ValueError('附件 MIME 與種類不符或不支援；不可嵌入 HTML、SVG 或執行檔')
        key = (path, mime)
        if key not in self.cache:
            size = path.stat().st_size
            if size > 25 * 1024 * 1024 or self.total + size > 100 * 1024 * 1024:
                raise ValueError('附件超過單檔 25MB 或合計 100MB；先說明並與使用者決定範圍，不靜默省略')
            payload = path.read_bytes()
            signatures = {
                'image/png': payload.startswith(b'\x89PNG\r\n\x1a\n'),
                'image/jpeg': payload.startswith(b'\xff\xd8\xff'),
                'image/gif': payload.startswith((b'GIF87a', b'GIF89a')),
                'image/webp': payload.startswith(b'RIFF') and payload[8:12] == b'WEBP',
                'application/pdf': payload.startswith(b'%PDF-'),
            }
            if mime in signatures and not signatures[mime]:
                raise ValueError('附件內容與 MIME 不符，請核對原檔')
            self.total += size
            self.cache[key] = 'data:' + mime + ';base64,' + base64.b64encode(payload).decode('ascii')
        uri = self.cache[key]
        if kind in ('image', 'sticker'):
            return f'<figure class="attachment"><img src="{uri}" alt="{esc(label)}" loading="lazy"><figcaption>{esc(label)}</figcaption></figure>'
        if kind in ('audio', 'video'):
            return f'<figure class="attachment"><{kind} controls preload="none" src="{uri}"></{kind}><figcaption>{esc(label)}</figcaption></figure>'
        suffix = '.pdf' if mime == 'application/pdf' else '.txt'
        return f'<p class="media"><a href="{uri}" download="attachment{suffix}">{esc(label)} 點此開啟或下載</a></p>'
