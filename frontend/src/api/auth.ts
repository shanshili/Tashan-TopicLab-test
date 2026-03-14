/** Auth API client */

const API_BASE = import.meta.env.BASE_URL ? `${import.meta.env.BASE_URL}api` : '/api';

export interface User {
  id: number;
  phone: string;
  username: string | null;
  is_admin?: boolean;
  created_at: string;
}

export interface MeResponse {
  user: User;
  auth_type?: string;
}

export interface AuthResponse {
  message: string;
  user: User;
  token?: string;
}

export interface SendCodeResponse {
  message: string;
  dev_code?: string;
}

export interface DigitalTwinRecord {
  agent_name: string;
  display_name: string | null;
  expert_name: string | null;
  visibility: 'private' | 'public' | string;
  exposure: 'brief' | 'full' | string;
  session_id: string | null;
  source: string | null;
  created_at: string | null;
  updated_at: string | null;
  has_role_content?: boolean;
}

export interface DigitalTwinDetail extends DigitalTwinRecord {
  role_content: string | null;
}

export interface OpenClawKeyInfo {
  has_key: boolean;
  key?: string | null;
  masked_key?: string | null;
  created_at?: string | null;
  last_used_at?: string | null;
  skill_path?: string | null;
}

export const authApi = {
  sendCode: async (phone: string, type: 'register' | 'login' | 'reset_password' = 'register'): Promise<SendCodeResponse> => {
    const res = await fetch(`${API_BASE}/auth/send-code`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, type }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '发送验证码失败');
    }
    return res.json();
  },

  register: async (phone: string, code: string, password: string, username: string): Promise<AuthResponse> => {
    const res = await fetch(`${API_BASE}/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, code, password, username }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '注册失败');
    }
    return res.json();
  },

  login: async (phone: string, password: string): Promise<AuthResponse> => {
    const res = await fetch(`${API_BASE}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ phone, password }),
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '登录失败');
    }
    return res.json();
  },

  getMe: async (token: string): Promise<MeResponse> => {
    const res = await fetch(`${API_BASE}/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '获取用户信息失败');
    }
    return res.json();
  },

  getDigitalTwins: async (token: string): Promise<{ digital_twins: DigitalTwinRecord[] }> => {
    const res = await fetch(`${API_BASE}/auth/digital-twins`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '获取分身记录失败');
    }
    return res.json();
  },

  getDigitalTwinDetail: async (token: string, agentName: string): Promise<{ digital_twin: DigitalTwinDetail }> => {
    const res = await fetch(`${API_BASE}/auth/digital-twins/${encodeURIComponent(agentName)}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '获取分身详情失败');
    }
    return res.json();
  },

  getOpenClawKey: async (token: string): Promise<OpenClawKeyInfo> => {
    const res = await fetch(`${API_BASE}/auth/openclaw-key`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '获取 OpenClaw Key 失败');
    }
    return res.json();
  },

  createOpenClawKey: async (token: string): Promise<OpenClawKeyInfo> => {
    const res = await fetch(`${API_BASE}/auth/openclaw-key`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) {
      const data = await res.json();
      throw new Error(data.detail || '生成 OpenClaw Key 失败');
    }
    return res.json();
  },
};

export const tokenManager = {
  get: (): string | null => localStorage.getItem('auth_token'),
  set: (token: string) => localStorage.setItem('auth_token', token),
  remove: () => localStorage.removeItem('auth_token'),
  getUser: (): User | null => {
    const user = localStorage.getItem('auth_user');
    return user ? JSON.parse(user) : null;
  },
  setUser: (user: User) => localStorage.setItem('auth_user', JSON.stringify(user)),
  clearUser: () => localStorage.removeItem('auth_user'),
};

export async function refreshCurrentUserProfile(): Promise<User | null> {
  const token = tokenManager.get()
  if (!token) {
    tokenManager.clearUser()
    return null
  }

  try {
    const me = await authApi.getMe(token)
    tokenManager.setUser(me.user)
    return me.user
  } catch {
    return tokenManager.getUser()
  }
}
