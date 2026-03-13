"""Automate source-feed topic creation via TopicLab backend -> Resonnet API."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx

logger = logging.getLogger(__name__)

DEFAULT_FETCH_LIMIT = 20
DEFAULT_SELECT_COUNT = 1
DEFAULT_DISCUSSION_MAX_TURNS = 6000
DEFAULT_DISCUSSION_BUDGET_USD = 3.0
DEFAULT_DISCUSSION_NUM_ROUNDS = 5
TOPIC_GENERATION_MODEL = "qwen3.5-plus"

POSITIVE_KEYWORDS = {
    "agent": 6,
    "ai": 3,
    "安全": 5,
    "具身": 6,
    "仿真": 5,
    "模型": 4,
    "算力": 5,
    "芯片": 4,
    "研究": 4,
    "科学": 4,
    "anthropic": 4,
    "claude": 4,
    "英伟达": 4,
    "google": 4,
    "谷歌": 4,
    "融资": 2,
    "开源": 4,
    "自动化": 4,
    "办公": 3,
}

NEGATIVE_KEYWORDS = {
    "大会": 8,
    "直播": 8,
    "观众票": 10,
    "扫码": 6,
    "报名": 6,
    "欢迎进群": 10,
    "阅读原文": 4,
    "今晚": 4,
    "扫地机": 7,
    "冰箱": 7,
    "发布会": 4,
}


@dataclass
class SourceArticle:
    id: int
    title: str
    source_feed_name: str
    source_type: str
    url: str
    pic_url: str | None
    description: str
    publish_time: str
    created_at: str
    content_md: str = ""
    content_source: str = ""
    md_path: str = ""
    run_dir: str = ""


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def get_information_collection_base_url() -> str:
    return os.getenv("INFORMATION_COLLECTION_BASE_URL", "http://ic.nexus.tashan.ac.cn").rstrip("/")


def get_resonnet_base_url() -> str:
    explicit = os.getenv("RESONNET_BASE_URL", "").strip().rstrip("/")
    if explicit:
        return explicit
    # Use the backend container's internal port by default. BACKEND_PORT is the
    # host-published port in docker-compose and is not valid for service-to-service
    # traffic inside the Docker network when it differs from 8000.
    return "http://backend:8000"


def get_workspace_base() -> Path:
    explicit = os.getenv("WORKSPACE_BASE")
    if explicit:
        return Path(explicit).expanduser().resolve()
    return (Path(__file__).resolve().parents[3] / "workspace").resolve()


def get_pipeline_state_file() -> Path:
    return get_workspace_base() / "topiclab" / "source_feed_pipeline" / "state.json"


def get_materials_dir(topic_id: str) -> Path:
    return get_workspace_base() / "topics" / topic_id / "shared" / "source_feed"


def source_feed_automation_enabled() -> bool:
    return _env_flag("SOURCE_FEED_AUTOMATION_ENABLED", True)


def source_feed_automation_interval_seconds() -> int:
    return max(300, int(os.getenv("SOURCE_FEED_AUTOMATION_INTERVAL_SECONDS", "1800")))


def _normalize_pic_url(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    raw = url.strip()
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme == "http":
        return urlunsplit(("https", parts.netloc, parts.path, parts.query, parts.fragment))
    return raw


def _normalize_article(article: dict[str, Any]) -> SourceArticle:
    return SourceArticle(
        id=int(article.get("id", 0)),
        title=str(article.get("title", "")),
        source_feed_name=str(article.get("source_feed_name", "")),
        source_type=str(article.get("source_type", "")),
        url=str(article.get("url", "")),
        pic_url=_normalize_pic_url(article.get("pic_url")),
        description=str(article.get("description", "")),
        publish_time=str(article.get("publish_time", "")),
        created_at=str(article.get("created_at", "")),
        content_md=str(article.get("content_md", "")),
        content_source=str(article.get("content_source", "")),
        md_path=str(article.get("md_path", "")),
        run_dir=str(article.get("run_dir", "")),
    )


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value).strip("-").lower()
    return slug[:48] or "article"


def _trim(text: str, limit: int) -> str:
    raw = (text or "").strip()
    return raw if len(raw) <= limit else f"{raw[:limit].rstrip()}..."


def _material_relpath(topic_id: str, file_path: Path) -> str:
    base = get_workspace_base() / "topics" / topic_id
    return str(file_path.relative_to(base))


def _validate_topic_workspace(topic_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", topic_id):
        raise ValueError("Invalid topic_id")
    topic_root = get_workspace_base() / "topics" / topic_id
    if not topic_root.exists():
        raise FileNotFoundError(f"Topic workspace does not exist: {topic_id}")
    return topic_root


def _load_state() -> dict[str, Any]:
    path = get_pipeline_state_file()
    if not path.exists():
        return {
            "processed_article_ids": [],
            "processed_signatures": [],
            "topics_by_article_id": {},
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError("invalid state payload")
        state.setdefault("processed_article_ids", [])
        state.setdefault("processed_signatures", [])
        state.setdefault("topics_by_article_id", {})
        return state
    except Exception as exc:
        logger.warning("Failed to load source-feed pipeline state: %s", exc)
        return {
            "processed_article_ids": [],
            "processed_signatures": [],
            "topics_by_article_id": {},
        }


def _save_state(state: dict[str, Any]) -> None:
    path = get_pipeline_state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _article_signature(article: SourceArticle) -> str:
    normalized_title = re.sub(r"\s+", " ", article.title).strip().lower()
    normalized_url = article.url.strip().lower()
    return f"{article.source_feed_name.strip().lower()}|{normalized_title}|{normalized_url}"


def _score_article(article: SourceArticle) -> int:
    haystack = f"{article.title} {article.description} {article.content_md[:2000]}".lower()
    score = 0
    for keyword, weight in POSITIVE_KEYWORDS.items():
        if keyword in haystack:
            score += weight
    for keyword, penalty in NEGATIVE_KEYWORDS.items():
        if keyword.lower() in haystack:
            score -= penalty
    if len(article.content_md) >= 1500:
        score += 2
    if article.description:
        score += 1
    if article.source_feed_name in {"极客公园", "DeepTech深科技", "新智元", "深度学习与NLP", "智猩猩AI"}:
        score += 1
    return score


async def _ai_generation_structured_generation(article: SourceArticle) -> dict[str, Any] | None:
    base_url = os.getenv("AI_GENERATION_BASE_URL", "").strip().rstrip("/")
    api_key = os.getenv("AI_GENERATION_API_KEY", "").strip()
    if not base_url or not api_key:
        return None

    prompt = f"""
请根据以下文章，生成一个适合 TopicLab 发起多专家讨论的话题标题和结构化摘要。

要求：
1. 输出 JSON，不要输出任何额外解释。
2. 字段必须包含：
   - topic_title: 30字以内，偏讨论题而不是新闻标题
   - discussion_summary_markdown: Markdown，包含四个二级标题：
     ## 背景
     ## 核心议题
     ## 为什么值得讨论
     ## 建议讨论问题
3. 语言使用中文。
4. 不要照抄原文标题，要提炼成更适合讨论的话题。
5. 建议讨论问题写 3 条编号问题。

文章标题：{article.title}
文章来源：{article.source_feed_name}
发布时间：{article.publish_time}
原文链接：{article.url}
文章摘要：{article.description}

文章全文：
{_trim(article.content_md, 12000)}
""".strip()

    payload = {
        "model": TOPIC_GENERATION_MODEL,
        "max_tokens": 1200,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": "你是 TopicLab 的策划编辑，擅长把新闻与长文提炼成适合多专家讨论的话题。"},
            {"role": "user", "content": prompt},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "content-type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.warning("AI generation failed for article %s: %s", article.id, exc)
        return None

    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    text = message.get("content", "") if isinstance(message, dict) else ""
    if not text:
        return None

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _fallback_topic_bundle(article: SourceArticle) -> dict[str, Any]:
    base_title = article.title.replace("！", "").replace("？", "")
    topic_title = f"围绕《{_trim(base_title, 28)}》的讨论"
    summary = (
        "## 背景\n"
        f"这篇文章来自 {article.source_feed_name}，发布时间为 {article.publish_time}。"
        f"它围绕“{_trim(article.title, 36)}”展开，原文摘要是：{_trim(article.description or article.title, 120)}\n\n"
        "## 核心议题\n"
        "文章触及了技术路线、产业走向或组织决策中的关键判断，不只适合作为资讯阅读，更适合拆成多个视角展开讨论。\n\n"
        "## 为什么值得讨论\n"
        "这类内容通常同时涉及技术可行性、商业化节奏、平台格局或风险边界，适合让不同专家从产业、产品、研究和治理角度交叉讨论。\n\n"
        "## 建议讨论问题\n"
        "1. 这篇文章真正反映的结构性变化是什么？\n"
        "2. 其中哪些判断是事实，哪些更像叙事或营销包装？\n"
        "3. 如果把它转成行动议题，团队最值得追问的下一步是什么？"
    )
    return {
        "topic_title": topic_title,
        "discussion_summary_markdown": summary,
    }


async def generate_topic_bundle(article: SourceArticle) -> dict[str, Any]:
    generated = await _ai_generation_structured_generation(article)
    if generated:
        topic_title = str(generated.get("topic_title") or "").strip()
        discussion_summary = str(generated.get("discussion_summary_markdown") or "").strip()
        if topic_title and discussion_summary:
            return {
                "topic_title": topic_title[:200],
                "discussion_summary_markdown": discussion_summary,
            }
    return _fallback_topic_bundle(article)


async def fetch_source_feed_articles(limit: int = DEFAULT_FETCH_LIMIT, offset: int = 0) -> list[SourceArticle]:
    upstream_url = f"{get_information_collection_base_url()}/api/v1/articles"
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(upstream_url, params={"limit": limit, "offset": offset})
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data", {})
    raw_list = data.get("list", [])
    return [_normalize_article(item) for item in raw_list if isinstance(item, dict)]


async def fetch_source_feed_article_detail(article_id: int) -> SourceArticle:
    upstream_url = f"{get_information_collection_base_url()}/api/v1/articles/{article_id}"
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(upstream_url)
        response.raise_for_status()
    payload = response.json()
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError(f"Unexpected article detail payload for article_id={article_id}")
    return _normalize_article(data)


async def select_candidate_articles(limit: int = DEFAULT_FETCH_LIMIT, select_count: int = DEFAULT_SELECT_COUNT) -> list[SourceArticle]:
    articles = await fetch_source_feed_articles(limit=limit)
    detailed: list[SourceArticle] = []
    for item in articles:
        try:
            detailed.append(await fetch_source_feed_article_detail(item.id))
        except Exception as exc:
            logger.warning("Skip article %s due to detail fetch error: %s", item.id, exc)
    detailed.sort(key=_score_article, reverse=True)
    return detailed[:select_count]


def _build_topic_body(article: SourceArticle, generated: dict[str, Any], material_paths: list[str]) -> str:
    material_lines = "\n".join(f"- `{path}`" for path in material_paths)
    return (
        f"{generated['discussion_summary_markdown']}\n\n"
        "## 原文信息\n"
        f"- 标题：{article.title}\n"
        f"- 来源：{article.source_feed_name}\n"
        f"- 发布时间：{article.publish_time}\n"
        f"- 原文链接：{article.url}\n\n"
        "## 工作区材料\n"
        "以下原文已同步到工作区，讨论请优先基于本地材料，不必再爬原文链接：\n"
        f"{material_lines}\n"
    )


async def hydrate_topic_workspace(topic_id: str, article_ids: list[int]) -> dict[str, Any]:
    _validate_topic_workspace(topic_id)
    materials_dir = get_materials_dir(topic_id)
    materials_dir.mkdir(parents=True, exist_ok=True)

    articles: list[SourceArticle] = []
    written_files: list[str] = []
    for article_id in article_ids:
        article = await fetch_source_feed_article_detail(article_id)
        articles.append(article)
        filename = f"article_{article.id}_{_slugify(article.title)}.md"
        file_path = materials_dir / filename
        content = (
            f"# {article.title}\n\n"
            f"- article_id: {article.id}\n"
            f"- source_feed_name: {article.source_feed_name}\n"
            f"- publish_time: {article.publish_time}\n"
            f"- url: {article.url}\n\n"
            "## content_md\n\n"
            f"{article.content_md.strip()}\n"
        )
        file_path.write_text(content, encoding="utf-8")
        written_files.append(_material_relpath(topic_id, file_path))

    manifest_path = materials_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "topic_id": topic_id,
                "articles": [asdict(article) for article in articles],
                "written_files": written_files,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    readme_path = materials_dir / "README.md"
    readme_path.write_text(
        "# Source Feed Materials\n\n"
        "本目录由 TopicLab 后端自动写入，供 Resonnet 讨论时直接读取本地全文。\n\n"
        + "\n".join(f"- `{path}`" for path in written_files),
        encoding="utf-8",
    )
    manifest_rel = _material_relpath(topic_id, manifest_path)
    readme_rel = _material_relpath(topic_id, readme_path)
    return {
        "topic_id": topic_id,
        "article_ids": article_ids,
        "written_files": [readme_rel, manifest_rel, *written_files],
        "manifest_path": manifest_rel,
        "readme_path": readme_rel,
    }


async def _resonnet_create_topic(client: httpx.AsyncClient, title: str, body: str) -> dict[str, Any]:
    response = await client.post(f"{get_resonnet_base_url()}/topics", json={"title": title, "body": body})
    response.raise_for_status()
    return response.json()


async def _resonnet_patch_topic_body(client: httpx.AsyncClient, topic_id: str, body: str) -> dict[str, Any]:
    response = await client.patch(f"{get_resonnet_base_url()}/topics/{topic_id}", json={"body": body})
    response.raise_for_status()
    return response.json()


async def _resonnet_start_discussion(client: httpx.AsyncClient, topic_id: str) -> dict[str, Any]:
    payload = {
        "num_rounds": DEFAULT_DISCUSSION_NUM_ROUNDS,
        "max_turns": int(os.getenv("SOURCE_FEED_AUTOMATION_DISCUSSION_MAX_TURNS", str(DEFAULT_DISCUSSION_MAX_TURNS))),
        "max_budget_usd": DEFAULT_DISCUSSION_BUDGET_USD,
    }
    response = await client.post(f"{get_resonnet_base_url()}/topics/{topic_id}/discussion", json=payload)
    response.raise_for_status()
    return response.json()


async def create_topic_from_article(article: SourceArticle, start_discussion: bool = True) -> dict[str, Any]:
    generated = await generate_topic_bundle(article)

    async with httpx.AsyncClient(timeout=30.0) as client:
        created = await _resonnet_create_topic(client, generated["topic_title"], generated["discussion_summary_markdown"])
        topic_id = created["id"]
        material_info = await hydrate_topic_workspace(topic_id, [article.id])
        body = _build_topic_body(article, generated, material_info["written_files"])
        patched = await _resonnet_patch_topic_body(client, topic_id, body)

        discussion = None
        if start_discussion:
            discussion = await _resonnet_start_discussion(client, topic_id)

    return {
        "topic_id": topic_id,
        "article_id": article.id,
        "article_title": article.title,
        "topic_title": patched["title"],
        "material_paths": material_info["written_files"],
        "discussion_started": bool(discussion),
        "discussion_status": discussion["status"] if isinstance(discussion, dict) and discussion.get("status") else None,
    }


async def preview_source_feed_pipeline(limit: int = DEFAULT_FETCH_LIMIT, select_count: int = DEFAULT_SELECT_COUNT) -> list[dict[str, Any]]:
    selected = await select_candidate_articles(limit=limit, select_count=select_count)
    results: list[dict[str, Any]] = []
    for article in selected:
        generated = await generate_topic_bundle(article)
        results.append(
            {
                "article_id": article.id,
                "article_title": article.title,
                "source_feed_name": article.source_feed_name,
                "publish_time": article.publish_time,
                "url": article.url,
                "score": _score_article(article),
                "topic_title": generated["topic_title"],
                "discussion_summary_markdown": generated["discussion_summary_markdown"],
            }
        )
    return results


async def run_source_feed_pipeline(
    limit: int = DEFAULT_FETCH_LIMIT,
    select_count: int = DEFAULT_SELECT_COUNT,
    *,
    start_discussion: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    state = _load_state()
    processed = {int(item) for item in state.get("processed_article_ids", [])}
    processed_signatures = set(state.get("processed_signatures", []))
    selected = await select_candidate_articles(limit=limit, select_count=select_count)

    created_topics: list[dict[str, Any]] = []
    skipped_articles: list[int] = []

    for article in selected:
        signature = _article_signature(article)
        if (article.id in processed or signature in processed_signatures) and not force:
            skipped_articles.append(article.id)
            continue
        created = await create_topic_from_article(article, start_discussion=start_discussion)
        created_topics.append(created)
        processed.add(article.id)
        processed_signatures.add(signature)
        state.setdefault("topics_by_article_id", {})[str(article.id)] = created["topic_id"]

    state["processed_article_ids"] = sorted(processed)[-500:]
    state["processed_signatures"] = sorted(processed_signatures)[-500:]
    _save_state(state)
    return {
        "selected_count": len(selected),
        "created_count": len(created_topics),
        "skipped_article_ids": skipped_articles,
        "created_topics": created_topics,
    }


async def run_source_feed_pipeline_forever() -> None:
    while True:
        try:
            result = await run_source_feed_pipeline(
                limit=int(os.getenv("SOURCE_FEED_AUTOMATION_FETCH_LIMIT", str(DEFAULT_FETCH_LIMIT))),
                select_count=int(os.getenv("SOURCE_FEED_AUTOMATION_SELECT_COUNT", str(DEFAULT_SELECT_COUNT))),
                start_discussion=_env_flag("SOURCE_FEED_AUTOMATION_START_DISCUSSION", True),
            )
            logger.info("Source-feed automation finished: %s", result)
        except Exception as exc:
            logger.exception("Source-feed automation failed: %s", exc)
        await asyncio.sleep(source_feed_automation_interval_seconds())
