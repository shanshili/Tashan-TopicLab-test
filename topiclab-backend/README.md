# TopicLab Backend (账号服务)

独立的账号/认证服务，与 Resonnet（话题、讨论等）分离。

## 功能

- 发送验证码 `POST /auth/send-code`
- 注册 `POST /auth/register`
- 登录 `POST /auth/login`
- 获取当前用户 `GET /auth/me`
- 记录/更新数字分身 `POST /auth/digital-twins/upsert`
- 查询当前用户分身记录 `GET /auth/digital-twins`
- 查询单条分身详情 `GET /auth/digital-twins/{agent_name}`
- 信源流列表/全文/图片代理 `GET /source-feed/articles` `GET /source-feed/articles/{article_id}` `GET /source-feed/image`
- 信源候选话题预览与执行 `GET /source-feed/automation/preview` `POST /source-feed/automation/run`
- 将原文直接写入 Resonnet 工作区 `POST /source-feed/topics/{topic_id}/workspace-materials`

## 环境变量

从项目根 `.env` 加载，需配置：

- `DATABASE_URL` - PostgreSQL 连接串
- `JWT_SECRET` - JWT 密钥
- `SMSBAO_USERNAME` / `SMSBAO_PASSWORD` - 短信宝（可选）
- `WORKSPACE_BASE` - 与 Resonnet 共享的工作区目录
- `SOURCE_FEED_AUTOMATION_*` - 信源定时抓取、建话题、发讨论的自动化配置
- `RESONNET_BASE_URL` - 可选；TopicLab Backend 访问 Resonnet 的地址。Docker Compose 内默认 `http://backend:8000`，本地分开运行时可设为 `http://127.0.0.1:8000`
- `AI_GENERATION_BASE_URL` / `AI_GENERATION_API_KEY` - 用于信源话题标题与讨论摘要生成，走 OpenAI 兼容接口，模型固定 `qwen3.5-plus`

其中 Resonnet API 地址默认走 Docker 内部服务地址 `http://backend:8000`；不要把 `BACKEND_PORT` 的宿主机映射端口用于容器间访问。若本地不是通过 Compose 互联，请显式设置 `RESONNET_BASE_URL`。

默认自动化策略建议：
- 每 `30` 分钟执行一次
- 每次只选 `1` 篇文章
- 对已经发起过的帖子按 `article_id + 标题/链接签名` 去重，避免信源 6 小时不更新时重复开题

## 运行

```bash
cd topiclab-backend
pip install -e .
uvicorn main:app --reload --port 8000
```

Docker 部署时由 `docker-compose` 自动启动，Nginx 将 `/topic-lab/api/auth/` 代理到 topiclab-backend。
