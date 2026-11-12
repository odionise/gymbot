export function LoadingScreen() {
  return <div className="bootLoader" role="status" aria-label="Загружаем тренировку">
    <div className="bootPlate" aria-hidden="true">
      <svg viewBox="0 0 160 160" focusable="false">
        <circle cx="80" cy="80" r="75" fill="#222226" stroke="#57575e" strokeWidth="2" />
        <circle cx="80" cy="80" r="66" fill="none" stroke="#424249" strokeWidth="7" />
        <circle cx="80" cy="80" r="57" fill="#29292e" stroke="#696970" strokeWidth="1.5" />
        <path d="M36 49a54 54 0 0 1 31-22M123 110a54 54 0 0 1-31 23" fill="none" stroke="#86868d" strokeWidth="2" strokeLinecap="round" opacity=".55" />
        <circle cx="80" cy="80" r="23" fill="#171719" stroke="#73737a" strokeWidth="5" />
        <circle cx="80" cy="80" r="9" fill="#08090b" stroke="#92929a" strokeWidth="2" />
        <text x="80" y="45" textAnchor="middle" fill="#f7f7f8" fontSize="19" fontWeight="800" letterSpacing="1">25 КГ</text>
        <path d="M49 105h17m28 0h17" stroke="#8b8b93" strokeWidth="3" strokeLinecap="round" />
      </svg>
    </div>
    <span className="bootLoaderText">Загружаем тренировку</span>
  </div>
}
