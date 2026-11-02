import { formatWeight } from './App'
import type { SessionExercise } from './types'

function dateLabel(value: string) {
  const date = new Date(`${value}T12:00:00Z`)
  return Number.isNaN(date.getTime()) ? 'Дата неизвестна'
    : new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(date)
}

export function RecommendationDetails({ item }: { item: SessionExercise }) {
  const context = item.recommendation
  const calculated = context?.calculated
  const manual = context?.manual_override
  const hasManual = Boolean(manual && Object.keys(manual).length)
  return <details className="recommendationDetails">
    <summary>Почему такой план?</summary>
    {calculated ? <>
      <p><strong>Расчёт сохранённого плана:</strong> {formatWeight(calculated.weight)} кг · {calculated.sets_count} × {calculated.reps} · целевой ПДО {formatWeight(calculated.rir)}.</p>
      {context.weight && <p><strong>Вес.</strong> {context.weight.reason}{context.weight.median !== null && <> Медиана: {formatWeight(context.weight.median)} кг; база после округления: {formatWeight(context.weight.rounded_base)} кг.</>} Шаг: {formatWeight(context.weight.step)} кг.</p>}
      {context.reps && <p><strong>Повторы.</strong> {context.reps.reason}{context.reps.median !== null && <> Медиана рабочих повторов последнего занятия: {formatWeight(context.reps.median)}.</>}</p>}
      {context.sets && <><p><strong>Подходы.</strong> {context.sets.reason} Базовая настройка: {context.sets.base}; до ограничений: {context.sets.before_limits}.{context.sets.limited && ' Количество уменьшено с учётом ограничений по мышцам.'}</p>
        {context.sets.limits.length > 0 && <ul>{context.sets.limits.map(limit => <li key={limit.group}>{limit.group}: предел {formatWeight(limit.cap)} подходов; недельный объём {formatWeight(limit.before)} → {formatWeight(limit.after)}.</li>)}</ul>}</>}
      {context.rir && <p><strong>Целевой ПДО.</strong> {context.rir.reason}</p>}
      {context.inputs && <p>Стартовая настройка: {formatWeight(context.inputs.start_weight)} кг; диапазон {context.inputs.rep_min}–{context.inputs.rep_max} повторов.</p>}
      {context.history?.length ? <>
        <p><strong>Использованная история</strong> — сохранённые данные на момент расчёта, от последнего занятия к более ранним:</p>
        <ul>{context.history.map(source => <li key={source.session_exercise_id}>
          <strong>{dateLabel(source.date)}</strong>: {source.weight_source === 'first_working' ? 'первый рабочий вес' : 'сохранённый плановый вес'} {formatWeight(source.base_weight)} кг; назначено {source.planned_sets} подходов.
          {source.working_sets.length > 0 ? <ul>{source.working_sets.map(set => <li key={set.set_index}>Подход {set.set_index}: {formatWeight(set.weight)} кг × {set.reps}; ПДО {set.rir === null ? 'неизвестен' : formatWeight(set.rir)}.</li>)}</ul> : <p>Рабочие подходы не записаны; для этого занятия использован плановый вес.</p>}
        </li>)}</ul>
      </> : <p>Подходящей завершённой обычной истории нет; использована стартовая настройка.</p>}
      <p>Детали сохранены вместе с планом. Последующие изменения программы и результатов не пересчитывают это объяснение.</p>
    </> : <p>Подробности расчёта не сохранены. В этом занятии показаны сохранённые цели и результаты.</p>}
    {hasManual && <p><strong>Ручное изменение:</strong> {manual?.weight !== undefined && <>вес {formatWeight(manual.weight)} кг; </>}{manual?.reps !== undefined && <>повторы {manual.reps}; </>}{manual?.sets_count !== undefined && <>подходы {manual.sets_count}; </>}текущая цель — {formatWeight(item.target_weight)} кг · {item.sets_count} × {item.target_reps}. Фактические результаты записываются отдельно.</p>}
  </details>
}

export function NextSetDetails({ item }: { item: SessionExercise }) {
  const suggestion = item.next_set
  if (!suggestion?.basis) return null
  const basis = suggestion.basis
  return <details className="recommendationDetails">
    <summary>Почему такая подсказка следующего подхода?</summary>
    <p>Подход {basis.set_index}: факт {formatWeight(basis.weight)} кг × {basis.reps}, фактический ПДО {formatWeight(basis.rir_reported)}. Целевой ПДО занятия — {formatWeight(basis.target_rir)}; разница — {formatWeight(basis.rir_difference)}. Шаг веса — {formatWeight(basis.weight_step)} кг.</p>
    <p>{suggestion.reason}. Подсказка для подхода {suggestion.set_index}: {formatWeight(suggestion.weight)} кг × {suggestion.reps}. План в заголовке сохраняется.</p>
  </details>
}
