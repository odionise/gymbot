import { useState } from 'react'
import type { FormEvent } from 'react'
import { api } from './api'
import type { Me } from './types'

export function ProfileForm({ profile, onSaved, onClose }: {
  profile: Me; onSaved: (profile: Me) => void; onClose?: () => void
}) {
  const [step, setStep] = useState(0)
  const [sex, setSex] = useState<'male' | 'female' | ''>(profile.sex ?? '')
  const [name, setName] = useState(profile.display_name ?? '')
  const [birthDate, setBirthDate] = useState(profile.birth_date ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const next = () => {
    if (step === 0 && !sex) return
    if (step === 1 && !name.trim()) return
    setError('')
    setStep(current => Math.min(current + 1, 2))
  }
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (step < 2) { next(); return }
    if (!sex || !name.trim() || !birthDate || busy) return
    setBusy(true); setError('')
    try { onSaved(await api.updateProfile({ sex, display_name: name.trim(), birth_date: birthDate })) }
    catch (cause) { setError((cause as Error).message) }
    finally { setBusy(false) }
  }
  return <section className="profileCard" aria-labelledby="profileTitle">
    <div className="profileProgress"><button type="button" className="profileBack" onClick={() => step ? setStep(step - 1) : onClose?.()} disabled={!step && !onClose} aria-label="Назад">←</button><div className="profileProgressTrack" aria-label={`Шаг ${step + 1} из 3`}><span style={{ width: `${(step + 1) * 100 / 3}%` }} /></div></div>
    <form onSubmit={save}><fieldset className="formFields" disabled={busy}>
      <div className="profileQuestion"><span className="eyebrow">АНКЕТА · {step + 1} / 3</span><h2 id="profileTitle">{step === 0 ? 'Какая схема мышц вам подходит?' : step === 1 ? 'Как к вам обращаться?' : 'Когда вы родились?'}</h2><p>{step === 0 ? 'Покажем подходящую схему на карточке тренировки.' : step === 1 ? 'Это имя увидите только вы в своём профиле.' : 'Возраст считаем по дате рождения. На расчёт нагрузки он не влияет.'}</p></div>
      <div className="profileAnswer">
        {step === 0 && <div className="profileSexChoices"><label className={sex === 'male' ? 'chosen' : ''}><input type="radio" name="sex" value="male" checked={sex === 'male'} onChange={() => setSex('male')} />Мужская</label><label className={sex === 'female' ? 'chosen' : ''}><input type="radio" name="sex" value="female" checked={sex === 'female'} onChange={() => setSex('female')} />Женская</label></div>}
        {step === 1 && <label className="field"><span>Имя</span><input value={name} onChange={event => setName(event.target.value)} maxLength={80} autoComplete="given-name" placeholder="Ваше имя" autoFocus /></label>}
        {step === 2 && <label className="field"><span>Дата рождения</span><input type="date" value={birthDate} onChange={event => setBirthDate(event.target.value)} max={new Date().toISOString().slice(0, 10)} /></label>}
      </div>
      {error && <p role="alert" className="profileError">{error}</p>}
      <button className="primaryButton profileContinue" type="submit" disabled={busy || (step === 0 && !sex) || (step === 1 && !name.trim()) || (step === 2 && !birthDate)}>{busy ? 'Сохраняем…' : step === 2 ? 'Сохранить' : 'Продолжить'}</button>
    </fieldset></form>
  </section>
}
