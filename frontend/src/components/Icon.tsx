import '@vscode/codicons/dist/codicon.css'

const icons = {
  conversations: 'comment-discussion',
  knowledge: 'book',
  account: 'account',
  settings: 'settings-gear',
  search: 'search',
  arrowRight: 'arrow-right',
  chevronDown: 'chevron-down',
  arrowLeft: 'arrow-left',
  document: 'file-text',
  people: 'organization',
  phone: 'device-mobile',
  info: 'info',
  check: 'check',
  close: 'close',
  lock: 'lock',
  plus: 'add',
  link: 'link',
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
