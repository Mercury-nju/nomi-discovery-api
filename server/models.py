from typing import Literal
from urllib.parse import urlparse
from .discovery import PLATFORM_HOSTS
from pydantic import BaseModel, Field, field_validator, model_validator


class Plan(BaseModel):
    platform: str = 'douyin'
    name: str = Field(min_length=1, max_length=120)
    target: str = Field(min_length=1, max_length=2000)
    region: str = ''
    signals: str = ''
    sourceType: Literal['keyword_comments', 'account_comments', 'live_chat', 'public_search'] = 'keyword_comments'
    keywords: list[str] = Field(default_factory=list, max_length=10)
    workKeywords: list[str] = Field(default_factory=list, max_length=10)
    maxWorks: int = Field(default=10, ge=1, le=50)
    maxComments: int = Field(default=50, ge=1, le=200)
    scanLimit: int = Field(default=100, ge=1, le=500)
    sourceUrl: str = ''
    scheduleMode: Literal['once', 'daily'] = 'once'
    scheduleTime: str = '10:00'
    limit: int = Field(default=10, ge=1, le=100)
    observeSeconds: int = Field(default=60, ge=10, le=1800)
    mode: Literal['find', 'contact'] = 'find'
    channel: Literal['dm', 'live_mention', 'video_comment'] = 'dm'
    authorized: bool = False
    communicationStrategy: str = ''

    @field_validator('platform')
    @classmethod
    def known_platform(cls, value):
        if value not in PLATFORM_HOSTS:
            raise ValueError('平台不存在或尚未通过接入验收')
        return value

    @field_validator('sourceUrl')
    @classmethod
    def valid_url(cls, value):
        if value:
            url = urlparse(value)
            if url.scheme != 'https' or url.hostname not in tuple(h for hosts in PLATFORM_HOSTS.values() for h in hosts) or url.username or url.password or url.port not in (None, 443):
                raise ValueError('来源链接必须是支持平台的 HTTPS 公开链接')
        return value

    @field_validator('scheduleTime')
    @classmethod
    def valid_time(cls, value):
        import re
        if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('时间应为 HH:mm')
        return value

    @model_validator(mode='after')
    def valid_scope(self):
        if self.sourceUrl and urlparse(self.sourceUrl).hostname not in PLATFORM_HOSTS[self.platform]:
            raise ValueError('来源链接与所选平台不一致')
        if self.scanLimit < self.limit:
            raise ValueError('候选扫描上限不能小于希望匹配人数')
        if self.sourceType not in ('keyword_comments', 'public_search') and not self.sourceUrl:
            raise ValueError('请提供作品账号或直播间链接')
        if self.sourceType in ('keyword_comments', 'public_search') and not any(x.strip() for x in self.keywords):
            raise ValueError('请提供搜索关键词')
        if self.mode == 'contact' and not self.authorized:
            raise ValueError('找客并触达需明确授权')
        if self.channel == 'live_mention' and self.sourceType != 'live_chat':
            raise ValueError('直播 @ 仅适用于直播任务')
        if self.channel == 'video_comment' and self.sourceType == 'live_chat':
            raise ValueError('作品评论回复不适用于直播任务')
        return self


class PlanRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)
    knowledge: dict | None = None


class DraftRequest(BaseModel):
    strategy: str = Field(default='', max_length=2000)
    knowledge: dict | None = None
    taskId: str | None = None


class SendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    channel: Literal['dm', 'live_mention', 'video_comment'] = 'dm'
    authorized: bool = False
    taskId: str | None = None


class KnowledgeRequest(BaseModel):
    identity: str = ''
    brand: str = ''
    region: str = ''
    service: str = ''
    advantage: str = ''
    audience: str = ''
    purpose: str = ''
    style: str = ''
    goal: str = ''
    cautions: str = ''
    products: list[dict] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    customerId: str = Field(min_length=1, max_length=200)


class ConversationControl(BaseModel):
    mode: Literal['suggest', 'auto', 'human', 'paused']
    authorized: bool = False


class ConversationSend(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    authorized: bool = False
    requestId: str = Field(min_length=8, max_length=150, pattern=r'^[A-Za-z0-9_-]+$')
    revision: int = Field(ge=0)


class MonitorSettings(BaseModel):
    enabled: bool
    intervalSeconds: int = Field(default=15, ge=5, le=300)


class ConversationResolution(BaseModel):
    resolution: Literal['sent', 'not_sent']
    authorized: bool = False
    note: str = Field(min_length=1, max_length=500)
