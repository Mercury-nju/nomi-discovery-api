"""Anonymous search-index discovery, deliberately separate from verified statements.

DDGS supplies public search results. Only stable social profile identities are
admitted; snippets never become first-person quotes or verified intent. Fetching
an original page is a separate availability check, not proof of its claims.
"""
import asyncio
import hashlib
import importlib.util
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urljoin, urlsplit

HOSTS = {
    'douyin': ('douyin.com', 'www.douyin.com'),
    'tiktok': ('tiktok.com', 'www.tiktok.com'),
    'instagram': ('instagram.com', 'www.instagram.com'),
    'youtube': ('youtube.com', 'www.youtube.com', 'm.youtube.com'),
    'facebook': ('facebook.com', 'www.facebook.com', 'm.facebook.com'),
    'linkedin': ('linkedin.com', 'www.linkedin.com'),
    'reddit': ('reddit.com', 'www.reddit.com', 'old.reddit.com'),
}
from .platform_extensions import EXTENSIONS, normalize_profile as extension_profile, entity_type as extension_entity, is_usable_result as extension_usable
EXTENSION_MAP = {p['id']: p for p in EXTENSIONS}
HOSTS.update({p['id']: tuple(p['hosts']) for p in EXTENSIONS})

RESERVED = {'accounts', 'about', 'help', 'login', 'signup', 'search', 'explore',
            'reels', 'reel', 'p', 'tv', 'stories', 'direct', 'privacy', 'legal',
            'terms', 'share', 'sharer', 'watch', 'groups', 'events', 'marketplace',
            'business', 'ads', 'policies', 'settings', 'home', 'pages', 'photo.php',
            'photos', 'videos', 'posts', 'feed', 'gaming', 'hashtag'}


def profile_url(value, platform):
    """Return a stable profile URL only when the URL itself establishes identity."""
    if platform in EXTENSION_MAP:
        return extension_profile(value, platform)
    try:
        parsed = urlsplit(value or '')
        if parsed.scheme != 'https' or parsed.hostname not in HOSTS[platform] or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        path = parsed.path.strip('/')
        if platform == 'reddit':
            match = re.fullmatch(r'(?:user|u)/([A-Za-z0-9_-]{3,20})', path)
            if match and match[1].lower() not in {'deleted', 'removed', 'automoderator'}:
                return 'https://www.reddit.com/user/' + match[1].lower() + '/'
            return None
        if platform == 'linkedin' and re.fullmatch(r'in/[A-Za-z0-9_%.-]+', path):
            return 'https://www.linkedin.com/' + path + '/'
        if platform == 'instagram' and re.fullmatch(r'[A-Za-z0-9_.]+', path) and path.lower() not in RESERVED:
            return 'https://www.instagram.com/' + path.lower() + '/'
        if platform == 'tiktok':
            match = re.fullmatch(r'@([A-Za-z0-9_.]+)(?:/video/\d+)?', path)
            return 'https://www.tiktok.com/@' + match[1] if match else None
        if platform == 'douyin' and re.fullmatch(r'user/[A-Za-z0-9_-]+', path):
            return 'https://www.douyin.com/' + path
        if platform == 'youtube' and re.fullmatch(r'(?:@[A-Za-z0-9_.%-]+|channel/UC[A-Za-z0-9_-]+)', path):
            return 'https://www.youtube.com/' + path
        if platform == 'facebook':
            if path == 'profile.php':
                ident = parse_qs(parsed.query).get('id', [''])[0]
                return 'https://www.facebook.com/profile.php?id=' + ident if ident.isdigit() else None
            if re.fullmatch(r'people/[^/]+/\d+', path):
                return 'https://www.facebook.com/' + path + '/'
            match = re.fullmatch(r'([A-Za-z0-9_.]+)(?:/posts/[A-Za-z0-9_-]+)?', path)
            if match and match[1].lower() not in RESERVED:
                return 'https://www.facebook.com/' + match[1] + '/'
    except (ValueError, KeyError):
        return None
    return None


def make_candidate(item, platform, query, engine):
    if platform in EXTENSION_MAP and not extension_usable(item, platform):
        return None
    source_url = item.get('href') or item.get('url') or ''
    profile = profile_url(source_url, platform)
    snippet = str(item.get('body') or item.get('snippet') or '').strip()
    title = str(item.get('title') or '').strip()
    # Do not rescue contaminated aggregate SERP rows by truncating them.
    if len(title) > 180 or len(snippet) > 1200 or re.search(r'(?:LinkedIn|Instagram|Facebook|TikTok).*(?:LinkedIn|Instagram|Facebook|TikTok)', title, re.I):
        return None
    if not profile or not (snippet or title):
        return None
    stamp = datetime.now(timezone.utc).isoformat()
    label = title or urlsplit(profile).path.strip('/')
    source = {
        'id': hashlib.sha256((source_url + '|' + query).encode()).hexdigest()[:24],
        'type': 'search_snippet', 'evidenceLevel': 'search_snippet',
        'verifiedStatement': False, 'title': title, 'text': snippet,
        'url': source_url, 'discoveredAt': stamp, 'searchQuery': query,
        'searchUrl': 'https://www.google.com/search?' + urlencode({'q': query}) if engine == 'google' else
                     'https://search.yahoo.com/search?' + urlencode({'p': query}) if engine == 'yahoo' else
                     'https://www.bing.com/search?' + urlencode({'q': query}) if engine == 'bing' else
                     'https://duckduckgo.com/?' + urlencode({'q': query}),
        'searchProvider': engine, 'originalPageStatus': 'not_checked',
        'verificationReason': '搜索索引摘要，不是已核验的本人原话；身份、资料与需求均待原页核对',
    }
    return {'platformId': platform + ':' + profile, 'profileUrl': profile,
            'nickname': label, 'profileText': '', 'entityType': extension_entity(profile, platform), 'sources': [source], 'demo': False}


async def search_process(query, limit, cancelled):
    proc = await asyncio.create_subprocess_exec(sys.executable, '-m', 'server.public_search',
        '--search', stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=str(Path(__file__).resolve().parent.parent),
        creationflags=0x08000000 if os.name == 'nt' else 0)
    pending = asyncio.create_task(proc.communicate(json.dumps({'query': query, 'limit': limit}).encode()))
    deadline = asyncio.get_running_loop().time() + 45
    try:
        while not pending.done():
            if cancelled():
                raise asyncio.CancelledError()
            if asyncio.get_running_loop().time() > deadline:
                raise ValueError('公开搜索服务响应超时，本轮停止；未伪造结果')
            await asyncio.wait({pending}, timeout=.2)
        stdout, _ = await pending
        if proc.returncode:
            raise ValueError('公开搜索服务当前不可用；没有取得可核验的搜索结果')
        return json.loads(stdout.decode('utf-8'))
    finally:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        if not pending.done():
            await pending


async def check_original(url, platform):
    """No arbitrary redirects, cookies, credentials, or authenticated browser state."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=False,
                                     headers={'User-Agent': 'Mozilla/5.0 NomiScout public-page-check'}) as client:
            current = url
            for _ in range(3):
                parsed = urlsplit(current)
                if parsed.scheme != 'https' or parsed.hostname not in HOSTS[platform] or parsed.username or parsed.password or parsed.port not in (None, 443):
                    return 'restricted', '原页跳转到不支持的地址，停止访问；摘要仍未核验'
                async with client.stream('GET', current) as response:
                    if response.is_redirect:
                        current = urljoin(current, response.headers.get('location', ''))
                        continue
                    if response.status_code in (401, 403, 429, 999):
                        return 'restricted', '原页访问受限或限流；没有绕过，搜索摘要仍未核验'
                    if response.status_code != 200:
                        return 'unavailable', '原页未成功返回；保留搜索发现路径，资料待核实'
                    if 'html' not in response.headers.get('content-type', ''):
                        return 'unavailable', '原页不是可核验的网页内容'
                    parts, size = [], 0
                    async for part in response.aiter_bytes():
                        parts.append(part)
                        size += len(part)
                        if size >= 250000:
                            break
                    html = b''.join(parts).decode('utf-8', errors='replace').lower()
                if any(x in urlsplit(current).path.lower() for x in ('login', 'checkpoint', 'challenge', 'authwall')):
                    return 'restricted', '原页要求登录或验证；保持匿名，不继续读取'
                if any(x in html for x in ('captcha', 'verify you are human', 'security challenge', 'access denied')):
                    return 'restricted', '原页出现访问验证；保持匿名，不继续读取'
                return 'reachable_unverified', '原页可访问，但尚未提取并核验本人陈述；搜索摘要不升级为需求证据'
    except Exception:
        return 'unavailable', '原页访问失败；搜索摘要仍未核验，不能确认当前资料或需求'
    return 'restricted', '原页跳转过多，已停止访问'


class PublicSearchAdapter:
    capabilities = ('public_search',)
    def __init__(self, data_dir, platform):
        if platform not in HOSTS:
            raise ValueError('Unsupported platform')
        self.data_dir, self.platform = Path(data_dir), platform

    async def status(self):
        installed = importlib.util.find_spec('ddgs') is not None
        return {'connected': installed, 'status': 'anonymous_ready' if installed else 'dependency_required',
                'verified': False, 'reason': '免登录公开搜索已配置；搜索候选与本人需求证据分开核验' if installed else '请安装公开搜索依赖 requirements-search.txt'}

    async def login(self):
        return await self.status()

    async def close(self):
        pass

    async def discover(self, plan, emit, cancelled):
        if plan.get('sourceType') != 'public_search':
            raise ValueError('此连接器仅支持公开网页搜索')
        if not (await self.status())['connected']:
            raise ValueError('公开搜索依赖未安装')
        keywords = [str(k).strip() for k in plan.get('keywords', []) if str(k).strip()][:3]
        if not keywords:
            raise ValueError('公开搜索需要关键词')
        limit = min(max(int(plan.get('scanLimit', 10)), 1), 30)
        profiles, failures = {}, []
        domain = EXTENSION_MAP.get(self.platform, {}).get('queryDomain', self.platform + '.com')
        qualifier = '/in/' if self.platform == 'linkedin' else '/user/' if self.platform == 'reddit' else EXTENSION_MAP.get(self.platform, {}).get('queryPrefix', '')
        for keyword in keywords:
            if cancelled() or len(profiles) >= limit:
                break
            query = f'site:{domain}{qualifier} {keyword}'
            await emit({'type': 'step', 'name': '搜索公开网页', 'status': 'running', 'reason': query})
            try:
                results = await search_process(query, min(30, limit * 3), cancelled)
            except ValueError as error:
                failures.append(str(error))
                continue
            for item in results.get('items', []):
                if plan.get('workKeywords') and not any(str(k).casefold() in str(item.get('title', '')).casefold() for k in plan['workKeywords']):
                    continue
                row = make_candidate(item, self.platform, query, item.get('_engine', 'bing'))
                if row and row['profileUrl'] not in profiles:
                    profiles[row['profileUrl']] = row
                if len(profiles) >= limit:
                    break
        if cancelled():
            return []
        if not profiles:
            raise ValueError(failures[0] if failures else '公开搜索未返回可识别的目标平台主页；不能把无结果当作发现成功')
        await emit({'type': 'step', 'name': '搜索公开网页', 'status': 'completed',
                    'reason': f'取得 {len(profiles)} 个公开索引候选；仍需核验身份、资料与需求'})
        for index, row in enumerate(profiles.values()):
            if cancelled():
                break
            source = row['sources'][0]
            # Bounded page checks; remaining results explicitly retain not_checked.
            if index < min(5, plan.get('maxWorks', 10)):
                state, reason = await check_original(source['url'], self.platform)
                source.update(originalPageStatus=state, verificationReason=reason)
            await emit({'type': 'candidate', 'customer': row})
        await emit({'type': 'step', 'name': '核对公开来源', 'status': 'completed',
                    'reason': '已记录原页访问情况；所有索引摘要仍是待核实候选，没有冒充本人原话'})
        return list(profiles.values()) if not cancelled() else []


def yahoo_single_results(html_text):
    """Yahoo/DDGS may nest result containers: bind each URL to one title only.

    If a bounded one-result description cannot be established, omit it instead
    of copying nearby or descendant people's snippets into this profile.
    """
    from lxml import html
    from ddgs.engines.yahoo import extract_url
    tree = html.fromstring(html_text)
    rows, seen = [], set()
    for heading in tree.xpath('//div[contains(@class,"Title")]//h3'):
        if heading.xpath('.//h3'):
            continue
        title_spans = heading.xpath('.//span[contains(@class,"fz-20")]')
        if len(title_spans) == 1:
            title = ' '.join(title_spans[0].text_content().split())
        else:
            import copy
            clean_heading = copy.deepcopy(heading)
            # The mobile layout puts site-name/breadcrumb DIVs inside H3.
            for badge in clean_heading.xpath('.//div'):
                if badge.getparent() is not None:
                    badge.getparent().remove(badge)
            title = ' '.join(clean_heading.text_content().split())
        anchor = next(iter(heading.xpath('ancestor::a[@href][1] | .//a[@href][1]')), None)
        if anchor is None:
            parent = heading.getparent()
            anchors = parent.xpath('.//a[@href]') if parent is not None else []
            anchor = anchors[0] if len(anchors) == 1 else None
        if anchor is None:
            continue
        url = anchor.get('href') or ''
        if '/RU=' in url:
            url = extract_url(url)
        if not url.startswith('https://') or url in seen or not title or len(title) > 180 or 'http' in title.lower():
            continue
        seen.add(url)
        snippet = ''
        title_blocks = heading.xpath('ancestor::div[contains(@class,"Title")][1]')
        if title_blocks and len(title_blocks[0].xpath('.//h3')) == 1:
            container = title_blocks[0].getparent()
            # Yahoo markup nests subsequent LI results inside the first DIV.
            # Only direct sibling description belongs to this linked title.
            descriptions = container.xpath('./div[contains(@class,"Text")]') if container is not None else []
            if len(descriptions) == 1 and not descriptions[0].xpath('.//h3'):
                candidate_text = ' '.join(descriptions[0].text_content().split())
                if len(candidate_text) <= 1200:
                    snippet = candidate_text
        rows.append({'title': title, 'href': url, 'body': snippet, '_engine': 'yahoo'})
    return rows


def _search(query, limit):
    from ddgs.engines.yahoo import Yahoo
    from ddgs.engines.duckduckgo import Duckduckgo
    rows = []
    # Call actual named engines: DDGS auto fallback can change provider silently.
    for engine, cls in (('yahoo', Yahoo), ('duckduckgo', Duckduckgo)):
        try:
            client = cls(timeout=8)
            if engine == 'yahoo':
                payload = client.build_payload(query, 'us-en', 'moderate', None)
                page = client.request('GET', client.search_url, params=payload)
                found = yahoo_single_results(page) if page else []
            else:
                client.items_xpath = "//div[contains(@class, 'body')][count(.//h2)=1]"
                client.elements_xpath = {'title': './/a[contains(@class,"result__a")]//text()',
                                         'href': './/a[contains(@class,"result__a")]/@href',
                                         'body': './/a[contains(@class,"result__snippet")]//text()'}
                found = [vars(row) for row in (client.search(query) or [])]
            useful = [dict(row, _engine=engine) for row in found if row.get('href') and row.get('title') and len(row.get('title', '')) <= 180 and len(row.get('body', '')) <= 1200]
            rows.extend(useful)
            if useful:
                break
        except Exception:
            continue
    return {'items': rows[:limit]}


if __name__ == '__main__':
    import contextlib
    payload = json.loads(sys.stdin.buffer.read().decode('utf-8'))
    with contextlib.redirect_stdout(sys.stderr):
        result = _search(payload['query'], payload['limit'])
    print(json.dumps(result, ensure_ascii=True))
