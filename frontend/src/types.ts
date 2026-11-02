export type Phase = 'light' | 'medium' | 'heavy' | 'accumulation' | 'deload'

export interface Movement {
  id: string; name: string; kind: 'strength' | 'cardio' | 'stretch' | 'other_timed'; primary_group: string; secondary_groups: string[]; is_anchor: boolean; is_used: boolean
}

export type MovementInput = Omit<Movement, 'id' | 'is_used'>

export interface MuscleTarget { min_sets: number; max_sets: number; cap_sets: number }

export interface Exercise {
  id: string
  readonly slot_id: string
  readonly history_id: string
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
  /** Legacy setting; the workout target is chosen by phase and reentry. */
  rir_target: number | null
  duration_minutes: number | null
}

export type ExerciseInput = Omit<Exercise, 'id' | 'slot_id' | 'history_id' | 'rir_target'>

export interface ExerciseHistoryOption {
  history_id: string
  name: string
  kind: Movement['kind']
  completed_sessions: number
  last_completed_date: string | null
  last_result: { weight: number | null; reps: number | null; duration_minutes: number | null } | null
}

export interface ExerciseHistoryOptions {
  movement_id: string
  options: ExerciseHistoryOption[]
  excluded_legacy: boolean
}

export interface ReplacementInput {
  movement_id: string
  history_mode: 'new' | 'resume'
  history_id: string | null
  settings: {
    sets_count: number; medium_weight: number; weight_step: number; rep_min: number; rep_max: number
  } | { duration_minutes: number }
}

export interface ReplacementResult {
  exercise: Exercise
  history_mode: ReplacementInput['history_mode']
  effective_from: 'next_new_session'
  preserved_sessions_count: number
}

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

export interface Recommendation {
  version: 1
  rules_version: '2' | null
  created_at?: string
  inputs?: { start_weight: number; weight_step: number; rep_min: number; rep_max: number; base_sets: number }
  history?: {
    session_id: string; session_exercise_id: string; date: string; completed_at: string | null
    base_weight: number; weight_source: 'first_working' | 'planned'; planned_sets: number
    working_sets: { set_index: number; weight: number; reps: number; rir: number | null }[]
  }[]
  weight?: { reason_code: string; reason: string; median: number | null; rounded_base: number; step: number }
  reps?: { reason_code: string; reason: string; median: number | null }
  sets?: {
    reason_code: string; reason: string; base: number; before_limits: number; limited: boolean
    limits: { group: string; cap: number; before: number; after: number }[]
  }
  rir?: { source: 'accumulation' | 'deload' | 'reentry'; reason: string }
  calculated: { weight: number; reps: number; sets_count: number; rir: number } | null
  manual_override: { weight?: number; reps?: number; sets_count?: number } | null
}

export interface SessionExercise {
  id: string
  exercise_id: string
  name: string
  kind: Movement['kind']
  target_duration_minutes: number | null
  actual_duration_minutes: number | null
  position: number
  sets_count: number
  weight_step: number | null
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
  recommendation: Recommendation | null
  next_set: {
    set_index: number; weight: number; reps: number; rir_target: number; reason: string
    basis?: { set_index: number; weight: number; reps: number; rir_reported: number; target_rir: number; weight_step: number; rir_difference: number }
  } | null
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
  exercises: { id: string; history_id: string; slot_id: string; movement_id: string | null; kind: Movement['kind']; name: string; label?: string; group: string; groups: string[]; points: ProgressPoint[] }[]
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

export interface NextWeek { week_start: string; kind: 'deload' | 'vacation' | null }
