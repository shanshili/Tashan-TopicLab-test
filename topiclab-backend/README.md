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

## 环境变量

从项目根 `.env` 加载，需配置：

- `DATABASE_URL` - PostgreSQL 连接串
- `JWT_SECRET` - JWT 密钥
- `SMSBAO_USERNAME` / `SMSBAO_PASSWORD` - 短信宝（可选）

## 运行

```bash
cd topiclab-backend
pip install -e .
uvicorn main:app --reload --port 8000
```

Docker 部署时由 `docker-compose` 自动启动，Nginx 将 `/topic-lab/api/auth/` 代理到 topiclab-backend。
