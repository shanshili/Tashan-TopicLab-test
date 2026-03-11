# Configuration

## Environment Variables

Config file: `.env` at project root (or `backend/.env`). The backend loads project root `./.env` first when backend is a submodule. Copy from `.env.example` or `backend/.env.example` and edit.

### 1. Claude Agent SDK (Discussion orchestration, expert reply)

```bash
ANTHROPIC_API_KEY=your_key_here
ANTHROPIC_BASE_URL=https://dashscope.aliyuncs.com/apps/anthropic   # optional, DashScope etc.
ANTHROPIC_MODEL=qwen-flash   # optional
```

Used for:
- Multi-round discussion (`run_discussion`)
- @expert reply (`run_expert_reply`)

### 2. AI Generation (Expert/Moderator generation)

```bash
AI_GENERATION_API_KEY=your_key_here
AI_GENERATION_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AI_GENERATION_MODEL=qwen-flash
```

Used for:
- AI-generated expert role
- AI-generated moderator mode

**Note**: Both configs are strictly separate; do not mix them.

### 3. Libraries

All libraries (experts, moderator_modes, mcps, assignable_skills, prompts) are loaded from `backend/libs/`. No scenario preset.

**Docker**: When `LIBS_PATH` points to a custom empty directory (e.g. for persistence), the backend merges from both built-in and the mount. See [backend/docs/config.md](backend/docs/config.md) for details.

### 4. Workspace (optional)

```bash
WORKSPACE_BASE=./workspace
```

Topic workspace root directory.

### 5. 用户认证（topiclab-backend，可选）

```bash
DATABASE_URL=postgresql://user:pass@host:5432/topiclab
PGSSLMODE=disable
JWT_SECRET=your-secret-key-change-in-production
# 短信验证码（可选，不填则开发模式，验证码打印到日志）
SMSBAO_USERNAME=
SMSBAO_PASSWORD=
# Resonnet backend 转发鉴权到账号服务
AUTH_SERVICE_BASE_URL=http://topiclab-backend:8000
```

- **DATABASE_URL**：PostgreSQL 连接串，用于 `users`、`verification_codes` 表。不填则使用内存存储（开发模式）。
- **JWT_SECRET**：JWT 签发密钥，生产环境务必修改。
- **SMSBAO_***：短信宝 API（https://www.smsbao.com/），用于发送验证码。`SMSBAO_PASSWORD` 填登录密码，程序会自动 MD5 后调用。不填则开发模式，验证码显示在页面/打印到日志。
- **AUTH_SERVICE_BASE_URL**：Resonnet backend 校验 Bearer Token 时调用的账号服务地址（默认 `http://topiclab-backend:8000`）。

账号服务运行在独立的 `topiclab-backend` 容器，与 Resonnet（topics、discussion 等）分离。Nginx 将 `/topic-lab/api/auth/` 代理到 topiclab-backend。

### 6. 科研数字分身采集助手（Profile Helper Agent）

```bash
# 单次用户请求内部最多允许的工具/思考循环轮数（默认 40，下限 5）
PROFILE_HELPER_MAX_TOOL_ITERATIONS=40
```

- **PROFILE_HELPER_MAX_TOOL_ITERATIONS**：控制 Profile Helper 内部 agent 循环的最大轮数。适当调大可以减少「达到最大工具调用次数」报错，但也会增加单次请求耗时与 token 消耗。推荐范围 20–60。

### 7. MCP 库 (只读)

MCP 服务器在 `backend/libs/mcps/` 中配置，与技能库结构一致。MCP 库页面 `/mcp` 只读展示，话题讨论时可选择启用的 MCP。仅接受 npm、uvx、remote。参见 [backend/docs/mcp-config.md](backend/docs/mcp-config.md)。

## Rules

1. **Do not mix the two API configs**: `ANTHROPIC_*` for Claude Agent SDK, `AI_GENERATION_*` for OpenAI-compatible API
2. **No fallback**: Missing `AI_GENERATION_API_KEY` does not fall back to `ANTHROPIC_API_KEY`
3. **Different API formats**: `ANTHROPIC_BASE_URL` expects Anthropic-compatible API; `AI_GENERATION_BASE_URL` expects OpenAI-compatible API

## Validation

The app will refuse to start if required variables are unset.

## More

Full Resonnet configuration: [backend/docs/config.md](backend/docs/config.md). **Backend source**: [Resonnet](https://github.com/TashanGKD/Resonnet)
