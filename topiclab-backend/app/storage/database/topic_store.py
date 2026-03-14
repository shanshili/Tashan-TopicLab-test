"""Database-backed topic business storage for TopicLab."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import uuid

from sqlalchemy import text

from app.storage.database.postgres_client import get_db_session


DEFAULT_TOPIC_EXPERT_NAMES = [
    "physicist",
    "biologist",
    "computer_scientist",
    "ethicist",
]

DEFAULT_TOPIC_SKILL_IDS = ["image_generation"]
DEFAULT_MODERATOR_MODE = {
    "mode_id": "standard",
    "num_rounds": 5,
    "custom_prompt": None,
    "skill_list": DEFAULT_TOPIC_SKILL_IDS,
    "mcp_server_ids": [],
    "model": None,
}


@dataclass
class TopicRecord:
    id: str
    session_id: str
    title: str
    body: str
    category: str | None
    status: str
    mode: str
    num_rounds: int
    expert_names: list[str]
    discussion_status: str
    created_at: str
    updated_at: str
    moderator_mode_id: str | None
    moderator_mode_name: str | None
    preview_image: str | None
    creator_user_id: int | None
    creator_name: str | None
    creator_auth_type: str | None
    discussion_result: dict | None


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _json_loads(value, default):
    if value in (None, ""):
        return default
    if isinstance(value, (list, dict)):
        return value
    return json.loads(value)


def init_topic_tables() -> None:
    """Create topic business tables if they do not exist."""
    with get_db_session() as session:
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topics (
                id VARCHAR(36) PRIMARY KEY,
                session_id VARCHAR(36) NOT NULL,
                title VARCHAR(200) NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                category VARCHAR(255),
                status VARCHAR(32) NOT NULL,
                mode VARCHAR(32) NOT NULL,
                num_rounds INTEGER NOT NULL DEFAULT 5,
                expert_names TEXT NOT NULL DEFAULT '[]',
                discussion_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                moderator_mode_id VARCHAR(64),
                moderator_mode_name VARCHAR(255),
                preview_image TEXT,
                creator_user_id INTEGER,
                creator_name VARCHAR(255),
                creator_auth_type VARCHAR(64)
            )
        """))
        session.execute(text("ALTER TABLE topics ADD COLUMN IF NOT EXISTS creator_user_id INTEGER"))
        session.execute(text("ALTER TABLE topics ADD COLUMN IF NOT EXISTS creator_name VARCHAR(255)"))
        session.execute(text("ALTER TABLE topics ADD COLUMN IF NOT EXISTS creator_auth_type VARCHAR(64)"))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS discussion_runs (
                topic_id VARCHAR(36) PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                turns_count INTEGER NOT NULL DEFAULT 0,
                cost_usd DOUBLE PRECISION,
                completed_at TIMESTAMPTZ,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                discussion_summary TEXT NOT NULL DEFAULT '',
                discussion_history TEXT NOT NULL DEFAULT ''
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS posts (
                id VARCHAR(36) PRIMARY KEY,
                topic_id VARCHAR(36) NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                author VARCHAR(255) NOT NULL,
                author_type VARCHAR(32) NOT NULL,
                expert_name VARCHAR(255),
                expert_label VARCHAR(255),
                body TEXT NOT NULL DEFAULT '',
                mentions TEXT NOT NULL DEFAULT '[]',
                in_reply_to_id VARCHAR(36),
                status VARCHAR(32) NOT NULL DEFAULT 'completed',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_posts_topic_created
            ON posts(topic_id, created_at)
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_posts_reply
            ON posts(in_reply_to_id)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS discussion_turns (
                id VARCHAR(36) PRIMARY KEY,
                topic_id VARCHAR(36) NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                turn_key VARCHAR(255) NOT NULL,
                round_num INTEGER,
                expert_name VARCHAR(255),
                expert_label VARCHAR(255),
                body TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(topic_id, turn_key)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_discussion_turns_topic
            ON discussion_turns(topic_id, round_num)
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topic_experts (
                topic_id VARCHAR(36) NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                expert_name VARCHAR(255) NOT NULL,
                expert_label VARCHAR(255) NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source VARCHAR(64) NOT NULL DEFAULT 'preset',
                is_from_topic_creation BOOLEAN NOT NULL DEFAULT FALSE,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (topic_id, expert_name)
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topic_moderator_configs (
                topic_id VARCHAR(36) PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
                mode_id VARCHAR(64) NOT NULL,
                num_rounds INTEGER NOT NULL DEFAULT 5,
                custom_prompt TEXT,
                skill_list TEXT NOT NULL DEFAULT '[]',
                mcp_server_ids TEXT NOT NULL DEFAULT '[]',
                model VARCHAR(255),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """))
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS topic_generated_images (
                id VARCHAR(36) PRIMARY KEY,
                topic_id VARCHAR(36) NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                asset_path TEXT NOT NULL,
                content_type VARCHAR(64) NOT NULL DEFAULT 'image/webp',
                image_bytes BYTEA NOT NULL,
                width INTEGER,
                height INTEGER,
                byte_size INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(topic_id, asset_path)
            )
        """))
        session.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_topic_generated_images_topic
            ON topic_generated_images(topic_id)
        """))


def _build_topic(row) -> TopicRecord:
    discussion_result = None
    if row.run_status:
        discussion_result = {
            "discussion_history": row.discussion_history or "",
            "discussion_summary": row.discussion_summary or "",
            "turns_count": row.turns_count or 0,
            "cost_usd": row.cost_usd,
            "completed_at": _to_iso(row.completed_at),
        }

    return TopicRecord(
        id=row.id,
        session_id=row.session_id,
        title=row.title,
        body=row.body or "",
        category=row.category,
        status=row.status,
        mode=row.mode,
        num_rounds=row.num_rounds,
        expert_names=_json_loads(row.expert_names, []),
        discussion_status=row.discussion_status,
        created_at=_to_iso(row.created_at),
        updated_at=_to_iso(row.updated_at),
        moderator_mode_id=row.moderator_mode_id,
        moderator_mode_name=row.moderator_mode_name,
        preview_image=row.preview_image,
        creator_user_id=row.creator_user_id,
        creator_name=row.creator_name,
        creator_auth_type=row.creator_auth_type,
        discussion_result=discussion_result,
    )


def create_topic(
    title: str,
    body: str = "",
    category: str | None = None,
    *,
    creator_user_id: int | None = None,
    creator_name: str | None = None,
    creator_auth_type: str | None = None,
) -> dict:
    topic_id = str(uuid.uuid4())
    now = utc_now()
    preview_image = extract_preview_image(body)
    with get_db_session() as session:
        session.execute(
            text("""
                INSERT INTO topics (
                    id, session_id, title, body, category, status, mode, num_rounds,
                    expert_names, discussion_status, created_at, updated_at,
                    moderator_mode_id, moderator_mode_name, preview_image,
                    creator_user_id, creator_name, creator_auth_type
                ) VALUES (
                    :id, :session_id, :title, :body, :category, :status, :mode, :num_rounds,
                    :expert_names, :discussion_status, :created_at, :updated_at,
                    :moderator_mode_id, :moderator_mode_name, :preview_image,
                    :creator_user_id, :creator_name, :creator_auth_type
                )
            """),
            {
                "id": topic_id,
                "session_id": topic_id,
                "title": title,
                "body": body,
                "category": category,
                "status": "open",
                "mode": "discussion",
                "num_rounds": 5,
                "expert_names": json.dumps(DEFAULT_TOPIC_EXPERT_NAMES, ensure_ascii=False),
                "discussion_status": "pending",
                "created_at": now,
                "updated_at": now,
                "moderator_mode_id": "standard",
                "moderator_mode_name": "标准圆桌",
                "preview_image": preview_image,
                "creator_user_id": creator_user_id,
                "creator_name": creator_name,
                "creator_auth_type": creator_auth_type,
            },
        )
        session.execute(
            text("""
                INSERT INTO discussion_runs (
                    topic_id, status, turns_count, updated_at, discussion_summary, discussion_history
                ) VALUES (
                    :topic_id, :status, 0, :updated_at, '', ''
                )
            """),
            {"topic_id": topic_id, "status": "pending", "updated_at": now},
        )
        replace_topic_experts(
            topic_id,
            [
                {
                    "name": name,
                    "label": name,
                    "description": "",
                    "source": "preset",
                    "is_from_topic_creation": True,
                }
                for name in DEFAULT_TOPIC_EXPERT_NAMES
            ],
            session=session,
        )
        set_topic_moderator_config(topic_id, DEFAULT_MODERATOR_MODE, session=session)
    return get_topic(topic_id)


def list_topics(category: str | None = None) -> list[dict]:
    with get_db_session() as session:
        if category:
            rows = session.execute(text("""
                SELECT
                    t.*,
                    r.status AS run_status,
                    r.turns_count,
                    r.cost_usd,
                    r.completed_at,
                    r.discussion_summary,
                    r.discussion_history
                FROM topics t
                LEFT JOIN discussion_runs r ON r.topic_id = t.id
                WHERE t.category = :category
                ORDER BY t.updated_at DESC
            """), {"category": category}).fetchall()
        else:
            rows = session.execute(text("""
                SELECT
                    t.*,
                    r.status AS run_status,
                    r.turns_count,
                    r.cost_usd,
                    r.completed_at,
                    r.discussion_summary,
                    r.discussion_history
                FROM topics t
                LEFT JOIN discussion_runs r ON r.topic_id = t.id
                ORDER BY t.updated_at DESC
            """)).fetchall()
    return [topic_record_to_dict(_build_topic(row), lightweight=True) for row in rows]


def get_topic(topic_id: str) -> dict | None:
    with get_db_session() as session:
        row = session.execute(
            text("""
                SELECT
                    t.*,
                    r.status AS run_status,
                    r.turns_count,
                    r.cost_usd,
                    r.completed_at,
                    r.discussion_summary,
                    r.discussion_history
                FROM topics t
                LEFT JOIN discussion_runs r ON r.topic_id = t.id
                WHERE t.id = :topic_id
            """),
            {"topic_id": topic_id},
        ).fetchone()
    if not row:
        return None
    return topic_record_to_dict(_build_topic(row))


def update_topic(topic_id: str, data: dict) -> dict | None:
    allowed = {
        "title",
        "body",
        "category",
        "status",
        "num_rounds",
        "expert_names",
        "moderator_mode_id",
        "moderator_mode_name",
        "preview_image",
    }
    payload = {k: v for k, v in data.items() if k in allowed}
    if not payload:
        return get_topic(topic_id)
    if "expert_names" in payload:
        payload["expert_names"] = json.dumps(payload["expert_names"], ensure_ascii=False)
    if "body" in payload and "preview_image" not in payload:
        payload["preview_image"] = extract_preview_image(payload["body"])
    payload["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = :{key}" for key in payload)
    payload["topic_id"] = topic_id
    with get_db_session() as session:
        result = session.execute(
            text(f"UPDATE topics SET {assignments} WHERE id = :topic_id"),
            payload,
        )
        if result.rowcount == 0:
            return None
    return get_topic(topic_id)


def close_topic(topic_id: str) -> dict | None:
    return update_topic(topic_id, {"status": "closed"})


def set_discussion_status(topic_id: str, status: str, *, turns_count: int | None = None, cost_usd: float | None = None,
                          completed_at: str | None = None, discussion_summary: str | None = None,
                          discussion_history: str | None = None) -> dict | None:
    now = utc_now()
    with get_db_session() as session:
        topic_result = session.execute(
            text("""
                UPDATE topics
                SET discussion_status = :status, updated_at = :updated_at
                WHERE id = :topic_id
            """),
            {"topic_id": topic_id, "status": status, "updated_at": now},
        )
        if topic_result.rowcount == 0:
            return None
        session.execute(
            text("""
                INSERT INTO discussion_runs (
                    topic_id, status, turns_count, cost_usd, completed_at,
                    updated_at, discussion_summary, discussion_history
                ) VALUES (
                    :topic_id, :status, :turns_count, :cost_usd, :completed_at,
                    :updated_at, :discussion_summary, :discussion_history
                )
                ON CONFLICT (topic_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    turns_count = EXCLUDED.turns_count,
                    cost_usd = EXCLUDED.cost_usd,
                    completed_at = EXCLUDED.completed_at,
                    updated_at = EXCLUDED.updated_at,
                    discussion_summary = EXCLUDED.discussion_summary,
                    discussion_history = EXCLUDED.discussion_history
            """),
            {
                "topic_id": topic_id,
                "status": status,
                "turns_count": turns_count or 0,
                "cost_usd": cost_usd,
                "completed_at": completed_at,
                "updated_at": now,
                "discussion_summary": discussion_summary or "",
                "discussion_history": discussion_history or "",
            },
        )
    return get_topic(topic_id)


def list_posts(topic_id: str) -> list[dict]:
    with get_db_session() as session:
        rows = session.execute(
            text("""
                SELECT * FROM posts
                WHERE topic_id = :topic_id
                ORDER BY created_at ASC, id ASC
            """),
            {"topic_id": topic_id},
        ).fetchall()
    return [post_row_to_dict(row) for row in rows]


def get_post(topic_id: str, post_id: str) -> dict | None:
    with get_db_session() as session:
        row = session.execute(
            text("SELECT * FROM posts WHERE topic_id = :topic_id AND id = :post_id"),
            {"topic_id": topic_id, "post_id": post_id},
        ).fetchone()
    return post_row_to_dict(row) if row else None


def upsert_post(post: dict) -> dict:
    created_at = post.get("created_at") or utc_now().isoformat()
    with get_db_session() as session:
        session.execute(
            text("""
                INSERT INTO posts (
                    id, topic_id, author, author_type, expert_name, expert_label,
                    body, mentions, in_reply_to_id, status, created_at
                ) VALUES (
                    :id, :topic_id, :author, :author_type, :expert_name, :expert_label,
                    :body, :mentions, :in_reply_to_id, :status, :created_at
                )
                ON CONFLICT (id) DO UPDATE SET
                    topic_id = EXCLUDED.topic_id,
                    author = EXCLUDED.author,
                    author_type = EXCLUDED.author_type,
                    expert_name = EXCLUDED.expert_name,
                    expert_label = EXCLUDED.expert_label,
                    body = EXCLUDED.body,
                    mentions = EXCLUDED.mentions,
                    in_reply_to_id = EXCLUDED.in_reply_to_id,
                    status = EXCLUDED.status,
                    created_at = EXCLUDED.created_at
            """),
            {
                "id": post["id"],
                "topic_id": post["topic_id"],
                "author": post["author"],
                "author_type": post["author_type"],
                "expert_name": post.get("expert_name"),
                "expert_label": post.get("expert_label"),
                "body": post.get("body", ""),
                "mentions": json.dumps(post.get("mentions") or [], ensure_ascii=False),
                "in_reply_to_id": post.get("in_reply_to_id"),
                "status": post.get("status", "completed"),
                "created_at": created_at,
            },
        )
    return get_post(post["topic_id"], post["id"])


def make_post(
    topic_id: str,
    author: str,
    author_type: str,
    body: str,
    *,
    expert_name: str | None = None,
    expert_label: str | None = None,
    in_reply_to_id: str | None = None,
    status: str = "completed",
) -> dict:
    import re

    return {
        "id": str(uuid.uuid4()),
        "topic_id": topic_id,
        "author": author,
        "author_type": author_type,
        "expert_name": expert_name,
        "expert_label": expert_label,
        "body": body,
        "mentions": re.findall(r"@(\w+)", body or ""),
        "in_reply_to_id": in_reply_to_id,
        "status": status,
        "created_at": utc_now().isoformat(),
    }


def replace_discussion_turns(topic_id: str, turns: list[dict]) -> None:
    now = utc_now()
    with get_db_session() as session:
        session.execute(text("DELETE FROM discussion_turns WHERE topic_id = :topic_id"), {"topic_id": topic_id})
        for turn in turns:
            session.execute(
                text("""
                    INSERT INTO discussion_turns (
                        id, topic_id, turn_key, round_num, expert_name, expert_label, body, created_at, updated_at
                    ) VALUES (
                        :id, :topic_id, :turn_key, :round_num, :expert_name, :expert_label, :body, :created_at, :updated_at
                    )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "topic_id": topic_id,
                    "turn_key": turn["turn_key"],
                    "round_num": turn.get("round_num"),
                    "expert_name": turn.get("expert_name"),
                    "expert_label": turn.get("expert_label"),
                    "body": turn.get("body", ""),
                    "created_at": turn.get("updated_at") or now,
                    "updated_at": turn.get("updated_at") or now,
                },
            )


def list_discussion_turns(topic_id: str) -> list[dict]:
    with get_db_session() as session:
        rows = session.execute(
            text("""
                SELECT turn_key, round_num, expert_name, expert_label, body, created_at, updated_at
                FROM discussion_turns
                WHERE topic_id = :topic_id
                ORDER BY round_num ASC NULLS LAST, turn_key ASC
            """),
            {"topic_id": topic_id},
        ).fetchall()
    return [
        {
            "turn_key": row.turn_key,
            "round_num": row.round_num,
            "expert_name": row.expert_name,
            "expert_label": row.expert_label,
            "body": row.body or "",
            "created_at": _to_iso(row.created_at),
            "updated_at": _to_iso(row.updated_at),
        }
        for row in rows
    ]


def replace_generated_images(topic_id: str, images: list[dict]) -> None:
    now = utc_now()
    with get_db_session() as session:
        session.execute(text("DELETE FROM topic_generated_images WHERE topic_id = :topic_id"), {"topic_id": topic_id})
        for image in images:
            session.execute(
                text("""
                    INSERT INTO topic_generated_images (
                        id, topic_id, asset_path, content_type, image_bytes,
                        width, height, byte_size, created_at, updated_at
                    ) VALUES (
                        :id, :topic_id, :asset_path, :content_type, :image_bytes,
                        :width, :height, :byte_size, :created_at, :updated_at
                    )
                """),
                {
                    "id": str(uuid.uuid4()),
                    "topic_id": topic_id,
                    "asset_path": image["asset_path"],
                    "content_type": image.get("content_type", "image/webp"),
                    "image_bytes": image["image_bytes"],
                    "width": image.get("width"),
                    "height": image.get("height"),
                    "byte_size": image.get("byte_size", len(image["image_bytes"])),
                    "created_at": now,
                    "updated_at": now,
                },
            )


def get_generated_image(topic_id: str, asset_path: str) -> dict | None:
    with get_db_session() as session:
        row = session.execute(
            text("""
                SELECT asset_path, content_type, image_bytes, width, height, byte_size, updated_at
                FROM topic_generated_images
                WHERE topic_id = :topic_id AND asset_path = :asset_path
            """),
            {"topic_id": topic_id, "asset_path": asset_path},
        ).fetchone()
    if not row:
        return None
    return {
        "asset_path": row.asset_path,
        "content_type": row.content_type,
        "image_bytes": bytes(row.image_bytes),
        "width": row.width,
        "height": row.height,
        "byte_size": row.byte_size,
        "updated_at": _to_iso(row.updated_at),
    }


def replace_topic_experts(topic_id: str, experts: list[dict], *, session=None) -> None:
    owns_session = session is None
    if owns_session:
        ctx = get_db_session()
        session = ctx.__enter__()
    try:
        session.execute(text("DELETE FROM topic_experts WHERE topic_id = :topic_id"), {"topic_id": topic_id})
        for expert in experts:
            session.execute(
                text("""
                    INSERT INTO topic_experts (
                        topic_id, expert_name, expert_label, description, source,
                        is_from_topic_creation, updated_at
                    ) VALUES (
                        :topic_id, :expert_name, :expert_label, :description, :source,
                        :is_from_topic_creation, :updated_at
                    )
                """),
                {
                    "topic_id": topic_id,
                    "expert_name": expert["name"],
                    "expert_label": expert.get("label", expert["name"]),
                    "description": expert.get("description", ""),
                    "source": expert.get("source", "preset"),
                    "is_from_topic_creation": bool(expert.get("is_from_topic_creation", False)),
                    "updated_at": utc_now(),
                },
            )
        session.execute(
            text("""
                UPDATE topics
                SET expert_names = :expert_names, updated_at = :updated_at
                WHERE id = :topic_id
            """),
            {
                "topic_id": topic_id,
                "expert_names": json.dumps([expert["name"] for expert in experts], ensure_ascii=False),
                "updated_at": utc_now(),
            },
        )
        if owns_session:
            ctx.__exit__(None, None, None)
    except Exception as exc:
        if owns_session:
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise


def list_topic_experts(topic_id: str) -> list[dict]:
    with get_db_session() as session:
        rows = session.execute(
            text("""
                SELECT expert_name, expert_label, description, source, is_from_topic_creation
                FROM topic_experts
                WHERE topic_id = :topic_id
                ORDER BY expert_name ASC
            """),
            {"topic_id": topic_id},
        ).fetchall()
    return [
        {
            "name": row[0],
            "label": row[1],
            "description": row[2],
            "source": row[3],
            "is_from_topic_creation": bool(row[4]),
        }
        for row in rows
    ]


def set_topic_moderator_config(topic_id: str, config: dict, *, session=None) -> None:
    owns_session = session is None
    if owns_session:
        ctx = get_db_session()
        session = ctx.__enter__()
    try:
        session.execute(
            text("""
                INSERT INTO topic_moderator_configs (
                    topic_id, mode_id, num_rounds, custom_prompt, skill_list, mcp_server_ids, model, updated_at
                ) VALUES (
                    :topic_id, :mode_id, :num_rounds, :custom_prompt, :skill_list, :mcp_server_ids, :model, :updated_at
                )
                ON CONFLICT (topic_id) DO UPDATE SET
                    mode_id = EXCLUDED.mode_id,
                    num_rounds = EXCLUDED.num_rounds,
                    custom_prompt = EXCLUDED.custom_prompt,
                    skill_list = EXCLUDED.skill_list,
                    mcp_server_ids = EXCLUDED.mcp_server_ids,
                    model = EXCLUDED.model,
                    updated_at = EXCLUDED.updated_at
            """),
            {
                "topic_id": topic_id,
                "mode_id": config.get("mode_id", "standard"),
                "num_rounds": int(config.get("num_rounds") or 5),
                "custom_prompt": config.get("custom_prompt"),
                "skill_list": json.dumps(config.get("skill_list") or [], ensure_ascii=False),
                "mcp_server_ids": json.dumps(config.get("mcp_server_ids") or [], ensure_ascii=False),
                "model": config.get("model"),
                "updated_at": utc_now(),
            },
        )
        mode_name = "自定义模式" if config.get("mode_id") == "custom" else config.get("mode_name", "标准圆桌")
        session.execute(
            text("""
                UPDATE topics
                SET moderator_mode_id = :mode_id,
                    moderator_mode_name = :mode_name,
                    num_rounds = :num_rounds,
                    updated_at = :updated_at
                WHERE id = :topic_id
            """),
            {
                "topic_id": topic_id,
                "mode_id": config.get("mode_id", "standard"),
                "mode_name": mode_name,
                "num_rounds": int(config.get("num_rounds") or 5),
                "updated_at": utc_now(),
            },
        )
        if owns_session:
            ctx.__exit__(None, None, None)
    except Exception as exc:
        if owns_session:
            ctx.__exit__(type(exc), exc, exc.__traceback__)
        raise


def get_topic_moderator_config(topic_id: str) -> dict | None:
    with get_db_session() as session:
        row = session.execute(
            text("""
                SELECT mode_id, num_rounds, custom_prompt, skill_list, mcp_server_ids, model
                FROM topic_moderator_configs
                WHERE topic_id = :topic_id
            """),
            {"topic_id": topic_id},
        ).fetchone()
    if not row:
        return None
    return {
        "mode_id": row[0],
        "num_rounds": row[1],
        "custom_prompt": row[2],
        "skill_list": _json_loads(row[3], []),
        "mcp_server_ids": _json_loads(row[4], []),
        "model": row[5],
    }


def extract_preview_image(markdown: str | None) -> str | None:
    import re

    if not markdown:
        return None
    match = re.search(r"!\[[^\]]*]\(([^)\s]+(?:\s+\"[^\"]*\")?)\)", markdown)
    if not match:
        return None
    raw = match.group(1).strip()
    return raw.split('"')[0].strip() if '"' in raw else raw


def topic_record_to_dict(record: TopicRecord, *, lightweight: bool = False) -> dict:
    base = {
        "id": record.id,
        "session_id": record.session_id,
        "title": record.title,
        "body": record.body,
        "category": record.category,
        "status": record.status,
        "mode": record.mode,
        "discussion_status": record.discussion_status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "moderator_mode_id": record.moderator_mode_id,
        "moderator_mode_name": record.moderator_mode_name,
        "preview_image": record.preview_image,
        "creator_user_id": record.creator_user_id,
        "creator_name": record.creator_name,
        "creator_auth_type": record.creator_auth_type,
    }
    if lightweight:
        return base
    base["num_rounds"] = record.num_rounds
    base["expert_names"] = record.expert_names
    base["discussion_result"] = record.discussion_result
    return base


def post_row_to_dict(row) -> dict:
    return {
        "id": row.id,
        "topic_id": row.topic_id,
        "author": row.author,
        "author_type": row.author_type,
        "expert_name": row.expert_name,
        "expert_label": row.expert_label,
        "body": row.body or "",
        "mentions": _json_loads(row.mentions, []),
        "in_reply_to_id": row.in_reply_to_id,
        "status": row.status,
        "created_at": _to_iso(row.created_at),
    }
