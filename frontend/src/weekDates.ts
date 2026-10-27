const date = (day: string) => new Date(`${day}T12:00:00Z`)
const month = (day: Date) => new Intl.DateTimeFormat('ru-RU', { month: 'short', timeZone: 'UTC' }).format(day)

export function weekStart(day: string): string {
  const value = date(day)
  value.setUTCDate(value.getUTCDate() - (value.getUTCDay() + 6) % 7)
  return value.toISOString().slice(0, 10)
}

export function weekRange(start: string): string {
  const first = date(weekStart(start))
  const last = date(weekStart(start))
  last.setUTCDate(last.getUTCDate() + 6)
  const sameMonth = first.getUTCMonth() === last.getUTCMonth() && first.getUTCFullYear() === last.getUTCFullYear()
  return sameMonth
    ? `${first.getUTCDate()}–${last.getUTCDate()} ${month(last)}`
    : `${first.getUTCDate()} ${month(first)}–${last.getUTCDate()} ${month(last)}`
}

export function weekRangeLines(start: string): [string, string] {
  const first = date(weekStart(start))
  const last = date(weekStart(start))
  last.setUTCDate(last.getUTCDate() + 6)
  const sameMonth = first.getUTCMonth() === last.getUTCMonth() && first.getUTCFullYear() === last.getUTCFullYear()
  return sameMonth
    ? [`${first.getUTCDate()}–${last.getUTCDate()}`, month(last)]
    : [`${first.getUTCDate()} ${month(first)}–`, `${last.getUTCDate()} ${month(last)}`]
}
