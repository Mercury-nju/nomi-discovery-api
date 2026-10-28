"""Evaluated anonymous public-index source extensions; no authenticated APIs.

An enabled source has produced an individually bound public profile/directory
search hit during local acceptance. It does not prove current buying intent.
"""
import re
from urllib.parse import urlsplit, parse_qs

CANDIDATES = [
    {'id': key, 'name': name, 'hosts': hosts, 'queryDomain': domain, 'queryPrefix': prefix,
     'entityType': entity, 'symbol': symbol, 'enabled': False,
     'reason': '公开索引中的账号或商家候选；摘要和身份资料仍需核验',
     'verification': 'not_tested'}
    for key, name, hosts, domain, prefix, entity, symbol in [
        ('x','X',('x.com','www.x.com','twitter.com','www.twitter.com'),'x.com','','account','X'),
        ('bluesky','Bluesky',('bsky.app',),'bsky.app','/profile/','account','Bs'),
        ('threads','Threads',('threads.com','www.threads.com','threads.net','www.threads.net'),'threads.com','/@','account','Th'),
        ('pinterest','Pinterest',('pinterest.com','www.pinterest.com'),'pinterest.com','','account','Pi'),
        ('github','GitHub',('github.com','www.github.com'),'github.com','','account','Gh'),
        ('hackernews','Hacker News',('news.ycombinator.com',),'news.ycombinator.com','/user','account','HN'),
        ('indiehackers','Indie Hackers',('indiehackers.com','www.indiehackers.com'),'indiehackers.com','','account','IH'),
        ('producthunt','Product Hunt',('producthunt.com','www.producthunt.com'),'producthunt.com','/@','account','PH'),
        ('devto','DEV Community',('dev.to',),'dev.to','','account','Dv'),
        ('behance','Behance',('behance.net','www.behance.net'),'behance.net','','account','Be'),
        ('dribbble','Dribbble',('dribbble.com','www.dribbble.com'),'dribbble.com','','account','Dr'),
        ('yelp','Yelp',('yelp.com','www.yelp.com'),'yelp.com','/biz/','business','Ye'),
        ('clutch','Clutch',('clutch.co','www.clutch.co'),'clutch.co','/profile/','business','Cl'),
        ('houzz','Houzz',('houzz.com','www.houzz.com'),'houzz.com','/pro/','business','Ho'),
        ('googlemaps','Google Maps',('google.com','www.google.com','maps.google.com'),'google.com','/maps/place/','business','Gm'),
    ]
]
HOSTS = {p['id']: p['hosts'] for p in CANDIDATES}
RESERVED = {'about','account','accounts','advertise','advertising','apps','auth','business','careers',
 'categories','collections','contact','dashboard','developers','discover','download','downloads','enterprise',
 'events','explore','features','feed','feeds','following','for-you','guidelines','help','home','i','images',
 'integrations','jobs','join','legal','login','logout','marketplace','new','notifications','organizations','orgs',
 'people','pin','press','pricing','privacy','products','projects','search','services','sessions','settings',
 'shots','signup','site','sponsors','stories','support','tags','terms','topics','trending','users','welcome'}


def normalize_profile(value, platform):
    try:
        u = urlsplit(value or '')
        if u.scheme != 'https' or u.hostname not in HOSTS.get(platform, ()) or u.username or u.password or u.port not in (None,443):
            return None
        path = u.path.strip('/')
        if platform == 'x':
            m=re.fullmatch(r'([A-Za-z0-9_]{1,15})(?:/status/\d+)?',path)
            return 'https://x.com/'+m[1].lower() if m and m[1].lower() not in RESERVED else None
        if platform == 'bluesky':
            m=re.fullmatch(r'profile/([A-Za-z0-9.:-]+)(?:/post/[A-Za-z0-9]+)?',path)
            return 'https://bsky.app/profile/'+m[1].lower() if m and ('.' in m[1] or m[1].startswith('did:')) else None
        if platform in ('threads','producthunt'):
            m=re.fullmatch(r'@([A-Za-z0-9_.-]+)(?:/post/[A-Za-z0-9_-]+)?',path)
            return ('https://www.threads.com/@' if platform=='threads' else 'https://www.producthunt.com/@')+m[1].lower() if m else None
        if platform == 'hackernews':
            ident=parse_qs(u.query).get('id',[''])[0]
            return 'https://news.ycombinator.com/user?id='+ident if path=='user' and re.fullmatch(r'[A-Za-z0-9_-]+',ident) else None
        if platform in ('yelp','clutch','houzz'):
            prefix={'yelp':'biz','clutch':'profile','houzz':'pro'}[platform]
            m=re.fullmatch(prefix+r'/([A-Za-z0-9_-]+)',path)
            origin={'yelp':'https://www.yelp.com/','clutch':'https://clutch.co/','houzz':'https://www.houzz.com/'}[platform]
            return origin+prefix+'/'+m[1] if m else None
        if platform == 'googlemaps':
            # Only a place result with a stable CID is accepted, not a search URL.
            query=parse_qs(u.query);cid=query.get('cid',[''])[0]
            if path in ('maps','maps/place') and cid.isdigit():
                return 'https://www.google.com/maps?cid='+cid
            if path.startswith('maps/place/') and re.search(r'!1s0x[0-9a-f]+:0x[0-9a-f]+',path):
                return 'https://www.google.com/'+path
            return None
        if platform in ('pinterest','github','indiehackers','devto','behance','dribbble'):
            if not re.fullmatch(r'[A-Za-z0-9_-]+',path) or path.lower() in RESERVED:
                return None
            origins={'pinterest':'https://www.pinterest.com/','github':'https://github.com/',
                     'indiehackers':'https://www.indiehackers.com/','devto':'https://dev.to/',
                     'behance':'https://www.behance.net/','dribbble':'https://dribbble.com/'}
            return origins[platform]+path.lower()
    except (ValueError,KeyError):
        return None
    return None

ENABLED_IDS = frozenset({'x', 'github', 'behance', 'yelp', 'clutch', 'houzz'})
for _entry in CANDIDATES:
    _entry['enabled'] = _entry['id'] in ENABLED_IDS
    _entry['verification'] = 'public_index_candidate_found' if _entry['enabled'] else 'no_valid_profile_found'
    if not _entry['enabled']:
        _entry['reason'] = '本轮匿名公开索引未返回可识别主页，未开放执行'



def is_usable_result(row, platform):
    """Require a named, individually bound indexed result, never a generic wall."""
    if not normalize_profile(row.get('href') or row.get('url'), platform):
        return False
    title = ' '.join(str(row.get('title') or '').split())
    body = ' '.join(str(row.get('body') or row.get('snippet') or '').split())
    if not title or len(title) > 180 or len(body) > 1200:
        return False
    lowered = title.casefold()
    walls = ('sign in', 'log in', 'login', 'sign up', 'signup', 'access denied', 'just a moment', 'security check', 'verify you are human', 'captcha')
    if any(w in lowered for w in walls):
        return False
    generic = {p['name'].casefold() for p in CANDIDATES} | {'home', 'explore', 'search', 'profile', 'user', 'welcome', 'login', 'join us'}
    if lowered.strip(' -|·/') in generic:
        return False
    # Multiple canonical platform suffixes suggest concatenated SERP containers.
    for token in (' / x', ' - github', ' · github', ' - yelp', ' - houzz', ' - behance', ' | clutch'):
        if lowered.count(token) > 1:
            return False
    return True
