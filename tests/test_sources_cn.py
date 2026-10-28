import pytest
from server.sources_cn import normalize_profile,entity_type,CANDIDATES

@pytest.mark.parametrize('platform,url,expected',[
 ('xiaohongshu','https://www.xiaohongshu.com/user/profile/5ab1234567890123456789ab?x=1','https://www.xiaohongshu.com/user/profile/5ab1234567890123456789ab'),
 ('zhihu','https://www.zhihu.com/people/example/','https://www.zhihu.com/people/example'),
 ('zhihu','https://www.zhihu.com/org/example/','https://www.zhihu.com/org/example'),
 ('bilibili','https://space.bilibili.com/1234?x=1','https://space.bilibili.com/1234'),
 ('weibo','https://weibo.com/u/12345678','https://weibo.com/u/12345678'),
 ('kuaishou','https://www.kuaishou.com/profile/example','https://www.kuaishou.com/profile/example'),
 ('douban','https://www.douban.com/people/example/','https://www.douban.com/people/example/'),
 ('v2ex','https://v2ex.com/member/example','https://www.v2ex.com/member/example/'),
 ('juejin','https://juejin.cn/user/12345','https://juejin.cn/user/12345'),
 ('csdn','https://blog.csdn.net/example','https://blog.csdn.net/example'),
 ('qichacha','https://www.qcc.com/firm/'+'a'*32+'.html','https://www.qcc.com/firm/'+'a'*32+'.html'),
 ('tianyancha','https://www.tianyancha.com/company/12345','https://www.tianyancha.com/company/12345'),
 ('dianping','https://www.dianping.com/shop/Abc123','https://www.dianping.com/shop/Abc123'),
])
def test_canonical(platform,url,expected):assert normalize_profile(url,platform)==expected

@pytest.mark.parametrize('platform,url',[
 ('xiaohongshu','https://www.xiaohongshu.com/explore/5ab1234567890123456789ab'),
 ('zhihu','https://www.zhihu.com/question/123/answer/456'),
 ('bilibili','https://www.bilibili.com/video/BV123'),
 ('weibo','https://weibo.com/u/12345/SomePost'),
 ('douban','https://www.douban.com/group/123'),
 ('v2ex','https://www.v2ex.com/t/123'),
 ('juejin','https://juejin.cn/post/123'),
 ('csdn','https://blog.csdn.net/example/article/details/123'),
 ('csdn','https://blog.csdn.net/search'),
 ('qichacha','https://www.qcc.com/web/search?key=test'),
 ('tianyancha','https://www.tianyancha.com/search?key=test'),
 ('dianping','https://www.dianping.com/shop/123/review_all'),
 ('zhihu','https://www.zhihu.com.evil.test/people/example'),
 ('zhihu','https://user:password@www.zhihu.com/people/example'),
 ('zhihu','https://www.zhihu.com:999/people/example'),
 ('zhihu','http://www.zhihu.com/people/example'),
])
def test_reject_ambiguous_or_unsafe(platform,url):assert normalize_profile(url,platform) is None

def test_entity_types():
 assert entity_type('https://www.zhihu.com/org/example','zhihu')=='organization'
 assert entity_type('https://www.qcc.com/firm/example','qichacha')=='organization'
 assert entity_type('https://www.dianping.com/shop/example','dianping')=='business'
 assert len({c['id'] for c in CANDIDATES})==len(CANDIDATES)


def test_weibo_same_user_alias_collapses():
 assert normalize_profile('https://weibo.com/12345678','weibo')==normalize_profile('https://weibo.com/u/12345678','weibo')


def test_platform_boilerplate_is_not_a_prospect():
 from server.sources_cn import is_usable_result
 assert not is_usable_result({'href':'https://www.kuaishou.com/profile/example','title':'快手','body':'快手是一款国民级短视频App'},'kuaishou')
 assert not is_usable_result({'href':'https://www.dianping.com/shop/Example','title':'大众点评网','body':'关于我们 | 商户入驻'},'dianping')
 assert not is_usable_result({'href':'https://www.zhihu.com/people/example','title':'Example','body':'We would like to show you a description here but the site won’t allow us.'},'zhihu')
 assert is_usable_result({'href':'https://www.qcc.com/firm/'+'a'*32+'.html','title':'某装修有限公司 - 企查查','body':'企业信息索引'},'qichacha')
