"""China source candidates. Enable only after a bounded real index acceptance.

A normalized profile/organization URL is an indexed candidate, not verified
personal identity or purchase intent. Post URLs never imply their author's ID.
"""
import re
from urllib.parse import urlsplit

CANDIDATES = [
 {'id': key, 'name': name, 'hosts': hosts, 'queryDomain': domain, 'queryPrefix': prefix,
  'entityType': kind, 'symbol': symbol, 'reason': '免登录公开索引候选；原页及需求仍待核验'}
 for key,name,hosts,domain,prefix,kind,symbol in [
 ('xiaohongshu','小红书',('www.xiaohongshu.com','xiaohongshu.com'),'xiaohongshu.com','/user/profile/','account','红'),
 ('zhihu','知乎',('www.zhihu.com','zhihu.com'),'zhihu.com','/people/','account','知'),
 ('bilibili','B站',('space.bilibili.com',),'space.bilibili.com','','account','B站'),
 ('weibo','微博',('weibo.com','www.weibo.com'),'weibo.com','/u/','account','微'),
 ('kuaishou','快手',('www.kuaishou.com','kuaishou.com'),'kuaishou.com','/profile/','account','快'),
 ('douban','豆瓣',('www.douban.com','douban.com'),'douban.com','/people/','account','豆'),
 ('v2ex','V2EX',('www.v2ex.com','v2ex.com'),'v2ex.com','/member/','account','V2'),
 ('juejin','掘金',('juejin.cn',),'juejin.cn','/user/','account','掘'),
 ('csdn','CSDN',('blog.csdn.net',),'blog.csdn.net','','account','C'),
 ('qichacha','企查查',('www.qcc.com','qcc.com'),'qcc.com','/firm/','organization','企'),
 ('tianyancha','天眼查',('www.tianyancha.com','tianyancha.com'),'tianyancha.com','/company/','organization','天'),
 ('dianping','大众点评',('www.dianping.com','dianping.com'),'dianping.com','/shop/','business','评'),
 ]
]
RULES = {
 'xiaohongshu': (r'user/profile/[a-fA-F0-9]{24}', 'www.xiaohongshu.com'),
 'zhihu': (r'(?:people|org)/[A-Za-z0-9_.%-]+', 'www.zhihu.com'),
 'bilibili': (r'[0-9]+', 'space.bilibili.com'),
 'weibo': (r'(?:u/)?[0-9]+', 'weibo.com'),
 'kuaishou': (r'profile/[A-Za-z0-9_-]+', 'www.kuaishou.com'),
 'douban': (r'people/[A-Za-z0-9_.-]+', 'www.douban.com'),
 'v2ex': (r'member/[A-Za-z0-9_]+', 'www.v2ex.com'),
 'juejin': (r'user/[0-9]+', 'juejin.cn'),
 'csdn': (r'[A-Za-z0-9_-]+', 'blog.csdn.net'),
 'qichacha': (r'firm/[a-fA-F0-9]{32}\.html', 'www.qcc.com'),
 'tianyancha': (r'company/[0-9]+', 'www.tianyancha.com'),
 'dianping': (r'shop/[A-Za-z0-9]+', 'www.dianping.com'),
}
ENABLED_IDS = frozenset(['zhihu', 'douban', 'v2ex', 'juejin', 'qichacha'])
# Bounded anonymous index smoke test; counts are candidates, never confirmed demand.
_VERIFIED_COUNTS = {'zhihu': 3, 'weibo': 3, 'douban': 2, 'v2ex': 3,
                    'juejin': 3, 'qichacha': 3, 'tianyancha': 2}
for _candidate in CANDIDATES:
    _count = _VERIFIED_COUNTS.get(_candidate['id'], 0)
    _candidate['verification'] = {
        'status': ('live_index_passed' if _candidate['id'] in ENABLED_IDS else 'smoke_passed_not_enabled') if _count else 'not_enabled',
        'candidateCount': _count,
        'evidenceLevel': 'search_snippet',
        'checkedAt': '2026-10-28',
        'demandVerified': False,
    }



def normalize_profile(value, platform):
    meta = next((x for x in CANDIDATES if x['id'] == platform), None)
    if meta is None:
        return None
    try:
        u = urlsplit(value or '')
        if u.scheme != 'https' or u.hostname not in meta['hosts'] or u.username or u.password or u.port not in (None,443):
            return None
        path = u.path.strip('/')
        pattern, host = RULES[platform]
        if not re.fullmatch(pattern, path):
            return None
        if platform == 'csdn' and path.lower() in {'nav','blog','login','user','article','download','community','index','search','rank','categories','premium','vip','ask','edu'}:
            return None
        if platform == 'weibo':
            path = 'u/' + path.removeprefix('u/')
        return 'https://' + host + '/' + path + ('/' if platform in ('douban','v2ex') else '')
    except (ValueError,TypeError):
        return None


def entity_type(url, platform):
    if platform == 'zhihu' and '/org/' in (url or ''):
        return 'organization'
    return next((x['entityType'] for x in CANDIDATES if x['id'] == platform), 'account')


def is_usable_result(row, platform):
    """Reject platform landing/blocked boilerplate posing as a profile result."""
    if not normalize_profile(row.get('href') or row.get('url'), platform):
        return False
    title = str(row.get('title') or '').strip()
    body = str(row.get('body') or row.get('snippet') or '').strip()
    meta = next(x for x in CANDIDATES if x['id'] == platform)
    generic = {meta['name'], meta['name']+'网', '你的生活兴趣社区 - 小红书', '【快手短视频App】快手，拥抱每一种生活'}
    if title in generic or not title:
        return False
    if 'we would like to show you a description' in body.lower():
        return False
    return len(title) <= 180 and len(body) <= 1200
