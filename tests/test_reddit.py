"""Reddit anonymous profile discovery does not infer authors from communities."""
import asyncio
import pytest
from pydantic import ValidationError
from server.discovery import PLATFORMS, validate_execution
from server.discovery_jobs import DiscoveryJobRequest
from server.models import Plan
from server.public_search import profile_url, make_candidate, PublicSearchAdapter
from server.planner import assess


@pytest.mark.parametrize('url', [
    'https://www.reddit.com/user/Example_Name/',
    'https://reddit.com/u/Example_Name?utm_source=example',
    'https://old.reddit.com/user/example_name/',
])
def test_reddit_stable_profile_normalization(url):
    assert profile_url(url, 'reddit') == 'https://www.reddit.com/user/example_name/'


@pytest.mark.parametrize('url', [
    'https://www.reddit.com/r/Entrepreneur/',
    'https://www.reddit.com/r/Entrepreneur/comments/abc/post_title/',
    'https://www.reddit.com/user/deleted/',
    'https://www.reddit.com/user/removed/',
    'https://www.reddit.com/user/AutoModerator/',
    'https://www.reddit.com/user/[deleted]/',
    'https://www.reddit.com/user/example/comments/abc/',
    'https://www.reddit.com/login/',
    'https://www.reddit.com.evil.example/user/example/',
    'https://user:password@www.reddit.com/user/example/',
])
def test_reddit_nonidentity_sources_rejected(url):
    assert profile_url(url, 'reddit') is None


def test_reddit_registered_and_unified_default():
    reddit = next(p for p in PLATFORMS if p['id'] == 'reddit')
    assert reddit['capabilities'] == ['public_search']
    assert len(DiscoveryJobRequest(request='Find public designers').platforms) == 7
    plan = Plan(platform='reddit',name='test',target='public designers',sourceType='public_search',keywords=['designer'])
    validate_execution(plan.model_dump())
    validate_execution({'platform':'reddit','sourceType':'public_search','mode':'find'})
    with pytest.raises(ValueError):
        validate_execution({'platform':'reddit','sourceType':'account_comments','mode':'find'})
    with pytest.raises(ValidationError):
        Plan(platform='reddit',name='test',target='test',sourceType='account_comments',sourceUrl='https://www.instagram.com/example/')


def test_reddit_search_snippet_stays_uncertain(tmp_path, monkeypatch):
    import server.public_search as search
    queries = []
    async def fake_search(query, limit, cancelled):
        queries.append(query)
        return {'items':[{'href':'https://www.reddit.com/user/example_user/', 'title':'example_user', 'body':'我是杭州销售，需要获客', '_engine':'yahoo'},
                         {'href':'https://www.reddit.com/r/sales/', 'title':'sales', 'body':'unattributed'}]}
    async def check(*args):
        return 'restricted','原页受限，摘要未核验'
    monkeypatch.setattr(search,'search_process',fake_search)
    monkeypatch.setattr(search,'check_original',check)
    emitted=[]
    async def emit(event): emitted.append(event)
    async def run():
        plan={'platform':'reddit','sourceType':'public_search','keywords':['sales'],'scanLimit':3,'maxWorks':1,'target':'杭州销售需要获客','region':'杭州','signals':'获客'}
        result=await PublicSearchAdapter(tmp_path,'reddit').discover(plan,emit,lambda:False)
        assert len(result)==1
        assert result[0]['profileUrl']=='https://www.reddit.com/user/example_user/'
        assert result[0]['sources'][0]['verifiedStatement'] is False
        assert (await assess(result[0],plan))['status']=='uncertain'
    asyncio.run(run())
    assert queries == ['site:reddit.com/user/ sales']
