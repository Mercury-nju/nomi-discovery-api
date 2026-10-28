import asyncio
import pytest
from server import public_search as search


@pytest.mark.parametrize('platform,url,expected', [
    ('linkedin','https://www.linkedin.com/in/example/', 'https://www.linkedin.com/in/example/'),
    ('instagram','https://www.instagram.com/Example/?x=y', 'https://www.instagram.com/example/'),
    ('tiktok','https://www.tiktok.com/@example/video/123', 'https://www.tiktok.com/@example'),
    ('facebook','https://www.facebook.com/profile.php?id=123&x=y', 'https://www.facebook.com/profile.php?id=123'),
    ('facebook','https://www.facebook.com/example/posts/abc', 'https://www.facebook.com/example/'),
    ('youtube','https://www.youtube.com/@example','https://www.youtube.com/@example'),
    ('douyin','https://www.douyin.com/user/example','https://www.douyin.com/user/example'),
])
def test_identity_urls(platform,url,expected):
    assert search.profile_url(url,platform)==expected


@pytest.mark.parametrize('platform,url', [
    ('linkedin','https://www.linkedin.com/posts/some-post'),
    ('linkedin','https://www.linkedin.com/company/example'),
    ('instagram','https://www.instagram.com/p/unknown-author/'),
    ('instagram','https://www.instagram.com/accounts/'),
    ('facebook','https://www.facebook.com/groups/example'),
    ('facebook','https://www.facebook.com/profile.php'),
    ('youtube','https://www.youtube.com/watch?v=unknown'),
    ('tiktok','https://www.tiktok.com/search?q=example'),
    ('tiktok','https://www.tiktok.com.evil.example/@name'),
    ('instagram','https://user:pass@www.instagram.com/name/'),
    ('instagram','http://www.instagram.com/name/'),
    ('instagram','https://www.instagram.com:8888/name/'),
])
def test_no_ambiguous_or_unsafe_identity(platform,url):
    assert search.profile_url(url,platform) is None


def test_snippets_never_become_verified_bio_or_statement():
    row=search.make_candidate({'href':'https://www.linkedin.com/in/example/','title':'A professional', 'body':'I need a builder'},'linkedin','site:linkedin.com/in builder','bing')
    assert row['profileText']==''
    assert row['sources'][0]['type']=='search_snippet'
    assert row['sources'][0]['evidenceLevel']=='search_snippet'
    assert row['sources'][0]['verifiedStatement'] is False
    assert row['sources'][0]['searchQuery']=='site:linkedin.com/in builder'


def test_discovery_deduplicates_caps_and_preserves_uncertainty(monkeypatch,tmp_path):
    async def fake_search(*args):
        return {'items':[{'href':'https://www.instagram.com/person/','title':'Person','body':'London designer'}, {'href':'https://www.instagram.com/person/?tracking=yes','title':'Person','body':'same'}, {'href':'https://www.instagram.com/second/','title':'Second','body':'different'}]}
    async def check(*args):return 'reachable_unverified','Page response is not intent verification'
    monkeypatch.setattr(search,'search_process',fake_search)
    monkeypatch.setattr(search,'check_original',check)
    events=[]
    async def emit(event):events.append(event)
    rows=asyncio.run(search.PublicSearchAdapter(tmp_path,'instagram').discover({'sourceType':'public_search','keywords':['designer'],'scanLimit':1},emit,lambda:False))
    assert len(rows)==1
    assert rows[0]['sources'][0]['originalPageStatus']=='reachable_unverified'
    assert rows[0]['sources'][0]['verifiedStatement'] is False
    assert sum(e.get('type')=='candidate' for e in events)==1


def test_empty_result_is_not_success(monkeypatch,tmp_path):
    async def fake_search(*args):return {'items':[]}
    async def emit(event):pass
    monkeypatch.setattr(search,'search_process',fake_search)
    with pytest.raises(ValueError,match='未返回'):
        asyncio.run(search.PublicSearchAdapter(tmp_path,'linkedin').discover({'sourceType':'public_search','keywords':['builder']},emit,lambda:False))


def test_cancel_before_search_does_not_collect(monkeypatch,tmp_path):
    async def bad_search(*args):raise AssertionError('should not search')
    async def emit(event):pass
    monkeypatch.setattr(search,'search_process',bad_search)
    assert asyncio.run(search.PublicSearchAdapter(tmp_path,'linkedin').discover({'sourceType':'public_search','keywords':['builder']},emit,lambda:True))==[]


def test_nested_yahoo_results_never_mix_people():
    markup='''<div class="relsrch"><div class="compTitle"><a href="https://www.linkedin.com/in/alice/"><h3><span class="fz-20">Alice | LinkedIn</span></h3></a></div><div class="compText">Alice designs homes</div><li><div class="relsrch"><div class="compTitle"><a href="https://www.linkedin.com/in/bob/"><h3><span class="fz-20">Bob | LinkedIn</span></h3></a></div><div class="compText">Bob sells cars</div></div></li></div>'''
    rows=search.yahoo_single_results(markup)
    assert len(rows)==2
    assert rows[0]['title']=='Alice | LinkedIn'
    assert rows[0]['body']=='Alice designs homes'
    assert rows[1]['title']=='Bob | LinkedIn'
    assert rows[1]['body']=='Bob sells cars'
    assert rows[0]['href'].endswith('/alice/')


def test_aggregated_title_rejected_not_truncated():
    assert search.make_candidate({'href':'https://www.instagram.com/example/', 'title':'Alice | InstagramBob | Instagram','body':'untrusted aggregate'},'instagram','q','yahoo') is None


def test_title_filter(monkeypatch,tmp_path):
    async def fake_search(*args):return {'items':[{'href':'https://www.instagram.com/person/','title':'Architect','body':'original index'}]}
    async def emit(event):pass
    monkeypatch.setattr(search,'search_process',fake_search)
    with pytest.raises(ValueError,match='未返回'):
        asyncio.run(search.PublicSearchAdapter(tmp_path,'instagram').discover({'sourceType':'public_search','keywords':['design'],'workKeywords':['plumber']},emit,lambda:False))
