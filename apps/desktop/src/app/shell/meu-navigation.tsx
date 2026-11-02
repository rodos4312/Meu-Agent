import './meu-navigation.css'

import { useEffect, useRef } from 'react'
import { useLocation, useNavigate } from 'react-router'

import { Button } from '@/components/ui/button'
import { Codicon } from '@/components/ui/codicon'
import { Tip } from '@/components/ui/tooltip'
import { useI18n } from '@/i18n'

import {
  appViewForPath,
  CAPABILITIES_ROUTE,
  CRON_ROUTE,
  navigateToWorkspacePage,
  NEW_CHAT_ROUTE,
  SETTINGS_ROUTE
} from '../routes'

import { TITLEBAR_HEIGHT } from './titlebar'

/** Route changes leave the session tiles and composer alive. Home returns to
 * the last chat route, rather than creating another session. */
export function MeuNavigationRail() {
  const { t } = useI18n()
  const location = useLocation()
  const navigate = useNavigate()
  const view = appViewForPath(location.pathname)
  const lastChat = useRef(NEW_CHAT_ROUTE)
  const target = `${location.pathname}${location.search}${location.hash}`
  const tab = new URLSearchParams(location.search).get('tab') ?? 'skills'

  // eslint-disable-next-line no-restricted-syntax -- remembers a router destination, not a mirrored atom
  useEffect(() => {
    if (view === 'chat') {
      lastChat.current = target
    }
  }, [target, view])

  const items = [
    { id: 'home', icon: 'home', label: t.meuShell.home, active: view === 'chat', to: NEW_CHAT_ROUTE },
    { id: 'scheduled', icon: 'calendar', label: t.sidebar.nav.cron, active: view === 'cron', to: CRON_ROUTE },
    {
      id: 'plugins',
      icon: 'extensions',
      label: t.skills.tabPlugins,
      active: view === 'capabilities' && tab === 'plugins',
      to: `${CAPABILITIES_ROUTE}?tab=plugins`
    },
    {
      id: 'skills',
      icon: 'book',
      label: t.skills.tabSkills,
      active: view === 'capabilities' && tab !== 'plugins',
      to: `${CAPABILITIES_ROUTE}?tab=skills`
    },
    {
      id: 'settings',
      icon: 'settings-gear',
      label: t.commandCenter.settings,
      active: view === 'settings',
      to: SETTINGS_ROUTE
    }
  ]

  return (
    <nav
      aria-label={t.meuShell.navigation}
      className="meu-navigation-rail"
      style={{ paddingTop: TITLEBAR_HEIGHT + 12 }}
    >
      <span aria-hidden="true" className="meu-navigation-brand">
        M
      </span>
      {items.map(item => (
        <Tip key={item.id} label={item.label} side="right">
          <Button
            aria-current={item.active ? 'page' : undefined}
            aria-label={item.label}
            className={item.id === 'settings' ? 'mt-auto' : undefined}
            data-meu-nav={item.id}
            onClick={() => navigateToWorkspacePage(navigate, item.id === 'home' ? lastChat.current : item.to)}
            size="icon-lg"
            variant="navigation"
          >
            <Codicon name={item.icon} size={20} />
          </Button>
        </Tip>
      ))}
    </nav>
  )
}

export function MeuCapabilitySidebar() {
  const { t } = useI18n()
  const { search } = useLocation()
  const navigate = useNavigate()
  const tab = new URLSearchParams(search).get('tab')
  const selected = ['plugins', 'connectors', 'toolsets'].includes(tab ?? '') ? tab : 'skills'

  const items = [
    { id: 'plugins', icon: 'extensions', label: t.skills.tabPlugins },
    { id: 'skills', icon: 'book', label: t.skills.tabSkills },
    { id: 'connectors', icon: 'plug', label: t.connectorsPage.title },
    { id: 'toolsets', icon: 'tools', label: t.skills.tabToolsets }
  ]

  return (
    <div className="meu-capability-sidebar">
      <div className="meu-sidebar-heading">{t.meuShell.customization}</div>
      <nav aria-label={t.meuShell.customization} className="flex flex-col gap-1">
        {items.map(item => (
          <Button
            aria-current={selected === item.id ? 'page' : undefined}
            className="justify-start"
            key={item.id}
            onClick={() => navigateToWorkspacePage(navigate, `${CAPABILITIES_ROUTE}?tab=${item.id}`)}
            size="touch"
            variant="navigation"
          >
            <Codicon name={item.icon} size={17} />
            {item.label}
          </Button>
        ))}
      </nav>
    </div>
  )
}
