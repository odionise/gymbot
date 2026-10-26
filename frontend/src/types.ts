export type Phase = 'light' | 'medium' | 'heavy'

export interface Exercise {
  id: string
  name: string
  position: number
  sets_count: number
  medium_weight: number
  weight_step: number
  light_factor: number
  heavy_factor: number
  light_min: number
  light_max: number
  medium_min: number
  medium_max: number
  heavy_min: number
  heavy_max: number
}

export type ExerciseInput = Omit<Exercise, 'id'>

export interface Template {
  id: string
  name: string
  muscle_group: string
  weekday: number
  send_time: string
  next_phase: Phase
  exercises: Exercise[]
}

export interface SetResult {
  set_index: number
  weight: number
  reps: number
}

export interface SessionExercise {
  id: string
  exercise_id: string
  name: string
  position: number
  sets_count: number
  target_weight: number
  target_reps: number
  min_reps: number
  max_reps: number
  skipped: boolean
  results: SetResult[]
}

export interface WorkoutSession {
  id: string
  template_id: string
  template_name: string
  muscle_group: string
  scheduled_date: string
  phase: Phase
  status: 'planned' | 'in_progress' | 'completed'
  completed_at: string | null
  exercises: SessionExercise[]
}

export interface ProgressPoint {
  name: string
  group: string
  groups: string[]
  date: string
  phase: Phase
  weight: number
  reps: number
  volume: number
  estimated_strength: number | null
}

export interface Progress {
  exercises: { id: string; name: string; group: string; groups: string[]; points: ProgressPoint[] }[]
  groups: { group: string; cycle_volume: number; strength_change_percent: number | null; sessions: number }[]
}

export interface Me {
  telegram_id: number
  timezone: string
  has_started_bot: boolean
}
