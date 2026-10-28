# Nomi Discovery API

供销售找客户产品复用的独立 HTTP 服务。与网页、桌面应用、CRM 等产品载体解耦；不需要复制原来的前端。

统一流程：提交需求与平台 → 后台搜索 → 候选筛选与证据整理 → 查询进度与名单 → 导出 CSV。

## 支持范围

18 个公开索引来源：抖音、TikTok、Instagram、YouTube、Facebook、LinkedIn、Reddit、知乎、豆瓣、V2EX、掘金、企查查、X、GitHub、Behance、Yelp、Clutch、Houzz。

此独立版本只开放免登录 `public_search`。结果为可追溯的账号、商家或企业候选，不等于确认购买意向；搜索摘要不冒充本人原话。未开放私信、评论回复、登录或站内评论采集接口。网络、索引覆盖与关键词都会影响结果，不保证每次有结果或足够人数。

## 本机启动

需要 Python 3.11+。在仓库目录执行：

```sh
python -m venv .venv
# 激活虚拟环境后：
python -m pip install -r requirements.txt
python -m uvicorn server.api:app --host 127.0.0.1 --port 8766 --no-proxy-headers
```

接口文档：`http://127.0.0.1:8766/docs`。不依赖原产品页面、Node.js、抖音登录或模型密钥。默认使用保守规则；本地运行数据保存在 `.data`，不属于仓库内容。

## 其他产品调用

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/health` | 服务健康状态 |
| `GET /api/platforms` | 当前支持的平台目录与可用状态 |
| `POST /api/discovery/jobs` | 提交任务，返回202及任务id |
| `GET /api/discovery/jobs` | 任务列表 |
| `GET /api/discovery/jobs/{id}` | 任务进度、平台子任务、名单及证据 |
| `GET /api/discovery/jobs/{id}/export?status=uncertain` | 导出待核实名单CSV |
| `POST /api/discovery/jobs/{id}/cancel` | 取消任务 |

提交示例：

```sh
curl -X POST http://127.0.0.1:8766/api/discovery/jobs \
  -H "Content-Type: application/json" \
  -d '{"request":"寻找杭州的装修商家候选，保留主页与依据","platforms":["douyin","zhihu","qichacha"],"keywords":["杭州 装修"],"limit":10,"accessMode":"anonymous","requestId":"demo-client-0001"}'
```

读取响应的 `id`，每隔数秒查询任务。名单在 `items`，数量在 `counts`，各平台进度在 `children`。`limit` 是跨平台总交付上限。搜索摘要结果通常属于 `uncertain`；默认CSV仅导出 `matched`，因此获取公开索引候选时请明确传入 `status=uncertain`。

省略 `platforms` 时默认原有7个平台；显式传入目录中的标识可选择全部18个。相同 `requestId` 和相同内容重复提交会复用任务；请求内容变更须更换该标识。任务持久化到 SQLite，重启中断任务如实标记，不伪装成完成。

## 接入方式与部署

- 桌面客户端：本机启动此服务，客户端通过HTTP调用。
- 网页或CRM：推荐由产品后端调用此服务，浏览器只请求自己的后端。
- 浏览器直接调用：用 `NOMI_ALLOWED_ORIGINS` 显式配置页面来源，逗号分隔，不使用通配符。
- 远程服务：设置 `NOMI_API_KEY`，调用时添加 `Authorization: Bearer <key>`，并通过HTTPS反向代理部署。未配置密钥仅接受本机访问。
- 数据目录可通过 `NOMI_DATA_DIR` 指定。环境变量请通过系统或部署平台注入；不要提交密钥、Cookie或数据库。

这是有持久任务和本地数据库的常驻服务，适合本机、服务器或容器。不能把它当作纯静态网页上传，也不适合直接放入短时无状态函数。当前是单实例、单租户服务；API密钥不是多租户身份系统。多个产品可共用同一服务，但任务与名单共享；需要客户数据隔离时，每个租户独立部署或先实现租户隔离。SQLite模式请仅运行一个worker。

## 验证

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

测试使用隔离数据与可控适配器，不会把模拟测试当作实时平台可用证明。来源在原产品中已完成真实搜索验收；独立版本的真实测试说明见 `VERIFICATION.md`。

## 来源

从 [Nomi Scout](https://github.com/Mercury-nju/nomi-scout) 提取的客户发现后端；不包含原项目的前端、浏览器资料、客户数据库或凭据。第三方依赖各自遵循其许可证。
