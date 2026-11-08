import { useRef, useState } from 'react'

// The ref closes the double-click gap before React renders the disabled button.
export function useSubmission() {
  const running = useRef(false)
  const [busy, setBusy] = useState(false)
  const submit = async (action: () => Promise<unknown>) => {
    if (running.current) return
    running.current = true
    setBusy(true)
    try { await action() }
    finally { running.current = false; setBusy(false) }
  }
  return { busy, submit }
}
