"""Stable public-index identity URLs; no API or inferred real-world identity."""
import pytest
from server.sources_global import normalize_profile, CANDIDATES, ENABLED_IDS

@pytest.mark.parametrize('platform,url,expected', [
 ('x','https://twitter.com/Topology_London/status/123?x=1','https://x.com/topology_london'),
 ('github','https://github.com/LondonAppDev/?tab=repositories','https://github.com/londonappdev'),
 ('behance','https://www.behance.net/dawidwoo87e8dc','https://www.behance.net/dawidwoo87e8dc'),
 ('yelp','https://www.yelp.com/biz/lc-renovation-london?sort_by=date_desc','https://www.yelp.com/biz/lc-renovation-london'),
 ('clutch','https://clutch.co/profile/magora','https://clutch.co/profile/magora'),
 ('houzz','https://www.houzz.com/pro/info41809','https://www.houzz.com/pro/info41809'),
 ('hackernews','https://news.ycombinator.com/user?id=pg','https://news.ycombinator.com/user?id=pg'),
 ('bluesky','https://bsky.app/profile/person.bsky.social','https://bsky.app/profile/person.bsky.social'),
])
def test_stable_identity(platform,url,expected):
 assert normalize_profile(url,platform)==expected

@pytest.mark.parametrize('platform,url', [
 ('github','https://github.com/example/repository'),
 ('github','https://github.com/topics'),
 ('github','https://github.com/login'),
 ('x','https://x.com/search?q=designer'),
 ('x','https://x.com/i/status/123'),
 ('yelp','https://www.yelp.com/search?find_desc=builder'),
 ('clutch','https://clutch.co/profile'),
 ('houzz','https://www.houzz.com/professionals'),
 ('hackernews','https://news.ycombinator.com/item?id=123'),
 ('github','https://github.com.evil.example/user'),
 ('github','http://github.com/user'),
 ('github','https://name:secret@github.com/user'),
 ('github','https://github.com:444/user'),
 ('googlemaps','https://www.google.com/maps/search/builder'),
])
def test_nonidentities_rejected(platform,url):
 assert normalize_profile(url,platform) is None


def test_enable_only_evaluated_sources():
 assert ENABLED_IDS == frozenset(p['id'] for p in CANDIDATES if p['enabled'])
 assert {'x','github','behance','yelp','clutch','houzz'} == ENABLED_IDS
 assert all(p['verification']=='public_index_candidate_found' for p in CANDIDATES if p['enabled'])
 assert 'googlemaps' not in ENABLED_IDS


@pytest.mark.parametrize('title', ['Log in to X', 'Sign up for GitHub', 'GitHub', 'Access denied', 'Explore', ''])
def test_generic_index_walls_rejected(title):
 from server.sources_global import is_usable_result
 assert not is_usable_result({'href':'https://github.com/example','title':title,'body':'generic'},'github')


def test_named_candidate_not_automatically_verified():
 from server.sources_global import is_usable_result
 assert is_usable_result({'href':'https://clutch.co/profile/magora','title':'Magora Reviews (75), Pricing, Services & Verified Ratings','body':'Software development company'},'clutch')
 assert not is_usable_result({'href':'https://github.com/example/repo','title':'Useful named repository'},'github')
