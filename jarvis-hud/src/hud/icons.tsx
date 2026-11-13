/** Ícones do HUD (traço fino, cor herdada). Desenhados aqui: nada de fonte de ícones externa. */
const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinecap: 'round', strokeLinejoin: 'round' } as const

function Svg({ children, label }: { children: React.ReactNode; label?: string }) {
  return <svg viewBox="0 0 24 24" aria-hidden={label ? undefined : true} role={label ? 'img' : undefined} aria-label={label}>{children}</svg>
}

export const SunIcon = () => <Svg><circle cx="12" cy="12" r="4" {...S} /><path d="M12 2.8v2.4M12 18.8v2.4M2.8 12h2.4M18.8 12h2.4M5.5 5.5l1.7 1.7M16.8 16.8l1.7 1.7M5.5 18.5l1.7-1.7M16.8 7.2l1.7-1.7" {...S} /></Svg>
export const FilmIcon = () => <Svg><rect x="3.5" y="5" width="17" height="14" rx="2" {...S} /><path d="M3.5 9h17M3.5 15h17M8 5v4M12 5v4M16 5v4M8 15v4M12 15v4M16 15v4" {...S} /></Svg>
export const FocusIcon = () => <Svg><circle cx="12" cy="12" r="7.5" {...S} /><circle cx="12" cy="12" r="3.5" {...S} /><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" {...S} /></Svg>
export const MoonIcon = () => <Svg><path d="M19.5 14.5A8 8 0 0 1 9.5 4.5a8 8 0 1 0 10 10Z" {...S} /><path d="M16.5 4.5v3M15 6h3" {...S} /></Svg>
export const DoorIcon = () => <Svg><path d="M6 21V4.5A1.5 1.5 0 0 1 7.5 3h7A1.5 1.5 0 0 1 16 4.5V21M3.5 21h17" {...S} /><circle cx="13" cy="12.5" r=".9" fill="currentColor" /><path d="M19 9l2 2-2 2M16 11h5" {...S} /></Svg>
export const SparkIcon = () => <Svg><path d="M12 3l1.9 5.6L19.5 10l-5.6 1.9L12 17.5l-1.9-5.6L4.5 10l5.6-1.4Z" {...S} /><path d="M18.5 16.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8Z" {...S} /></Svg>
export const BulbIcon = () => <Svg><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.6 10.8c.7.6 1.1 1.3 1.1 2.2h5c0-.9.4-1.6 1.1-2.2A6 6 0 0 0 12 3Z" {...S} /></Svg>
export const BulbOffIcon = () => <Svg><path d="M9 18h6M10 21h4M8.2 5.2A6 6 0 0 1 17.6 13.4M15.6 15.9c-.1.1-.1.1-.1.1h-5c0-.9-.4-1.6-1.1-2.2A6 6 0 0 1 6.1 8M3.5 3.5l17 17" {...S} /></Svg>
export const StripIcon = () => <Svg><rect x="2.5" y="9" width="19" height="6" rx="3" {...S} /><circle cx="7" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="17" cy="12" r="1" fill="currentColor" /></Svg>
export const LockIcon = () => <Svg><rect x="5" y="10.5" width="14" height="10" rx="2" {...S} /><path d="M8 10.5V7.5a4 4 0 0 1 8 0v3M12 14.5v2.5" {...S} /></Svg>
export const ShieldIcon = () => <Svg><path d="M12 3l7.5 3v5.5c0 4.6-3.1 8.2-7.5 9.5-4.4-1.3-7.5-4.9-7.5-9.5V6Z" {...S} /><rect x="9" y="11" width="6" height="4.5" rx="1" {...S} /><path d="M10.2 11V9.7a1.8 1.8 0 0 1 3.6 0V11" {...S} /></Svg>
export const EyeIcon = () => <Svg><path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12Z" {...S} /><circle cx="12" cy="12" r="3" {...S} /></Svg>
export const HistoryIcon = () => <Svg><path d="M3.5 12a8.5 8.5 0 1 0 2.5-6M3.5 4v4h4M12 7.5V12l3 2" {...S} /></Svg>
export const HelpIcon = () => <Svg><circle cx="12" cy="12" r="9" {...S} /><path d="M9.6 9.3a2.5 2.5 0 0 1 4.8.9c0 1.7-2.4 2.1-2.4 3.6M12 17h.01" {...S} /></Svg>
export const FullIcon = () => <Svg><path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" {...S} /></Svg>
export const BellIcon = () => <Svg><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15ZM10 20.5a2 2 0 0 0 4 0" {...S} /></Svg>
export const CloseIcon = () => <Svg><path d="M6 6l12 12M18 6 6 18" {...S} /></Svg>
export const PlayIcon = () => <Svg><path d="M8 5.5v13l10.5-6.5Z" {...S} /></Svg>
export const ClockIcon = () => <Svg><circle cx="12" cy="12" r="8.5" {...S} /><path d="M12 7.5V12l3 2" {...S} /></Svg>

export function SceneIcon({ icon }: { icon?: string }) {
  switch (icon) {
    case 'sol': return <SunIcon />
    case 'filme': return <FilmIcon />
    case 'foco': return <FocusIcon />
    case 'lua': return <MoonIcon />
    case 'porta': return <DoorIcon />
    default: return <SparkIcon />
  }
}
