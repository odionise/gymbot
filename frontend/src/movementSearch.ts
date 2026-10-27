import type { Movement } from './types'

export const normalizeMovementSearch = (value: string) => value.trim().toLocaleLowerCase('ru-RU').replaceAll('ё', 'е')

export function filterMovements(movements: Movement[], muscle: string, search: string): Movement[] {
  const query = normalizeMovementSearch(search)
  return movements.filter(item =>
    (muscle === 'all' || item.primary_group === muscle || muscle === `kind:${item.kind}`) &&
    (query.length < 3 || normalizeMovementSearch(item.name).includes(query))
  ).sort((a, b) => a.name.localeCompare(b.name, 'ru-RU'))
}
