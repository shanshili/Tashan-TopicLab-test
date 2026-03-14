import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import TopicList from '../TopicList'
import { topicsApi } from '../../api/client'

vi.mock('../../components/OpenClawSkillCard', () => ({
  default: () => <section data-testid="openclaw-skill-card" />,
}))

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    topicsApi: {
      ...actual.topicsApi,
      list: vi.fn(),
      delete: vi.fn(),
    },
  }
})

const mockedTopicsApiList = vi.mocked(topicsApi.list)
const mockedTopicsApiDelete = vi.mocked(topicsApi.delete)

describe('TopicList', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockedTopicsApiList.mockResolvedValue({
      data: [
        {
          id: 'topic-1',
          session_id: 'topic-1',
          category: 'research',
          title: '带图片的话题',
          body: '正文中没有图片',
          status: 'open',
          discussion_status: 'completed',
          preview_image: '../generated_images/list_preview.png',
          creator_name: 'openclaw-user',
          creator_auth_type: 'openclaw_key',
          created_at: '2026-03-12T00:00:00Z',
          updated_at: '2026-03-12T00:00:00Z',
        },
      ],
    } as any)
  })

  it('renders one topic preview image when topic contains image markdown', async () => {
    render(
      <MemoryRouter>
        <TopicList />
      </MemoryRouter>,
    )

    const image = await screen.findByRole('img', { name: '带图片的话题 预览图' })
    expect(screen.getByTestId('openclaw-skill-card')).toBeInTheDocument()
    expect(screen.getByText('板块：科研')).toBeInTheDocument()
    expect(screen.getByText('发起人：openclaw-user · OpenClaw')).toBeInTheDocument()
    expect(screen.getByText('AI 话题讨论')).toBeInTheDocument()
    expect(screen.queryByTestId('status-badge')).not.toBeInTheDocument()
    expect(image.getAttribute('src')).toMatch(
      /\/api\/topics\/topic-1\/assets\/generated_images\/list_preview\.png\?w=128&h=128&q=72&fm=webp$/,
    )
  })

  it('filters topics by selected category', async () => {
    render(
      <MemoryRouter>
        <TopicList />
      </MemoryRouter>,
    )

    fireEvent.click((await screen.findAllByRole('button', { name: '思考' }))[0])

    await waitFor(() => {
      expect(mockedTopicsApiList).toHaveBeenLastCalledWith({ category: 'thought' })
    })
  })

  it('shows delete action in admin mode and deletes topic', async () => {
    mockedTopicsApiDelete.mockResolvedValue({ data: { ok: true, topic_id: 'topic-1' } } as any)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    localStorage.setItem('auth_token', 'jwt-token')
    localStorage.setItem('auth_user', JSON.stringify({
      id: 1,
      phone: '13800000001',
      username: 'admin',
      is_admin: true,
      created_at: '2026-03-12T00:00:00Z',
    }))

    render(
      <MemoryRouter>
        <TopicList />
      </MemoryRouter>,
    )

    fireEvent.click(await screen.findByRole('button', { name: '删除话题' }))

    await waitFor(() => {
      expect(mockedTopicsApiDelete).toHaveBeenCalledWith('topic-1')
    })
  })
})
