export function LoadingScreen() {
  return <div className="bootLoader" role="status" aria-label="Загружаем тренировку">
    <div className="bootPlate" aria-hidden="true">
      <img src="/images/plate-25-v2.png" alt="" width="128" height="128" />
    </div>
    <span className="bootLoaderText">Загружаем тренировку</span>
  </div>
}
