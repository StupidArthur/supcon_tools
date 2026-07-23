interface RealtimeTabsProps {
  value: 'config' | 'run'
  onChange: (tab: 'config' | 'run') => void
}

const tabs: { key: 'config' | 'run'; label: string }[] = [
  { key: 'config', label: '组态' },
  { key: 'run', label: '运行' },
]

export function RealtimeTabs({ value, onChange }: RealtimeTabsProps) {
  return (
    <div className="flex border-b border-border px-4" data-testid="realtime-tabs">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          type="button"
          onClick={() => onChange(tab.key)}
          className={`px-4 py-2 text-sm ${
            value === tab.key
              ? 'border-b-2 border-primary font-medium text-foreground'
              : 'text-muted-foreground hover:text-foreground'
          }`}
          data-testid={`realtime-tab-${tab.key}`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
