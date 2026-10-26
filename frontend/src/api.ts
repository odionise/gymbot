import type { ExerciseInput, Me, Progress, Template, WorkoutSession } from './types'

declare global {
  interface Window {
    Telegram?: { WebApp?: { initData: string; ready: () => void; expand: () => void; setHeaderColor?: (color: string) => void; setBackgroundColor?: (color: string) => void; themeParams?: Record<string, string> } }
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const initData = window.Telegram?.WebApp?.initData
  const devId = import.meta.env.VITE_DEV_TELEGRAM_ID
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  if (initData) headers.Authorization = `tma ${initData}`
  else if (devId) headers['X-Dev-User-Id'] = devId
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string> | undefined) },
  })
  if (!response.ok) {
    let message = `Ошибка ${response.status}`
    try {
      const body = await response.json()
      message = typeof body.detail === 'string' ? body.detail : message
    } catch { /* no JSON response */ }
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

const json = (value: unknown) => JSON.stringify(value)

export const api = {
  me: () => request<Me>('/me'),
  updateMe: (timezone: string) => request<Me>('/me', { method: 'PATCH', body: json({ timezone }) }),
  templates: () => request<Template[]>('/templates'),
  createTemplate: (data: { name: string; muscle_group: string; weekday: number; send_time: string }) =>
    request<Template>('/templates', { method: 'POST', body: json(data) }),
  updateTemplate: (id: string, data: { name: string; muscle_group: string; weekday: number; send_time: string }) =>
    request<Template>(`/templates/${id}`, { method: 'PUT', body: json(data) }),
  deleteTemplate: (id: string) => request(`/templates/${id}`, { method: 'DELETE' }),
  createExercise: (templateId: string, data: ExerciseInput) =>
    request(`/templates/${templateId}/exercises`, { method: 'POST', body: json(data) }),
  updateExercise: (id: string, data: ExerciseInput) =>
    request(`/exercises/${id}`, { method: 'PUT', body: json(data) }),
  deleteExercise: (id: string) => request(`/exercises/${id}`, { method: 'DELETE' }),
  today: () => request<WorkoutSession[]>('/sessions/today'),
  start: (id: string) => request<WorkoutSession>(`/templates/${id}/start`, { method: 'POST' }),
  session: (id: string) => request<WorkoutSession>(`/sessions/${id}`),
  history: () => request<WorkoutSession[]>('/sessions'),
  override: (id: string, target_weight: number, target_reps: number) =>
    request<WorkoutSession>(`/session-exercises/${id}/target`, { method: 'PATCH', body: json({ target_weight, target_reps }) }),
  saveSet: (id: string, index: number, weight: number, reps: number) =>
    request<WorkoutSession>(`/session-exercises/${id}/sets/${index}`, { method: 'PUT', body: json({ weight, reps }) }),
  deleteSet: (id: string, index: number) => request<WorkoutSession>(`/session-exercises/${id}/sets/${index}`, { method: 'DELETE' }),
  skip: (id: string, skipped: boolean) =>
    request<WorkoutSession>(`/session-exercises/${id}/skip`, { method: 'PATCH', body: json({ skipped }) }),
  complete: (id: string) => request<WorkoutSession>(`/sessions/${id}/complete`, { method: 'POST' }),
  progress: () => request<Progress>('/progress'),
}
