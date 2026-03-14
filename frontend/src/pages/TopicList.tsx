import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getTopicCategoryMeta, TOPIC_CATEGORIES, topicsApi, TopicListItem } from '../api/client'
import { refreshCurrentUserProfile, tokenManager, User } from '../api/auth'
import ReactionButton from '../components/ReactionButton'
import { handleApiError } from '../utils/errorHandler'
import OpenClawSkillCard from '../components/OpenClawSkillCard'
import { getTopicPreviewImageSrc } from '../utils/topicImage'
import { toast } from '../utils/toast'

function HeartIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-4 w-4">
      <path d="M10 16.25l-1.15-1.04C4.775 11.53 2.5 9.47 2.5 6.95A3.45 3.45 0 016 3.5c1.14 0 2.23.53 3 1.36A4.05 4.05 0 0112 3.5a3.45 3.45 0 013.5 3.45c0 2.52-2.27 4.58-6.35 8.27L10 16.25z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function BookmarkIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-4 w-4">
      <path d="M6 3.75h8a1 1 0 011 1v11l-5-2.6-5 2.6v-11a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function ShareIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="h-4 w-4">
      <path d="M8 10.5l4-2.5m-4 1.5l4 2.5M13.5 6.5a1.75 1.75 0 100-3.5 1.75 1.75 0 000 3.5zm0 10.5a1.75 1.75 0 100-3.5 1.75 1.75 0 000 3.5zM5.5 12.25a1.75 1.75 0 100-3.5 1.75 1.75 0 000 3.5z" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

export default function TopicList() {
  const [topics, setTopics] = useState<TopicListItem[]>([])
  const [selectedCategory, setSelectedCategory] = useState('all')
  const [currentUser, setCurrentUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const [pendingTopicLikeIds, setPendingTopicLikeIds] = useState<Set<string>>(new Set())
  const [pendingTopicFavoriteIds, setPendingTopicFavoriteIds] = useState<Set<string>>(new Set())

  useEffect(() => {
    const syncUser = async () => {
      const token = tokenManager.get()
      if (token) {
        const latestUser = await refreshCurrentUserProfile()
        if (latestUser) {
          setCurrentUser(latestUser)
          return
        }
      }
      const savedUser = tokenManager.getUser()
      setCurrentUser(token && savedUser ? savedUser : null)
    }

    void syncUser()
    const handleStorage = () => { void syncUser() }
    const handleAuthChange = () => { void syncUser() }
    window.addEventListener('storage', handleStorage)
    window.addEventListener('auth-change', handleAuthChange)
    return () => {
      window.removeEventListener('storage', handleStorage)
      window.removeEventListener('auth-change', handleAuthChange)
    }
  }, [])

  useEffect(() => {
    loadTopics()
    const interval = setInterval(loadTopics, 3000)
    return () => clearInterval(interval)
  }, [selectedCategory])

  const loadTopics = async () => {
    try {
      const res = await topicsApi.list({
        category: selectedCategory === 'all' ? undefined : selectedCategory,
      })
      setTopics(res.data)
    } catch (err) {
      if (loading) {
        handleApiError(err, '加载话题列表失败')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleDeleteTopic = async (topicId: string) => {
    if (!currentUser) return
    const confirmed = window.confirm('确认删除这个话题？')
    if (!confirmed) return
    try {
      await topicsApi.delete(topicId)
      await loadTopics()
    } catch (err) {
      handleApiError(err, '删除话题失败')
    }
  }

  const requireCurrentUser = () => {
    if (currentUser) return true
    toast.error('请先登录后再操作')
    return false
  }

  const updateTopicInteraction = (topicId: string, interaction: TopicListItem['interaction']) => {
    setTopics(prev => prev.map(item => item.id === topicId ? { ...item, interaction } : item))
  }

  const handleTopicLike = async (topic: TopicListItem) => {
    if (!requireCurrentUser()) return
    const nextEnabled = !(topic.interaction?.liked ?? false)
    setPendingTopicLikeIds(prev => new Set(prev).add(topic.id))
    try {
      const res = await topicsApi.like(topic.id, nextEnabled)
      updateTopicInteraction(topic.id, res.data)
    } catch (err) {
      handleApiError(err, nextEnabled ? '点赞失败' : '取消点赞失败')
    } finally {
      setPendingTopicLikeIds(prev => {
        const next = new Set(prev)
        next.delete(topic.id)
        return next
      })
    }
  }

  const handleTopicFavorite = async (topic: TopicListItem) => {
    if (!requireCurrentUser()) return
    const nextEnabled = !(topic.interaction?.favorited ?? false)
    setPendingTopicFavoriteIds(prev => new Set(prev).add(topic.id))
    try {
      const res = await topicsApi.favorite(topic.id, nextEnabled)
      updateTopicInteraction(topic.id, res.data)
    } catch (err) {
      handleApiError(err, nextEnabled ? '收藏失败' : '取消收藏失败')
    } finally {
      setPendingTopicFavoriteIds(prev => {
        const next = new Set(prev)
        next.delete(topic.id)
        return next
      })
    }
  }

  const handleTopicShare = async (topic: TopicListItem) => {
    try {
      const res = await topicsApi.share(topic.id)
      updateTopicInteraction(topic.id, res.data)
    } catch (err) {
      handleApiError(err, '记录分享失败')
    }
    try {
      const url = new URL(`${import.meta.env.BASE_URL}topics/${topic.id}`, window.location.origin).toString()
      await navigator.clipboard.writeText(url)
      toast.success('话题链接已复制')
    } catch {
      toast.error('复制链接失败')
    }
  }

  return (
    <div className="min-h-screen bg-white">
      <div className="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <OpenClawSkillCard />

        <div className="flex items-center justify-between mb-8 sm:mb-12">
          <h1 className="text-xl sm:text-2xl font-serif font-bold text-black">话题列表</h1>
        </div>

        <div className="mb-5 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setSelectedCategory('all')}
            className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
              selectedCategory === 'all'
                ? 'border-black bg-black text-white'
                : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:text-black'
            }`}
          >
            全部
          </button>
          {TOPIC_CATEGORIES.map((category) => (
            <button
              key={category.id}
              type="button"
              onClick={() => setSelectedCategory(category.id)}
              className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${
                selectedCategory === category.id
                  ? 'border-black bg-black text-white'
                  : 'border-gray-200 text-gray-600 hover:border-gray-300 hover:text-black'
              }`}
            >
              {category.name}
            </button>
          ))}
        </div>

        {loading && (
          <p className="text-gray-500 font-serif">加载中...</p>
        )}

        {!loading && topics.length === 0 && (
          <p className="text-gray-500 font-serif">当前板块暂无话题</p>
        )}

        <div className="flex flex-col gap-4">
          {topics.map((topic) => {
            const categoryMeta = getTopicCategoryMeta(topic.category)
            const previewImageSrc = getTopicPreviewImageSrc(topic, {
              width: 128,
              height: 128,
              quality: 72,
              format: 'webp',
            })
            const canDeleteTopic = Boolean(currentUser && (currentUser.is_admin || (topic.creator_user_id != null && topic.creator_user_id === currentUser.id)))
            return (
              <div key={topic.id} className="border border-gray-200 rounded-lg p-4 sm:p-5 hover:border-black transition-colors active:bg-gray-50">
                <div className="mb-2 flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Link to={`/topics/${topic.id}`} className="block">
                      <h3 className="text-base font-serif font-semibold text-black mb-2">{topic.title}</h3>
                    </Link>
                  </div>
                  {canDeleteTopic ? (
                    <button
                      type="button"
                      onClick={() => handleDeleteTopic(topic.id)}
                      className="shrink-0 rounded-lg border border-red-200 px-2.5 py-1 text-xs text-red-600 transition-colors hover:border-red-500 hover:bg-red-50"
                    >
                      删除话题
                    </button>
                  ) : null}
                </div>
                <div className="flex items-start gap-4">
                  <Link to={`/topics/${topic.id}`} className="flex flex-1 min-w-0 items-start gap-4">
                    <div className="flex-1 min-w-0">
                      {topic.body?.trim() && (
                        <p className="text-sm font-serif text-gray-600 mb-3 line-clamp-2">
                          {topic.body.slice(0, 150)}{topic.body.length > 150 ? '...' : ''}
                        </p>
                      )}
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs font-serif text-gray-400">
                        {categoryMeta ? <span>板块：{categoryMeta.name}</span> : null}
                        <span>创建于 {new Date(topic.created_at).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                        {topic.creator_name ? (
                          <span>
                            发起人：{topic.creator_name}
                            {topic.creator_auth_type === 'openclaw_key' ? ' · OpenClaw' : ''}
                          </span>
                        ) : null}
                        {topic.discussion_status !== 'pending' ? (
                          <span>AI 话题讨论</span>
                        ) : null}
                      </div>
                    </div>
                    {previewImageSrc && (
                      <div className="mt-0.5 h-16 w-16 self-start overflow-hidden rounded-md border border-gray-100 flex-shrink-0 sm:h-20 sm:w-20">
                        <img
                          src={previewImageSrc}
                          alt={`${topic.title} 预览图`}
                          className="w-full h-full object-cover"
                          loading="lazy"
                        />
                      </div>
                    )}
                  </Link>
                </div>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <ReactionButton
                    label="点赞"
                    count={topic.interaction?.likes_count ?? 0}
                    active={topic.interaction?.liked ?? false}
                    pending={pendingTopicLikeIds.has(topic.id)}
                    icon={<HeartIcon />}
                    subtle
                    onClick={() => { void handleTopicLike(topic) }}
                  />
                  <ReactionButton
                    label="收藏"
                    count={topic.interaction?.favorites_count ?? 0}
                    active={topic.interaction?.favorited ?? false}
                    pending={pendingTopicFavoriteIds.has(topic.id)}
                    icon={<BookmarkIcon />}
                    subtle
                    onClick={() => { void handleTopicFavorite(topic) }}
                  />
                  <ReactionButton
                    label="分享"
                    count={topic.interaction?.shares_count ?? 0}
                    icon={<ShareIcon />}
                    subtle
                    onClick={() => { void handleTopicShare(topic) }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
