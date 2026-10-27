export type Phase = 'light' | 'medium' | 'heavy' | 'accumulation' | 'deload'

export interface Movement {
  id: string; name: string; primary_group: string; secondary_groups: string[]; is_anchor: boolean
}

export interface MuscleTarget { min_sets: number; max_sets: number; cap_sets: number }

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
  movement_id: string | null
  rep_min: number
  rep_max: number
  rir_target: number
}

export type ExerciseInput = Omit<Exercise, 'id'>

export interface Template {
  id: string
  name: string
  muscle_group: string
  weekday: number
  send_time: string
  exercises: Exercise[]
}

export interface SetResult {
  set_index: number
  weight: number
  reps: number
  rir_reported: number | null
  rir_target: number | null
  is_working: boolean
  is_hard_set: boolean
}

export interface SessionExercise {
  id: string
  exercise_id: string
  name: string
  position: number
  sets_count: number
  weight_step: number
  target_weight: number
  target_reps: number
  min_reps: number
  max_reps: number
  skipped: boolean
  movement_id: string | null
  primary_group: string | null
  secondary_groups: string[]
  is_anchor: boolean
  target_rir: number | null
  action_label: string | null
  next_set: { set_index: number; weight: number; reps: number; rir_target: number; reason: string } | null
  results: SetResult[]
}

export interface WorkoutSession {
  id: string
  template_id: string
  template_name: string
  muscle_group: string
  scheduled_date: string
  actual_date: string | null
  phase: Phase
  phase_type: 'accumulation' | 'deload' | null
  week_id: string | null
  week_start: string | null
  week_number: number | null
  deload_reason: 'scheduled' | 'auto' | 'manual' | null
  feeling_beat_up: boolean
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
  weeks: { week_start: string; group: string; phase: string; deload_reason: string | null; hard_sets: number; working_sets: number; tonnage: number; avg_rir: number | null; avg_reps_hard: number | null; target_low: number; target_high: number; missed_deload: boolean }[]
  signals: string[]
}

export interface Me {
  telegram_id: number
  timezone: string
  volume_cap: number
  has_started_bot: boolean
}
