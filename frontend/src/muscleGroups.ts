export const muscleGroups = ['Грудь', 'Спина', 'Плечи', 'Руки', 'Ноги'] as const

export function parseMuscleGroups(value: string): string[] {
  return [...new Set(value.split(',').map(item => item.trim()).filter(Boolean))]
}
