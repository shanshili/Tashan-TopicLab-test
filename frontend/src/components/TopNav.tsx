import { useState, useEffect, useCallback, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { createPortal } from 'react-dom'
import { refreshCurrentUserProfile, tokenManager, User } from '../api/auth'

const navLinks = [
  { to: '/', label: '话题列表', match: (path: string) => path === '/' && !path.startsWith('/topics') && !path.startsWith('/source-feed') && !path.startsWith('/library') && !path.startsWith('/profile-helper') && !path.startsWith('/agent-links') },
  { to: '/source-feed', label: '信源流', match: (path: string) => path.startsWith('/source-feed') },
  { to: '/library', label: '库', match: (path: string) => path.startsWith('/library') || path.startsWith('/experts') || path.startsWith('/skills') || path.startsWith('/mcp') || path.startsWith('/moderator-modes') },
  { to: '/agent-links', label: 'Agent Link', match: (path: string) => path.startsWith('/agent-links') },
] as const

export default function TopNav() {
  const location = useLocation()
  const navigate = useNavigate()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  const [adminMode, setAdminMode] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [userMenuPosition, setUserMenuPosition] = useState({ top: 0, left: 0 })
  const userMenuTriggerRef = useRef<HTMLButtonElement | null>(null)
  const userMenuRef = useRef<HTMLDivElement | null>(null)

  const loadUser = useCallback(async () => {
    const token = tokenManager.get()
    if (token) {
      const latestUser = await refreshCurrentUserProfile()
      if (latestUser) {
        setUser(latestUser)
        setAdminMode(Boolean(latestUser.is_admin))
        return
      }
    }
    const savedUser = tokenManager.getUser()
    if (savedUser && token) {
      setUser(savedUser)
      setAdminMode(Boolean(savedUser.is_admin))
    } else {
      setUser(null)
      setAdminMode(false)
    }
  }, [])

  useEffect(() => {
    void loadUser()
  }, [location.pathname, loadUser])

  useEffect(() => {
    const handleStorageChange = () => { void loadUser() }
    const handleAuthChange = () => { void loadUser() }
    window.addEventListener('storage', handleStorageChange)
    window.addEventListener('auth-change', handleAuthChange)
    return () => {
      window.removeEventListener('storage', handleStorageChange)
      window.removeEventListener('auth-change', handleAuthChange)
    }
  }, [loadUser])

  const updateUserMenuPosition = useCallback(() => {
    const trigger = userMenuTriggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    setUserMenuPosition({
      top: rect.bottom + 8,
      left: rect.right,
    })
  }, [])

  useEffect(() => {
    setUserMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (!userMenuOpen) return
    updateUserMenuPosition()

    const handleWindowChange = () => updateUserMenuPosition()
    const handleClickOutside = (event: MouseEvent) => {
      const target = event.target as Node
      if (
        userMenuRef.current?.contains(target) ||
        userMenuTriggerRef.current?.contains(target)
      ) {
        return
      }
      setUserMenuOpen(false)
    }
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setUserMenuOpen(false)
      }
    }

    window.addEventListener('resize', handleWindowChange)
    window.addEventListener('scroll', handleWindowChange, true)
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleEscape)
    return () => {
      window.removeEventListener('resize', handleWindowChange)
      window.removeEventListener('scroll', handleWindowChange, true)
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleEscape)
    }
  }, [userMenuOpen, updateUserMenuPosition])

  const handleLogout = () => {
    tokenManager.remove()
    tokenManager.clearUser()
    setUser(null)
    setUserMenuOpen(false)
    window.dispatchEvent(new CustomEvent('auth-change'))
    navigate('/')
  }

  const linkClass = (isActive: boolean) =>
    `text-sm font-serif transition-all block py-2 ${
      isActive ? 'text-black font-medium' : 'text-gray-500 hover:text-black'
    }`

  const hideNav = location.pathname === '/login' || location.pathname === '/register'

  if (hideNav) {
    return null
  }

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 w-full bg-white border-b border-gray-200 safe-area-inset-top overflow-x-hidden">
      {adminMode && location.pathname === '/' ? (
        <div className="w-full bg-red-600 px-4 py-2 text-center text-xs font-medium tracking-[0.18em] text-white">
          ADMIN MODE
        </div>
      ) : null}
      <div className="w-full max-w-6xl mx-auto px-4 sm:px-6 h-14 flex items-center justify-between min-w-0">
        <Link to="/" className="flex items-center gap-2 min-w-0 shrink" onClick={() => setMobileMenuOpen(false)}>
          <span className="text-black font-serif font-bold text-base tracking-tight truncate">Topic Lab</span>
        </Link>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-6 lg:gap-8">
          {navLinks.map(({ to, label, match }) => (
            <Link
              key={to}
              to={to}
              className={linkClass(match(location.pathname)).replace(' block py-2', '')}
            >
              {label}
            </Link>
          ))}
          <Link
            to="/profile-helper"
            className={`text-sm font-serif font-medium transition-all whitespace-nowrap ${
              location.pathname.startsWith('/profile-helper')
                ? 'text-black font-medium'
                : 'text-gray-500 hover:text-black'
            }`}
          >
            科研数字分身
          </Link>
          <Link
            to="/topics/new"
            className="bg-black text-white px-4 py-1.5 rounded-lg text-sm font-serif font-medium transition-all hover:bg-gray-900 whitespace-nowrap shrink-0"
            onClick={() => setMobileMenuOpen(false)}
          >
            + 创建话题
          </Link>

          {/* User Menu */}
          {user ? (
            <div>
              <button
                ref={userMenuTriggerRef}
                type="button"
                onClick={() => {
                  setUserMenuOpen(v => {
                    const next = !v
                    if (next) {
                      requestAnimationFrame(updateUserMenuPosition)
                    }
                    return next
                  })
                }}
                className="flex items-center gap-2 text-sm font-serif text-gray-600 hover:text-black"
              >
                <div className="w-6 h-6 rounded-full bg-gray-200 flex items-center justify-center text-xs font-medium">
                  {(user.username || user.phone).charAt(0)}
                </div>
                <span className="max-w-[100px] truncate">{user.username || user.phone}</span>
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <Link
                to="/login"
                className="text-sm font-serif text-gray-600 hover:text-black"
              >
                登录
              </Link>
              <Link
                to="/register"
                className="bg-gray-100 text-black px-3 py-1.5 rounded-lg text-sm font-serif font-medium hover:bg-gray-200 whitespace-nowrap"
              >
                注册
              </Link>
            </div>
          )}
        </div>

        {/* Mobile */}
        <div className="flex md:hidden items-center gap-2 shrink-0">
          <Link
            to="/profile-helper"
            className="text-sm font-serif font-medium text-gray-600 hover:text-black px-3 py-1.5"
            onClick={() => setMobileMenuOpen(false)}
          >
            科研数字分身
          </Link>
          <Link
            to="/topics/new"
            className="bg-black text-white px-3 py-1.5 rounded-lg text-sm font-serif font-medium transition-all hover:bg-gray-900 shrink-0"
            onClick={() => setMobileMenuOpen(false)}
          >
            + 创建话题
          </Link>
          <button
            type="button"
            onClick={() => setMobileMenuOpen(v => !v)}
            className="p-2 -mr-2 rounded-lg text-gray-600 hover:text-black hover:bg-gray-100 touch-manipulation"
            aria-label={mobileMenuOpen ? '关闭菜单' : '打开菜单'}
            aria-expanded={mobileMenuOpen}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {mobileMenuOpen ? (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              ) : (
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              )}
            </svg>
          </button>
        </div>
      </div>

      {/* Mobile dropdown menu */}
      {mobileMenuOpen && (
        <div className="md:hidden border-t border-gray-100 bg-white">
          <div className="px-4 py-3 space-y-0">
            <Link
              to="/profile-helper"
              className={linkClass(location.pathname.startsWith('/profile-helper'))}
              onClick={() => setMobileMenuOpen(false)}
            >
              科研数字分身
            </Link>
            {navLinks.map(({ to, label, match }) => (
              <Link
                key={to}
                to={to}
                className={linkClass(match(location.pathname))}
                onClick={() => setMobileMenuOpen(false)}
              >
                {label}
              </Link>
            ))}
            {user ? (
              <>
                <div className="border-t border-gray-100 my-2"></div>
                <div className="px-2 py-2 text-sm font-serif text-gray-600">
                  {user.username || user.phone}
                </div>
                <Link
                  to="/favorites"
                  className={linkClass(location.pathname.startsWith('/favorites'))}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  我的收藏
                </Link>
                <button
                  type="button"
                  onClick={() => { handleLogout(); setMobileMenuOpen(false); }}
                  className="block w-full text-left px-2 py-2 text-sm font-serif text-gray-600 hover:text-black"
                >
                  退出登录
                </button>
              </>
            ) : (
              <>
                <div className="border-t border-gray-100 my-2"></div>
                <Link
                  to="/login"
                  className={linkClass(location.pathname === '/login')}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  登录
                </Link>
                <Link
                  to="/register"
                  className={linkClass(location.pathname === '/register')}
                  onClick={() => setMobileMenuOpen(false)}
                >
                  注册
                </Link>
              </>
            )}
          </div>
        </div>
      )}
      {userMenuOpen &&
        createPortal(
          <div
            ref={userMenuRef}
            className="fixed bg-white border border-gray-200 rounded-lg shadow-xl ring-1 ring-black/5 py-1 min-w-[120px] z-[9999]"
            style={{
              top: `${userMenuPosition.top}px`,
              left: `${userMenuPosition.left}px`,
              transform: 'translateX(-100%)',
            }}
          >
            <Link
              to="/favorites"
              className="block px-4 py-2 text-sm font-serif text-gray-600 hover:bg-gray-50 hover:text-black"
              onClick={() => setUserMenuOpen(false)}
            >
              我的收藏
            </Link>
            <Link
              to="/profile-helper"
              className="block px-4 py-2 text-sm font-serif text-gray-600 hover:bg-gray-50 hover:text-black"
              onClick={() => setUserMenuOpen(false)}
            >
              数字分身
            </Link>
            <button
              type="button"
              onClick={handleLogout}
              className="block w-full text-left px-4 py-2 text-sm font-serif text-gray-600 hover:bg-gray-50 hover:text-black"
            >
              退出登录
            </button>
          </div>,
          document.body,
        )}
    </nav>
  )
}
