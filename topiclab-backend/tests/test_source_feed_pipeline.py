import json

import pytest

from app.services.source_feed_pipeline import (
    SourceArticle,
    get_pipeline_state_file,
    get_resonnet_base_url,
    run_source_feed_pipeline,
)


def test_get_resonnet_base_url_defaults_to_internal_backend_url(monkeypatch):
    monkeypatch.delenv("RESONNET_BASE_URL", raising=False)
    monkeypatch.setenv("BACKEND_PORT", "8010")

    assert get_resonnet_base_url() == "http://backend:8000"


def test_get_resonnet_base_url_uses_explicit_override(monkeypatch):
    monkeypatch.setenv("RESONNET_BASE_URL", "http://127.0.0.1:8010/")

    assert get_resonnet_base_url() == "http://127.0.0.1:8010"


@pytest.mark.asyncio
async def test_run_source_feed_pipeline_advances_to_next_ranked_article(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACE_BASE", str(tmp_path))
    state_file = get_pipeline_state_file()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {
                "processed_article_ids": [101],
                "processed_signatures": ["feed-a|alpha|https://example.com/a"],
                "topics_by_article_id": {"101": "topic-101"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    articles = [
        SourceArticle(
            id=101,
            title="Alpha",
            source_feed_name="Feed A",
            source_type="rss",
            url="https://example.com/a",
            pic_url=None,
            description="alpha",
            publish_time="2026-03-13",
            created_at="2026-03-13T00:00:00Z",
            content_md="agent ai 芯片",
        ),
        SourceArticle(
            id=102,
            title="Beta",
            source_feed_name="Feed B",
            source_type="rss",
            url="https://example.com/b",
            pic_url=None,
            description="beta",
            publish_time="2026-03-13",
            created_at="2026-03-13T00:00:00Z",
            content_md="agent ai",
        ),
        SourceArticle(
            id=103,
            title="Gamma",
            source_feed_name="Feed C",
            source_type="rss",
            url="https://example.com/c",
            pic_url=None,
            description="gamma",
            publish_time="2026-03-13",
            created_at="2026-03-13T00:00:00Z",
            content_md="ai",
        ),
    ]

    async def mock_select_candidate_articles(limit: int, select_count: int):
        return articles

    async def mock_create_topic_from_article(article: SourceArticle, start_discussion: bool = True):
        return {
            "topic_id": f"topic-{article.id}",
            "article_id": article.id,
            "article_title": article.title,
            "topic_title": f"Topic {article.title}",
            "score": 99,
            "material_paths": [],
            "discussion_started": start_discussion,
            "discussion_status": "running" if start_discussion else None,
        }

    monkeypatch.setattr(
        "app.services.source_feed_pipeline.select_candidate_articles",
        mock_select_candidate_articles,
    )
    monkeypatch.setattr(
        "app.services.source_feed_pipeline.create_topic_from_article",
        mock_create_topic_from_article,
    )

    result = await run_source_feed_pipeline(limit=5, select_count=1, start_discussion=True, force=False)

    assert result["created_count"] == 1
    assert result["created_topics"][0]["article_id"] == 102
    assert result["skipped_article_ids"] == [101]
    assert result["inspected_count"] == 2
