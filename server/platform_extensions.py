"""Only independently smoke-tested public-index sources enter the catalog."""
from .sources_cn import CANDIDATES as CN, ENABLED_IDS as CN_ENABLED, normalize_profile as cn_profile, entity_type as cn_entity, is_usable_result as cn_usable
from .sources_global import CANDIDATES as GLOBAL, ENABLED_IDS as GLOBAL_ENABLED, normalize_profile as global_profile, is_usable_result as global_usable

EXTENSIONS = [dict(item) for item in [*CN, *GLOBAL] if item['id'] in (CN_ENABLED | GLOBAL_ENABLED)]
ALL_CANDIDATES = [*CN, *GLOBAL]

def normalize_profile(url, platform):
    if platform in CN_ENABLED:
        return cn_profile(url, platform)
    if platform in GLOBAL_ENABLED:
        return global_profile(url, platform)
    return None

def entity_type(url, platform):
    if platform in CN_ENABLED:
        return cn_entity(url, platform)
    return next((x['entityType'] for x in EXTENSIONS if x['id'] == platform), 'account')

def is_usable_result(row, platform):
    if platform in CN_ENABLED:
        return cn_usable(row, platform)
    if platform in GLOBAL_ENABLED:
        return global_usable(row, platform)
    return False
