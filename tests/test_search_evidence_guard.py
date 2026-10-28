import asyncio
import pytest
from server import planner


def plan(**values):
    return {'sourceType': 'public_search', 'target': '杭州销售想获客', 'region': '杭州', 'signals': '获客', **values}


@pytest.mark.parametrize('source', [
    {'type': 'search_snippet', 'evidenceLevel': 'search_snippet', 'verifiedStatement': False},
    {'type': 'public_profile', 'evidenceLevel': 'public_page', 'verifiedStatement': False},
    {'type': 'public_profile', 'evidenceLevel': 'public_page', 'verifiedStatement': True},
    {'type': 'comment', 'evidenceLevel': 'search_snippet', 'verifiedStatement': True},
    {'type': 'comment'},
    {'type': 'comment', 'verifiedStatement': 'true'},
])
def test_metadata_cannot_become_demand_even_if_every_keyword_matches(source, monkeypatch):
    async def forged_model(*args):
        pytest.fail('Unverified search evidence must not be offered to the model as a user statement')
    monkeypatch.setattr(planner, 'llm_json', forged_model)
    source = {**source, 'url': 'https://www.linkedin.com/in/example', 'text': '我是杭州销售，我需要获客'}
    result = asyncio.run(planner.assess({'profileText': '杭州销售想获客', 'sources': [source]}, plan()))
    assert result['status'] == 'uncertain'
    assert any('已核验原始发言' in item for item in result['missing'])
    assert not any('发言出现需求信号' in item for item in result['reasons'])


def test_metadata_negative_is_not_attributed_to_person(monkeypatch):
    monkeypatch.setenv('NOMI_LLM_API_KEY', '')
    result = asyncio.run(planner.assess({'sources': [{'type': 'search_snippet', 'text': '杭州销售不需要获客'}]}, plan()))
    assert result['status'] == 'uncertain'


def test_profile_only_never_confirms_purchase_intent(monkeypatch):
    monkeypatch.setenv('NOMI_LLM_API_KEY', '')
    result = asyncio.run(planner.assess({'profileText': '杭州销售，需要获客', 'sources': []}, plan()))
    assert result['status'] == 'uncertain'
    assert result['missing']


def test_explicitly_verified_statement_with_source_keeps_original_rules(monkeypatch):
    monkeypatch.setenv('NOMI_LLM_API_KEY', '')
    customer = {'sources': [{'type': 'public_statement', 'evidenceLevel': 'public_page',
                            'verifiedStatement': True, 'url': 'https://www.linkedin.com/posts/example',
                            'text': '我是杭州销售，想获客'}]}
    assert asyncio.run(planner.assess(customer, plan()))['status'] == 'matched'
    customer['sources'][0].pop('url')
    assert asyncio.run(planner.assess(customer, plan()))['status'] == 'uncertain'


def test_legacy_douyin_comment_unchanged(monkeypatch):
    monkeypatch.setenv('NOMI_LLM_API_KEY', '')
    result = asyncio.run(planner.assess({'sources': [{'text': '我是杭州销售，想获客'}]}, plan(sourceType='keyword_comments')))
    assert result['status'] == 'matched'


def test_mixed_sources_never_pass_search_summary_to_model(monkeypatch):
    seen = []
    async def model(instruction, data):
        seen.append(data)
        return {'status': 'uncertain', 'reasons': [], 'missing': ['没有本人需求']}
    monkeypatch.setattr(planner, 'llm_json', model)
    customer = {'sources': [
        {'type': 'search_snippet', 'text': '我是杭州销售，我需要获客'},
        {'type': 'public_statement', 'verifiedStatement': True, 'url': 'https://www.linkedin.com/posts/example', 'text': '谢谢分享'},
    ]}
    result = asyncio.run(planner.assess(customer, plan()))
    assert result['status'] == 'uncertain'
    assert seen and seen[0]['statements'] == '谢谢分享'


def test_search_metadata_guard_applies_even_to_legacy_task(monkeypatch):
    monkeypatch.setenv('NOMI_LLM_API_KEY', '')
    customer = {'sources': [{'type': 'search_snippet', 'text': '我是杭州销售，想获客'}]}
    assert asyncio.run(planner.assess(customer, plan(sourceType='keyword_comments')))['status'] == 'uncertain'
