"""Evidence-based list delivery, independent from outreach capabilities."""
import csv
import io
import os

PLATFORM_HOSTS = {
 'douyin': ('douyin.com','www.douyin.com','live.douyin.com'),
 'youtube': ('youtube.com','www.youtube.com','m.youtube.com','youtu.be'),
 'tiktok': ('tiktok.com','www.tiktok.com'), 'instagram': ('instagram.com','www.instagram.com'),
 'facebook': ('facebook.com','www.facebook.com','m.facebook.com','mbasic.facebook.com'),
 'linkedin': ('linkedin.com','www.linkedin.com'),
 'reddit': ('reddit.com','www.reddit.com','old.reddit.com'),
}
PLATFORMS = [
 {'id':key,'name':name,'status':status,'provider':provider,'capabilities':caps,'reason':reason}
 for key,name,status,provider,caps,reason in [
 ('douyin','抖音','ready','本地浏览器',['keyword_comments','account_comments','live_chat'],'已接入公开页面采集'),
 ('youtube','YouTube','available','yt-dlp',['keyword_comments','account_comments'],'开源采集器已接入；真实网络结果需核验'),
 ('tiktok','TikTok','available','TikTok-Api',['account_comments'],'指定公开账号或作品评论；不支持关键词作品搜索'),
 ('instagram','Instagram','available','Instaloader',['account_comments'],'指定公开账号或作品评论；需本机登录会话'),
 ('facebook','Facebook','available','facebook-scraper',['account_comments'],'实验性公开页面评论采集；上游维护较弱，待实测'),
 ('linkedin','LinkedIn','blocked','待验证',[],'候选开源工具缺少可靠的评论者发现链路，尚不能执行找客户'),
 ('reddit','Reddit','available','公开索引',[],'免登录发现公开 Reddit 用户主页；尚未接入平台内帖子或评论采集'),
 ]
]


for _platform in PLATFORMS:
    _platform['capabilities'] = ['public_search', *_platform['capabilities']]
    _platform['status'] = 'ready' if _platform['id'] == 'douyin' else 'available'
    _platform['provider'] = '公开网页搜索 / ' + _platform['provider']
    _platform['reason'] = '免登录发现公开主页；搜索摘要与已核验原文分开展示。' + (f"{_platform['name']} 目前仅开放公开网页路径。" if _platform['id'] in ('linkedin', 'reddit') else '直接评论路径仍受平台访问条件限制。')


from .platform_extensions import EXTENSIONS
for _extension in EXTENSIONS:
    PLATFORM_HOSTS[_extension['id']] = tuple(_extension['hosts'])
    PLATFORMS.append({**_extension, 'status':'available', 'capabilities':['public_search'],
                      'provider':'公开网页搜索', 'reason': '已通过公开索引候选发现实测；仍需核验原页与需求。'})
for _platform in PLATFORMS:
    _platform.setdefault('hosts', list(PLATFORM_HOSTS[_platform['id']]))
    _platform.setdefault('entityType', 'account')


# This standalone package implements only anonymous public index discovery.
for _platform in PLATFORMS:
    _platform.update(capabilities=['public_search'], provider='Public search index', status='available',
                     reason='Anonymous indexed candidates; identity and demand remain unverified.')



def discovery_only():
    return True


def validate_execution(plan):
    platform = next((p for p in PLATFORMS if p['id'] == plan.get('platform', 'douyin')), None)
    if not platform or platform['status'] == 'blocked':
        raise ValueError('该平台尚无可用的客户发现链路。')
    if plan.get('sourceType', 'keyword_comments') not in platform['capabilities']:
        raise ValueError('该平台不支持此发现路径。')
    if platform['id'] != 'douyin' and plan.get('mode', 'find') != 'find':
        raise ValueError('海外平台仅支持发现，不支持触达。')
    if discovery_only() and (plan.get('mode') != 'find' or plan.get('authorized')):
        raise ValueError('此产品仅提供客户发现与名单交付，不执行私信、评论回复或对话承接。')


def result_list(database, task_id=None, status=None):
    tasks = {t['id']: t for t in database.all('tasks')}
    if task_id and task_id not in tasks:
        raise ValueError('任务不存在')
    entries = []
    for customer in database.all('customers'):
        scopes = [task_id] if task_id else customer.get('taskIds', [])
        for scope in scopes:
            if scope not in customer.get('taskIds', []) or scope not in tasks:
                continue
            match = customer.get('matches', {}).get(scope, {'status': 'uncertain', 'reasons': [], 'missing': ['该任务尚未形成判断']})
            if status and match.get('status') != status:
                continue
            sources = [s for s in customer.get('sources', []) if s.get('taskId') == scope]
            entries.append({'id': customer['id'], 'taskId': scope, 'taskName': tasks[scope]['plan']['name'],
                            'platform': tasks[scope]['plan'].get('platform', 'douyin'),
                            'nickname': customer.get('nickname', ''), 'profileUrl': customer.get('profileUrl', ''),
                            'profileText': customer.get('profileText', ''), 'entityType': customer.get('entityType', 'account'), 'match': match,
                            'discoveredAt': customer.get('discoveredAt'),
                            'sources': [{k: s.get(k) for k in ('id', 'type', 'title', 'url', 'text', 'discoveredAt', 'publishedAt', 'postedAt', 'evidencePath', 'evidenceLevel', 'verifiedStatement', 'searchQuery', 'searchUrl', 'verificationReason', 'originalAccessible', 'originalPageStatus', 'searchProvider')} for s in sources]})
    return {'items': entries, 'counts': {s: sum(e['match'].get('status') == s for e in entries) for s in ('matched', 'uncertain', 'excluded')},
            'total': len(entries), 'scope': 'task-person', 'currentIntentVerified': False}


def csv_text(result):
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['任务', '平台', '用户', '主页', '判断状态', '入选理由', '待核实项', '来源内容（原文或搜索摘要）', '来源链接', '采集时间', '证据类型', '搜索词', '原页核验说明', '主体类型'])
    def safe(value):
        value = str(value or '')
        return "'" + value if value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) or value.startswith(('\t', '\r', '\n')) else value
    for e in result['items']:
        writer.writerow([safe(v) for v in [e['taskName'], e['platform'], e['nickname'], e['profileUrl'], e['match'].get('status'),
                         '；'.join(e['match'].get('reasons', [])), '；'.join(e['match'].get('missing', [])),
                         '\n'.join(s.get('text') or '' for s in e['sources']), '\n'.join(s.get('url') or '' for s in e['sources']), e['discoveredAt'], '\n'.join(s.get('evidenceLevel') or s.get('type') or '' for s in e['sources']), '\n'.join(s.get('searchQuery') or '' for s in e['sources']), '\n'.join(s.get('verificationReason') or '' for s in e['sources']), e.get('entityType', 'account')]])
    return '\ufeff' + output.getvalue()
