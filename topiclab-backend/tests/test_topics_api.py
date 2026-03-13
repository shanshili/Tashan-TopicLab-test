import asyncio
import importlib
import time
from pathlib import Path

import pytest
from PIL import Image


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "topiclab-test.db"
    workspace_base = tmp_path / "workspace"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WORKSPACE_BASE", str(workspace_base))
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    monkeypatch.setenv("RESONNET_BASE_URL", "http://resonnet.test")

    from app.storage.database import postgres_client
    postgres_client.reset_db_state()

    import app.api.auth as auth_module
    import app.api.topics as topics_module
    import main as main_module

    importlib.reload(postgres_client)
    importlib.reload(auth_module)
    topics_module = importlib.reload(topics_module)
    main_module = importlib.reload(main_module)
    discussion_state = {"snapshot_turns": []}

    async def fake_request_json(method, path, *, json_body=None, headers=None, params=None, timeout=600.0):
        if path == "/executor/topics/bootstrap":
            return {"ok": True, "topic_id": json_body["topic_id"]}
        if path == "/executor/discussions":
            await asyncio.sleep(0.3)
            generated_dir = workspace_base / "topics" / json_body["topic_id"] / "shared" / "generated_images"
            generated_dir.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (32, 24), color=(12, 120, 210)).save(generated_dir / "round1.png", format="PNG")
            discussion_state["snapshot_turns"] = [
                {
                    "turn_key": "round1_physicist",
                    "round_num": 1,
                    "expert_name": "physicist",
                    "expert_label": "Physicist",
                    "body": "观点",
                    "updated_at": "2026-03-14T00:00:00+00:00",
                }
            ]
            return {
                "turns_count": 1,
                "cost_usd": 0.01,
                "completed_at": "2026-03-14T00:00:00+00:00",
                "discussion_summary": "总结\n\n![图](../generated_images/round1.png)",
                "discussion_history": "## Round 1 - Physicist\n\n观点",
                "turns": [
                    {
                        "turn_key": "round1_physicist",
                        "round_num": 1,
                        "expert_name": "physicist",
                        "expert_label": "Physicist",
                        "body": "观点",
                        "updated_at": "2026-03-14T00:00:00+00:00",
                    }
                ],
                "generated_images": ["round1.png"],
            }
        if path.endswith("/snapshot"):
            return {
                "topic_id": path.split("/")[-2],
                "turns": discussion_state["snapshot_turns"],
                "turns_count": len(discussion_state["snapshot_turns"]),
                "discussion_history": "## Round 1 - Physicist\n\n观点" if discussion_state["snapshot_turns"] else "",
                "discussion_summary": "",
                "generated_images": [],
            }
        if path == "/executor/expert-replies":
            return {
                "reply_body": "这是专家回复",
                "num_turns": 1,
                "total_cost_usd": 0.001,
            }
        if path.endswith("/experts"):
            return [{"name": "physicist", "label": "Physicist", "description": "", "source": "preset"}]
        if path.endswith("/moderator-mode"):
            return {
                "mode_id": "standard",
                "num_rounds": 5,
                "custom_prompt": None,
                "skill_list": ["image_generation"],
                "mcp_server_ids": [],
                "model": None,
            }
        return {}

    monkeypatch.setattr(topics_module, "request_json", fake_request_json)

    from fastapi.testclient import TestClient

    with TestClient(main_module.app) as test_client:
        test_client.app.state.workspace_base = workspace_base
        yield test_client

    postgres_client.reset_db_state()


def test_topic_create_list_and_posts(client):
    create = client.post("/topics", json={"title": "话题A", "body": "正文"})
    assert create.status_code == 201, create.text
    topic = create.json()
    topic_id = topic["id"]
    topic_workspace = client.app.state.workspace_base / "topics" / topic_id
    assert not topic_workspace.exists()

    list_resp = client.get("/topics")
    assert list_resp.status_code == 200
    assert any(item["id"] == topic_id for item in list_resp.json())

    post_resp = client.post(f"/topics/{topic_id}/posts", json={"author": "alice", "body": "第一条"})
    assert post_resp.status_code == 201
    assert not topic_workspace.exists()
    listed_posts = client.get(f"/topics/{topic_id}/posts")
    assert listed_posts.status_code == 200
    assert listed_posts.json()[0]["body"] == "第一条"


def test_discussion_and_mention_complete_via_executor(client):
    topic = client.post("/topics", json={"title": "执行测试", "body": "验证异步任务"}).json()
    topic_id = topic["id"]

    mention = client.post(
        f"/topics/{topic_id}/posts/mention",
        json={"author": "alice", "body": "@physicist 请回答", "expert_name": "physicist"},
    )
    assert mention.status_code == 202, mention.text
    reply_id = mention.json()["reply_post_id"]

    deadline = time.time() + 3
    latest = None
    while time.time() < deadline:
        latest = client.get(f"/topics/{topic_id}/posts/mention/{reply_id}")
        assert latest.status_code == 200
        if latest.json()["status"] == "completed":
            break
        time.sleep(0.1)
    assert latest is not None
    assert latest.json()["body"] == "这是专家回复"

    start = client.post(
        f"/topics/{topic_id}/discussion",
        json={"num_rounds": 1, "max_turns": 20, "max_budget_usd": 1.0},
    )
    assert start.status_code == 202

    deadline = time.time() + 3
    latest_status = None
    while time.time() < deadline:
        latest_status = client.get(f"/topics/{topic_id}/discussion/status")
        assert latest_status.status_code == 200
        if latest_status.json()["status"] == "completed":
            break
        time.sleep(0.1)
    assert latest_status is not None
    assert latest_status.json()["result"]["discussion_summary"].startswith("总结")


def test_discussion_status_syncs_running_turns_into_database(client):
    topic = client.post("/topics", json={"title": "实时状态", "body": "观察进行中 turn"}).json()
    topic_id = topic["id"]

    start = client.post(
        f"/topics/{topic_id}/discussion",
        json={"num_rounds": 1, "max_turns": 20, "max_budget_usd": 1.0},
    )
    assert start.status_code == 202

    deadline = time.time() + 3
    running_status = None
    while time.time() < deadline:
        running_status = client.get(f"/topics/{topic_id}/discussion/status")
        assert running_status.status_code == 200
        payload = running_status.json()
        if payload["status"] == "running" and payload["result"]["turns_count"] >= 1:
            break
        time.sleep(0.05)

    assert running_status is not None
    payload = running_status.json()
    assert payload["status"] in {"running", "completed"}
    assert payload["result"]["turns_count"] >= 1
    if payload["status"] == "running":
        assert payload["progress"]["completed_turns"] >= 1
        assert payload["progress"]["current_round"] == 1
        assert payload["progress"]["latest_speaker"] == "Physicist"


def test_topic_detail_related_proxy_bootstraps_workspace_on_demand(client):
    topic = client.post("/topics", json={"title": "旧话题", "body": "无 workspace"}).json()
    topic_id = topic["id"]

    experts = client.get(f"/topics/{topic_id}/experts")
    assert experts.status_code == 200, experts.text
    assert experts.json()[0]["name"] == "physicist"

    mode = client.get(f"/topics/{topic_id}/moderator-mode")
    assert mode.status_code == 200, mode.text
    assert mode.json()["mode_id"] == "standard"


def test_discussion_generated_image_is_served_from_database_after_workspace_file_removed(client):
    topic = client.post("/topics", json={"title": "图片入库", "body": "验证图片"}).json()
    topic_id = topic["id"]

    start = client.post(
        f"/topics/{topic_id}/discussion",
        json={"num_rounds": 1, "max_turns": 20, "max_budget_usd": 1.0},
    )
    assert start.status_code == 202

    deadline = time.time() + 3
    latest_status = None
    while time.time() < deadline:
        latest_status = client.get(f"/topics/{topic_id}/discussion/status")
        assert latest_status.status_code == 200
        if latest_status.json()["status"] == "completed":
            break
        time.sleep(0.1)
    assert latest_status is not None
    assert latest_status.json()["result"]["discussion_summary"]
    generated_path = client.app.state.workspace_base / "topics" / topic_id / "shared" / "generated_images" / "round1.png"
    assert generated_path.exists()
    generated_path.unlink()

    image = client.get(f"/topics/{topic_id}/assets/generated_images/round1.png")
    assert image.status_code == 200, image.text
    assert image.headers["content-type"] == "image/webp"
    assert image.content

    preview = client.get(f"/topics/{topic_id}/assets/generated_images/round1.png?w=16&h=16&q=80")
    assert preview.status_code == 200, preview.text
    assert preview.headers["content-type"] == "image/webp"
    assert preview.content
