"""Topic, posts, discussion, and topic-scoped proxy APIs."""

from __future__ import annotations

import asyncio
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import tempfile
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.auth import security, verify_access_token
from app.services.resonnet_client import request_json
from app.storage.database.postgres_client import get_db_session
from app.storage.database.topic_store import (
    DEFAULT_MODERATOR_MODE,
    close_topic,
    create_topic,
    extract_preview_image,
    get_post,
    get_generated_image,
    get_topic,
    get_topic_moderator_config,
    list_discussion_turns,
    list_posts,
    list_topic_experts,
    list_topics,
    make_post,
    replace_discussion_turns,
    replace_generated_images,
    replace_topic_experts,
    set_discussion_status,
    set_topic_moderator_config,
    update_topic,
    upsert_post,
)

router = APIRouter()

_PREVIEW_CACHE_DIRNAME = ".generated_image_previews"
_PREVIEW_DEFAULT_QUALITY = 72
_PREVIEW_DEFAULT_FORMAT = "webp"
_PREVIEW_MAX_DIMENSION = 2048
_DISCUSSION_SYNC_INTERVAL_SECONDS = 2.0


class TopicCreateRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    body: str = ""
    category: str | None = None


class TopicUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    category: str | None = None


class CreatePostRequest(BaseModel):
    author: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    in_reply_to_id: str | None = None


class MentionExpertRequest(BaseModel):
    author: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    expert_name: str = Field(..., min_length=1)
    in_reply_to_id: str | None = None


class MentionExpertResponse(BaseModel):
    user_post: dict
    reply_post_id: str
    status: str


class StartDiscussionRequest(BaseModel):
    num_rounds: int = Field(default=5, ge=1, le=20)
    max_turns: int = Field(default=50000, ge=10, le=50000)
    max_budget_usd: float = Field(default=500.0, ge=0.1)
    model: str | None = None
    allowed_tools: list[str] | None = None
    skill_list: list[str] | None = Field(default=None)
    mcp_server_ids: list[str] | None = None


def get_workspace_base() -> Path:
    import os

    raw = os.getenv("WORKSPACE_BASE", "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parents[2] / "workspace"


def _topic_workspace(topic_id: str) -> Path:
    return get_workspace_base() / "topics" / topic_id


def _preview_cache_dir(topic_id: str) -> Path:
    cache_dir = _topic_workspace(topic_id) / "shared" / _PREVIEW_CACHE_DIRNAME
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _resolve_generated_image_path(topic_id: str, asset_path: str) -> Path:
    generated_dir = (_topic_workspace(topic_id) / "shared" / "generated_images").resolve()
    target = (generated_dir / asset_path).resolve()
    if generated_dir != target and generated_dir not in target.parents:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return target


def _encode_image_to_webp(source_path: Path) -> dict:
    try:
        with Image.open(source_path) as image:
            normalized = ImageOps.exif_transpose(image)
            normalized.load()
            normalized = normalized.copy()
            width, height = normalized.size
            if normalized.mode not in {"RGB", "RGBA"}:
                normalized = normalized.convert("RGBA" if "A" in normalized.getbands() else "RGB")

            output = BytesIO()
            normalized.save(output, format="WEBP", quality=90, method=6)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=415, detail="Unsupported image format") from exc

    image_bytes = output.getvalue()
    return {
        "content_type": "image/webp",
        "image_bytes": image_bytes,
        "width": width,
        "height": height,
        "byte_size": len(image_bytes),
    }


def _build_preview_cache_path(
    topic_id: str,
    asset_key: str,
    source_path: Path,
    *,
    width: int | None,
    height: int | None,
    quality: int,
    output_format: str,
) -> Path:
    stat = source_path.stat()
    cache_key = sha256(
        f"{asset_key}|{stat.st_mtime_ns}|{stat.st_size}|{width}|{height}|{quality}|{output_format}".encode("utf-8")
    ).hexdigest()[:20]
    width_part = width if width is not None else "auto"
    height_part = height if height is not None else "auto"
    return _preview_cache_dir(topic_id) / (
        f"{source_path.stem}.{cache_key}.{width_part}x{height_part}.q{quality}.{output_format}"
    )


def _create_generated_image_preview(
    topic_id: str,
    asset_path: str,
    *,
    width: int | None,
    height: int | None,
    quality: int,
    output_format: str,
) -> Path:
    source_path = _resolve_generated_image_path(topic_id, asset_path)
    cache_path = _build_preview_cache_path(
        topic_id,
        asset_path,
        source_path,
        width=width,
        height=height,
        quality=quality,
        output_format=output_format,
    )
    if cache_path.exists():
        return cache_path

    max_size = (
        width if width is not None else _PREVIEW_MAX_DIMENSION,
        height if height is not None else _PREVIEW_MAX_DIMENSION,
    )

    try:
        with Image.open(source_path) as image:
            preview = ImageOps.exif_transpose(image)
            preview.load()
            preview = preview.copy()
            preview.thumbnail(max_size, Image.Resampling.LANCZOS)
            if preview.mode not in {"RGB", "RGBA"}:
                preview = preview.convert("RGBA" if "A" in preview.getbands() else "RGB")

            with tempfile.NamedTemporaryFile(
                dir=cache_path.parent,
                prefix=f"{cache_path.stem}.",
                suffix=".tmp",
                delete=False,
            ) as tmp_file:
                tmp_path = Path(tmp_file.name)
            try:
                preview.save(tmp_path, format=output_format.upper(), quality=quality, method=6)
                tmp_path.replace(cache_path)
            finally:
                if tmp_path.exists():
                    tmp_path.unlink()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=415, detail="Unsupported image format") from exc

    return cache_path


def _create_generated_image_preview_bytes(
    image_bytes: bytes,
    *,
    width: int | None,
    height: int | None,
    quality: int,
    output_format: str,
) -> bytes:
    max_size = (
        width if width is not None else _PREVIEW_MAX_DIMENSION,
        height if height is not None else _PREVIEW_MAX_DIMENSION,
    )
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            preview = ImageOps.exif_transpose(image)
            preview.load()
            preview = preview.copy()
            preview.thumbnail(max_size, Image.Resampling.LANCZOS)
            if preview.mode not in {"RGB", "RGBA"}:
                preview = preview.convert("RGBA" if "A" in preview.getbands() else "RGB")
            output = BytesIO()
            preview.save(output, format=output_format.upper(), quality=quality, method=6)
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=415, detail="Unsupported image format") from exc
    return output.getvalue()


def _build_posts_context(posts: list[dict]) -> str:
    if not posts:
        return "# Posts Context\n\n_No posts yet._\n"
    parts = ["# Posts Context"]
    for post in posts:
        author = post.get("expert_label") or post.get("author") or "unknown"
        status = post.get("status", "completed")
        header = f"## {author} ({post.get('author_type', 'unknown')}, {status})"
        body = (post.get("body") or "").strip() or "_empty_"
        parts.append(
            f"{header}\n\n- created_at: {post.get('created_at', '')}\n- id: {post.get('id')}\n\n{body}"
        )
    return "\n\n".join(parts) + "\n"


def _build_discussion_history(turns: list[dict]) -> str:
    parts: list[str] = []
    for turn in sorted(turns, key=lambda item: (item.get("round_num") or 0, item.get("turn_key") or "")):
        label = turn.get("expert_label") or turn.get("expert_name") or turn.get("turn_key", "Unknown")
        round_num = turn.get("round_num")
        heading = f"## Round {round_num} - {label}" if round_num else f"## {label}"
        parts.append(f"{heading}\n\n{(turn.get('body') or '').strip()}\n\n---")
    return "\n\n".join(parts)


def _discussion_progress_from_turns(topic: dict, turns: list[dict]) -> dict:
    latest_turn = turns[-1] if turns else None
    return {
        "completed_turns": len(turns),
        "total_turns": (topic.get("num_rounds") or 0) * len(topic.get("expert_names") or []),
        "current_round": latest_turn.get("round_num") if latest_turn else 0,
        "latest_speaker": (latest_turn or {}).get("expert_label") or (latest_turn or {}).get("expert_name") or "",
    }


def _row_user_name(user_id: int) -> str | None:
    with get_db_session() as session:
        row = session.execute(
            text("SELECT username, phone FROM users WHERE id = :id"),
            {"id": user_id},
        ).fetchone()
    if not row:
        return None
    return row[0] or row[1]


async def _get_optional_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict | None:
    if not credentials:
        return None
    return verify_access_token(credentials.credentials)


def _resolve_author_name(requested_author: str, user: dict | None) -> str:
    if not user:
        return requested_author
    user_id = user.get("sub")
    if user_id is None:
        return requested_author
    actual = _row_user_name(int(user_id))
    return actual or requested_author


def _resonnet_headers(authorization: str | None) -> dict[str, str]:
    if not authorization:
        return {}
    return {"Authorization": authorization}


async def _proxy_to_resonnet(
    method: str,
    path: str,
    *,
    authorization: str | None = None,
    json_body: dict | None = None,
    params: dict | None = None,
) -> Any:
    try:
        return await request_json(
            method,
            path,
            json_body=json_body,
            params=params,
            headers=_resonnet_headers(authorization),
            timeout=120.0,
        )
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text
        try:
            detail_json = exc.response.json()
            detail = detail_json.get("detail", detail_json)
        except Exception:
            pass
        raise HTTPException(status_code=exc.response.status_code, detail=detail) from exc


async def _ensure_executor_workspace(topic_id: str) -> dict:
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    await request_json(
        "POST",
        "/executor/topics/bootstrap",
        json_body={
            "topic_id": topic["id"],
            "topic_title": topic["title"],
            "topic_body": topic["body"],
            "num_rounds": topic.get("num_rounds") or 5,
        },
        timeout=120.0,
    )
    return topic


async def _sync_topic_experts_from_resonnet(topic_id: str, authorization: str | None) -> list[dict]:
    await _ensure_executor_workspace(topic_id)
    experts = await _proxy_to_resonnet("GET", f"/topics/{topic_id}/experts", authorization=authorization)
    replace_topic_experts(topic_id, experts)
    return experts


async def _sync_topic_mode_from_resonnet(topic_id: str, authorization: str | None) -> dict:
    await _ensure_executor_workspace(topic_id)
    config = await _proxy_to_resonnet("GET", f"/topics/{topic_id}/moderator-mode", authorization=authorization)
    config["mode_name"] = _mode_name_from_id(config.get("mode_id"))
    set_topic_moderator_config(topic_id, config)
    return config


def _collect_generated_images(topic_id: str, asset_paths: list[str]) -> list[dict]:
    generated_images: list[dict] = []
    for asset_path in asset_paths:
        try:
            encoded = _encode_image_to_webp(_resolve_generated_image_path(topic_id, asset_path))
        except HTTPException:
            continue
        generated_images.append({"asset_path": asset_path, **encoded})
    return generated_images


async def _sync_discussion_snapshot(topic_id: str) -> dict | None:
    try:
        snapshot = await request_json("GET", f"/executor/discussions/{topic_id}/snapshot", timeout=120.0)
    except Exception:
        return None

    turns = snapshot.get("turns") or []
    discussion_history = snapshot.get("discussion_history") or _build_discussion_history(turns)
    discussion_summary = snapshot.get("discussion_summary") or ""
    generated_images = _collect_generated_images(topic_id, snapshot.get("generated_images") or [])

    replace_discussion_turns(topic_id, turns)
    replace_generated_images(topic_id, generated_images)
    set_discussion_status(
        topic_id,
        "running",
        turns_count=snapshot.get("turns_count") or len(turns),
        discussion_summary=discussion_summary,
        discussion_history=discussion_history,
    )

    preview_markdown_ref = (
        extract_preview_image(discussion_summary)
        or extract_preview_image(discussion_history)
        or (f"../generated_images/{generated_images[0]['asset_path']}" if generated_images else None)
    )
    if preview_markdown_ref:
        update_topic(topic_id, {"preview_image": preview_markdown_ref})
    return snapshot


def _mode_name_from_id(mode_id: str | None) -> str:
    if mode_id == "custom":
        return "自定义模式"
    if mode_id == "standard":
        return "标准圆桌"
    return mode_id or "standard"


async def _run_discussion_background(topic_id: str, payload: dict) -> None:
    try:
        discussion_task = asyncio.create_task(
            request_json("POST", "/executor/discussions", json_body=payload, timeout=3600.0)
        )
        while not discussion_task.done():
            await asyncio.wait({discussion_task}, timeout=_DISCUSSION_SYNC_INTERVAL_SECONDS)
            await _sync_discussion_snapshot(topic_id)
        result = await discussion_task
        turns = result.get("turns") or []
        discussion_history = result.get("discussion_history") or _build_discussion_history(turns)
        discussion_summary = result.get("discussion_summary") or ""
        generated_images = _collect_generated_images(topic_id, result.get("generated_images") or [])
        replace_discussion_turns(topic_id, turns)
        replace_generated_images(topic_id, generated_images)
        set_discussion_status(
            topic_id,
            "completed",
            turns_count=result.get("turns_count") or len(turns),
            cost_usd=result.get("cost_usd"),
            completed_at=result.get("completed_at"),
            discussion_summary=discussion_summary,
            discussion_history=discussion_history,
        )
        preview_markdown_ref = (
            extract_preview_image(discussion_summary)
            or extract_preview_image(discussion_history)
            or (f"../generated_images/{generated_images[0]['asset_path']}" if generated_images else None)
        )
        if preview_markdown_ref:
            update_topic(topic_id, {"preview_image": preview_markdown_ref})
    except Exception:
        set_discussion_status(topic_id, "failed")


async def _run_expert_reply_background(topic_id: str, reply_post_id: str, payload: dict) -> None:
    try:
        result = await request_json("POST", "/executor/expert-replies", json_body=payload, timeout=1800.0)
        reply = get_post(topic_id, reply_post_id)
        if not reply:
            return
        reply["body"] = result.get("reply_body", "")
        reply["status"] = "completed"
        upsert_post(reply)
    except Exception:
        reply = get_post(topic_id, reply_post_id)
        if not reply:
            return
        reply["body"] = "(Expert reply failed; please try again later)"
        reply["status"] = "failed"
        upsert_post(reply)


@router.get("/topics")
def get_topics():
    return list_topics()


@router.post("/topics", status_code=201)
async def create_topic_endpoint(data: TopicCreateRequest):
    return create_topic(data.title, data.body, data.category)


@router.get("/topics/{topic_id}")
def get_topic_endpoint(topic_id: str):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic


@router.patch("/topics/{topic_id}")
def update_topic_endpoint(topic_id: str, data: TopicUpdateRequest):
    updated = update_topic(topic_id, data.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Topic not found")
    return updated


@router.post("/topics/{topic_id}/close")
def close_topic_endpoint(topic_id: str):
    closed = close_topic(topic_id)
    if not closed:
        raise HTTPException(status_code=404, detail="Topic not found")
    return closed


@router.get("/topics/{topic_id}/posts")
def list_posts_endpoint(topic_id: str):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return list_posts(topic_id)


@router.post("/topics/{topic_id}/posts", status_code=201)
def create_post_endpoint(topic_id: str, req: CreatePostRequest, user: dict | None = Depends(_get_optional_user)):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    author_name = _resolve_author_name(req.author, user)
    post = make_post(
        topic_id=topic_id,
        author=author_name,
        author_type="human",
        body=req.body,
        in_reply_to_id=req.in_reply_to_id,
        status="completed",
    )
    return upsert_post(post)


@router.post("/topics/{topic_id}/posts/mention", status_code=202, response_model=MentionExpertResponse)
async def mention_expert_endpoint(
    topic_id: str,
    req: MentionExpertRequest,
    user: dict | None = Depends(_get_optional_user),
):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic["discussion_status"] == "running":
        raise HTTPException(status_code=409, detail="Discussion is running; wait for it to finish before @mentioning experts")

    expert_map = {expert["name"]: expert for expert in list_topic_experts(topic_id)}
    expert = expert_map.get(req.expert_name)
    if expert is None:
        raise HTTPException(status_code=400, detail=f"Expert '{req.expert_name}' is not in this topic")

    author_name = _resolve_author_name(req.author, user)
    user_post = upsert_post(
        make_post(
            topic_id=topic_id,
            author=author_name,
            author_type="human",
            body=req.body,
            in_reply_to_id=req.in_reply_to_id,
            status="completed",
        )
    )
    reply_post = upsert_post(
        make_post(
            topic_id=topic_id,
            author=req.expert_name,
            author_type="agent",
            body="",
            expert_name=req.expert_name,
            expert_label=expert.get("label", req.expert_name),
            in_reply_to_id=user_post["id"],
            status="pending",
        )
    )
    payload = {
        "topic_id": topic_id,
        "topic_title": topic["title"],
        "topic_body": topic["body"],
        "expert_name": req.expert_name,
        "expert_label": expert.get("label", req.expert_name),
        "user_post_id": user_post["id"],
        "user_author": author_name,
        "user_question": req.body,
        "reply_post_id": reply_post["id"],
        "reply_created_at": reply_post["created_at"],
        "posts_context": _build_posts_context(list_posts(topic_id)),
    }
    asyncio.create_task(_run_expert_reply_background(topic_id, reply_post["id"], payload))
    return MentionExpertResponse(user_post=user_post, reply_post_id=reply_post["id"], status="pending")


@router.get("/topics/{topic_id}/posts/mention/{reply_post_id}")
def get_reply_status_endpoint(topic_id: str, reply_post_id: str):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    post = get_post(topic_id, reply_post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Reply post not found")
    return post


@router.post("/topics/{topic_id}/discussion", status_code=202)
async def start_discussion_endpoint(topic_id: str, req: StartDiscussionRequest):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic["discussion_status"] == "running":
        raise HTTPException(status_code=400, detail="Discussion already running")

    topic_config = get_topic_moderator_config(topic_id) or DEFAULT_MODERATOR_MODE
    num_rounds = int(topic_config.get("num_rounds") or topic["num_rounds"] or req.num_rounds)
    updated = update_topic(topic_id, {"num_rounds": num_rounds})
    if not updated:
        raise HTTPException(status_code=404, detail="Topic not found")
    set_discussion_status(topic_id, "running", turns_count=0, discussion_summary="", discussion_history="")
    payload = {
        "topic_id": topic_id,
        "topic_title": topic["title"],
        "topic_body": topic["body"],
        "num_rounds": num_rounds,
        "expert_names": topic["expert_names"],
        "max_turns": req.max_turns,
        "max_budget_usd": req.max_budget_usd,
        "model": req.model or topic_config.get("model"),
        "allowed_tools": req.allowed_tools,
        "skill_list": req.skill_list if req.skill_list is not None else topic_config.get("skill_list", []),
        "mcp_server_ids": req.mcp_server_ids if req.mcp_server_ids is not None else topic_config.get("mcp_server_ids", []),
        "posts_context": _build_posts_context(list_posts(topic_id)),
    }
    asyncio.create_task(_run_discussion_background(topic_id, payload))
    return {"status": "running", "result": None, "progress": None}


@router.get("/topics/{topic_id}/discussion/status")
async def get_discussion_status_endpoint(topic_id: str):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    if topic["discussion_status"] == "running":
        await _sync_discussion_snapshot(topic_id)
        topic = get_topic(topic_id)
        if not topic:
            raise HTTPException(status_code=404, detail="Topic not found")

    progress = None
    if topic["discussion_status"] == "running":
        progress = _discussion_progress_from_turns(topic, list_discussion_turns(topic_id))
    return {"status": topic["discussion_status"], "result": topic.get("discussion_result"), "progress": progress}


@router.get("/topics/{topic_id}/assets/generated_images/{asset_path:path}")
def get_generated_image_endpoint(
    topic_id: str,
    asset_path: str,
    w: int | None = Query(default=None, ge=1, le=_PREVIEW_MAX_DIMENSION),
    h: int | None = Query(default=None, ge=1, le=_PREVIEW_MAX_DIMENSION),
    q: int = Query(default=_PREVIEW_DEFAULT_QUALITY, ge=30, le=95),
    fm: str | None = Query(default=None, pattern="^webp$"),
):
    stored = get_generated_image(topic_id, asset_path)
    if stored is not None:
        if w is None and h is None and fm is None:
            return Response(
                content=stored["image_bytes"],
                media_type=stored["content_type"],
                headers={"Cache-Control": "public, max-age=300"},
            )
        output_format = fm or _PREVIEW_DEFAULT_FORMAT
        return Response(
            content=_create_generated_image_preview_bytes(
                stored["image_bytes"],
                width=w,
                height=h,
                quality=q,
                output_format=output_format,
            ),
            media_type=f"image/{output_format}",
            headers={"Cache-Control": "public, max-age=300"},
        )

    if w is None and h is None and fm is None:
        return FileResponse(_resolve_generated_image_path(topic_id, asset_path), headers={"Cache-Control": "public, max-age=300"})
    output_format = fm or _PREVIEW_DEFAULT_FORMAT
    return FileResponse(
        _create_generated_image_preview(
            topic_id,
            asset_path,
            width=w,
            height=h,
            quality=q,
            output_format=output_format,
        ),
        media_type=f"image/{output_format}",
        headers={"Cache-Control": "public, max-age=300"},
    )


@router.get("/topics/{topic_id}/experts")
async def list_topic_experts_endpoint(topic_id: str, authorization: str | None = Header(default=None)):
    topic = get_topic(topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")
    return await _sync_topic_experts_from_resonnet(topic_id, authorization)


@router.post("/topics/{topic_id}/experts", status_code=201)
async def add_topic_expert_endpoint(topic_id: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    result = await _proxy_to_resonnet("POST", f"/topics/{topic_id}/experts", authorization=authorization, json_body=req)
    await _sync_topic_experts_from_resonnet(topic_id, authorization)
    return result


@router.put("/topics/{topic_id}/experts/{expert_name}")
async def update_topic_expert_endpoint(topic_id: str, expert_name: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    result = await _proxy_to_resonnet(
        "PUT",
        f"/topics/{topic_id}/experts/{expert_name}",
        authorization=authorization,
        json_body=req,
    )
    await _sync_topic_experts_from_resonnet(topic_id, authorization)
    return result


@router.delete("/topics/{topic_id}/experts/{expert_name}")
async def delete_topic_expert_endpoint(topic_id: str, expert_name: str, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    result = await _proxy_to_resonnet(
        "DELETE",
        f"/topics/{topic_id}/experts/{expert_name}",
        authorization=authorization,
    )
    await _sync_topic_experts_from_resonnet(topic_id, authorization)
    return result


@router.get("/topics/{topic_id}/experts/{expert_name}/content")
async def get_topic_expert_content_endpoint(topic_id: str, expert_name: str, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    return await _proxy_to_resonnet(
        "GET",
        f"/topics/{topic_id}/experts/{expert_name}/content",
        authorization=authorization,
    )


@router.post("/topics/{topic_id}/experts/generate")
async def generate_topic_expert_endpoint(topic_id: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    result = await _proxy_to_resonnet(
        "POST",
        f"/topics/{topic_id}/experts/generate",
        authorization=authorization,
        json_body=req,
    )
    await _sync_topic_experts_from_resonnet(topic_id, authorization)
    return result


@router.post("/topics/{topic_id}/experts/{expert_name}/share")
async def share_topic_expert_endpoint(topic_id: str, expert_name: str, req: dict | None = None, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    return await _proxy_to_resonnet(
        "POST",
        f"/topics/{topic_id}/experts/{expert_name}/share",
        authorization=authorization,
        json_body=req,
    )


@router.get("/topics/{topic_id}/moderator-mode")
async def get_topic_moderator_mode_endpoint(topic_id: str, authorization: str | None = Header(default=None)):
    return await _sync_topic_mode_from_resonnet(topic_id, authorization)


@router.put("/topics/{topic_id}/moderator-mode")
async def set_topic_moderator_mode_endpoint(topic_id: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    await _proxy_to_resonnet(
        "PUT",
        f"/topics/{topic_id}/moderator-mode",
        authorization=authorization,
        json_body=req,
    )
    return await _sync_topic_mode_from_resonnet(topic_id, authorization)


@router.post("/topics/{topic_id}/moderator-mode/generate")
async def generate_topic_moderator_mode_endpoint(topic_id: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    result = await _proxy_to_resonnet(
        "POST",
        f"/topics/{topic_id}/moderator-mode/generate",
        authorization=authorization,
        json_body=req,
    )
    config = result.get("config") or {}
    config["mode_name"] = _mode_name_from_id(config.get("mode_id"))
    set_topic_moderator_config(topic_id, config)
    return result


@router.post("/topics/{topic_id}/moderator-mode/share")
async def share_topic_moderator_mode_endpoint(topic_id: str, req: dict, authorization: str | None = Header(default=None)):
    await _ensure_executor_workspace(topic_id)
    return await _proxy_to_resonnet(
        "POST",
        f"/topics/{topic_id}/moderator-mode/share",
        authorization=authorization,
        json_body=req,
    )
