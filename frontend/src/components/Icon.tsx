import '@vscode/codicons/dist/codicon.css'

const icons = {
  conversations: 'comment-discussion',
  knowledge: 'book',
  account: 'account',
  settings: 'settings-gear',
  search: 'search',
  arrowRight: 'arrow-right',
  chevronDown: 'chevron-down',
}

export function Icon({
  name,
  size = 16,
}: {
  name: keyof typeof icons
  size?: number
}) {
  return (
    <span
      className={`codicon codicon-${icons[name]}`}
      style={{ fontSize: size, width: size, height: size }}
      aria-hidden="true"
    />
  )
}
