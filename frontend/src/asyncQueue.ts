// Serialize changes to one workout so an older response cannot replace newer
// facts on screen. A rejected action is reported to its caller; later actions
// can still run. No action is retried.
export function createSerialQueue() {
  let tail: Promise<unknown> = Promise.resolve()
  return <T>(action: () => Promise<T>): Promise<T> => {
    const result = tail.then(action)
    tail = result.then(() => undefined, () => undefined)
    return result
  }
}
