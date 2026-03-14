# TopicLab Frontend and Backend Performance Optimizations

This document summarizes the recent performance work in `topiclab-backend` and `frontend`. It explains the current architecture and default behavior, not the full public API surface. The authoritative API contract remains the actual routes plus `topiclab-backend/skill.md`.

## Goals

This optimization round focused on three bottlenecks:

- User interactions should feel immediate even when the database write path is slower.
- Topic lists and post threads should not fetch or mount the full dataset at once.
- Repeated reads of the same topic or post should avoid re-running identical base queries on every request.

The resulting strategy is:

- Maintain interaction counters at write time instead of recomputing them on reads.
- Switch post and favorites reads to paged, on-demand access patterns.
- Separate immediate UI feedback from eventual persistence with optimistic frontend updates.
- Add a short-TTL shared read cache in `topiclab-backend`, but keep viewer-specific state out of that cache.

## Backend Changes

### 1. Write-time interaction counters

The main counters for topics, posts, and source articles are now maintained on write paths instead of being recomputed with read-time `COUNT(*) + GROUP BY` queries.

The primary read-model fields include:

- `likes_count`
- `favorites_count`
- `shares_count`
- `reply_count` / `posts_count`

As a result, endpoints such as:

- `POST /topics/{topic_id}/like`
- `POST /topics/{topic_id}/favorite`
- `POST /topics/{topic_id}/share`
- `POST /topics/{topic_id}/posts/{post_id}/like`
- `POST /source-feed/articles/{article_id}/favorite`

only need to persist the action, update the relevant counters, and return the latest interaction state. They no longer depend on an extra aggregate recount before returning.

### 2. Cursor pagination for topic lists

`GET /topics` now returns a paged structure instead of an unbounded array:

```json
{
  "items": [],
  "next_cursor": "..."
}
```

Supported parameters:

- `category`
- `cursor`
- `limit`

Pagination order is stable:

- `updated_at DESC`
- `id DESC`

The cursor is derived from that ordering so pages remain consistent without duplicates or gaps.

### 3. Top-level post pagination and on-demand replies

Post reads were reshaped from "return the whole thread tree" into a thread-oriented API:

- `GET /topics/{topic_id}/posts`
  - Returns only top-level posts
  - Defaults to `preview_replies=0`
- `GET /topics/{topic_id}/posts/{post_id}/replies`
  - Returns a paged list of direct replies for one post
- `GET /topics/{topic_id}/posts/{post_id}/thread`
  - Returns the full thread only when a complete subtree is explicitly needed
- `POST /topics/{topic_id}/posts`
  - Returns the new `post` and the affected `parent_post` when the request is a reply

Two important defaults changed:

- `bundle.posts` is now the first post page, not the full thread tree
- reply previews are no longer returned by default for every top-level post, which keeps first-page payloads small

### 4. Category-first favorites reads

Favorites reads are now split into lightweight category and page endpoints:

- `GET /api/v1/me/favorite-categories`
  - Returns category metadata and counts only
- `GET /api/v1/me/favorite-categories/{category_id}/items`
  - Returns one page of items for the selected category and item type
- `GET /api/v1/me/favorites/recent`
  - Feeds the "all favorites" view

The older `GET /api/v1/me/favorites` endpoint still exists for compatibility, but it is no longer the primary frontend data source.

Favorite categories also maintain write-time counters:

- `topics_count`
- `source_articles_count`

This avoids the earlier pattern of loading all favorites first and then filtering them in memory for each category view.

### 5. Short-TTL shared read cache

`topiclab-backend` now includes a process-local shared read cache with a 5-second TTL.

It caches the anonymous base read model for:

- topic list pages
- single-topic detail
- top-level post pages
- reply pages
- single-thread reads
- full post base reads used by thread assembly

The rules are:

- only shared anonymous base reads are cached
- viewer-specific fields such as `liked` and `favorited` are added after the cache read
- anonymous requests avoid opening an extra database session just to derive empty viewer state

That means different users can share the same cached topic or post structure while still receiving their own per-user interaction booleans.

### 6. Write-triggered invalidation

To keep the short cache from serving obviously stale data after writes, key write paths explicitly invalidate affected entries.

Covered write paths include:

- topic create, update, delete, and close
- discussion status updates
- create/delete post and replace discussion turns
- topic expert and moderator-mode configuration changes
- topic, post, and source article like/favorite/share operations

Invalidation currently happens at the topic and topic-list level. It intentionally favors correctness and simpler implementation over fine-grained subtree cache invalidation.

### 7. Shared outbound HTTP clients

Cross-service calls to Resonnet and the source-feed bridge now reuse process-level `httpx.AsyncClient` instances.

This does not reduce database reads, but it removes repeated connection setup, TLS handshake, and throwaway client overhead from the request path.

## Frontend Changes

### 1. Immediate UI feedback separated from persistence

The frontend now treats "instant feedback" and "database persistence" as separate stages.

Optimistic updates are used for:

- topic like, favorite, and share
- post like and share
- create post
- create reply
- favorites-page remove/move operations

The normal flow is:

- update the local UI immediately
- send the API request in the background
- roll back locally only if the request fails

This turns "the write path is slow" into "the UI responds now and the backend converges in the background."

### 2. Three-stage topic detail loading

The topic detail page no longer waits for a heavy all-in-one payload before rendering.

The current sequence is:

1. Fetch the topic shell and render the page frame.
2. Fetch the first post page.
3. Fetch experts last.

This makes the page feel faster because:

- the layout appears earlier
- posts are not blocked by expert loading
- discussion and mention polling stays scoped to the UI regions that actually need it

### 3. Infinite scrolling for topic lists

Topic lists now use:

- first-page-only initial fetch
- automatic next-page loading near the viewport bottom
- a fallback "load more" button

Category switches use a reset-and-refetch model:

- clear the current list
- reset the cursor
- load page one for the next category

Scroll position is not preserved across categories in this iteration.

### 4. Incremental mounting after data is already loaded

Pagination alone does not solve browser-side stalls. Even with the data already in memory, mounting too many cards or posts at once can block the main thread.

To address that, the frontend now incrementally mounts:

- topic cards
- thread entries

This specifically targets browser render cost rather than database or network cost.

### 5. Progressive post-body rendering

`PostThread` no longer upgrades every visible post into full `ReactMarkdown` immediately.

The current behavior is:

- render a plain-text summary first
- upgrade to Markdown when the post enters the viewport or the user interacts with it
- delay heavy images and math rendering until the Markdown upgrade happens

This reduces the common case where the API response has already arrived but the browser is still busy constructing large Markdown trees.

## Current Frontend and API Contract

After these optimizations, the default collaboration model between frontend and backend is:

### Topic lists

- use `GET /topics?cursor=...&limit=...`
- expect a `TopicListPage` response
- append `items` client-side
- treat `next_cursor = null` as the end of the list

### Topic detail

- do not depend on `bundle` for the first page shell
- treat `bundle.posts` as a lightweight first page
- load experts after the topic shell and first post page

### Post threads

- fetch only the first page of top-level posts initially
- show "view N replies" when replies exist
- fetch replies only after the user expands a thread
- do not expect reply previews on every top-level post by default

### Favorites

- load favorite categories first
- load only one page for the active panel
- refetch only the current category and type when the user switches tabs

## Benefits and Current Limits

### Benefits already achieved

- Likes, favorites, and posting feel much faster because the UI responds immediately.
- Topic lists and post areas no longer load or mount the full dataset in one shot.
- Repeated short-interval reads of the same topic or post now reuse cached base reads in the backend.
- Post Markdown rendering moved from eager full-page work to staged, on-demand upgrades.

### Current limits

- The read cache is still in-process memory, not Redis.
- Multi-instance deployments do not share that cache or its invalidations.
- Large threads use progressive mounting, but not a full virtualized list yet.
- Heavy images, complex Markdown, and math content can still dominate browser render cost.

## Recommended Next Steps

If further production-grade optimization is needed, the recommended order is:

1. Move the short-TTL cache to Redis for cross-instance sharing.
2. Introduce true virtualization for long thread rendering.
3. Add more aggressive image lazy loading and stable placeholders for topic cards and Markdown content.
4. Add endpoint-level observability that separates `db_time`, `upstream_time`, `serialize_time`, and `total_time`.
5. Move counter backfills and schema evolution into explicit migrations rather than relying only on initialization paths.

## Verification

The recent optimization work has been validated with:

- `npm --prefix frontend run build`
- `PYTHONPATH=. uv run --with-editable . --with pytest pytest tests/test_topics_api.py -q`

The current regression coverage includes:

- topic list cursor pagination
- posts defaulting to no reply preview
- favorites category paging endpoints
- short-TTL cache hits and write-triggered invalidation
