import type { BundledLocale } from './types'

export interface MeuShellCopy {
  navigation: string
  home: string
  customization: string
  welcome: string
}

export const meuShellCopy = {
  en: {
    navigation: 'Main navigation',
    home: 'Home',
    customization: 'Customize',
    welcome: 'What would you like to do?'
  },
  ar: { navigation: 'التنقل الرئيسي', home: 'الرئيسية', customization: 'تخصيص', welcome: 'ماذا تريد أن تفعل؟' },
  de: { navigation: 'Hauptnavigation', home: 'Start', customization: 'Anpassen', welcome: 'Was möchtest du tun?' },
  es: {
    navigation: 'Navegación principal',
    home: 'Inicio',
    customization: 'Personalizar',
    welcome: '¿Qué te gustaría hacer?'
  },
  fr: {
    navigation: 'Navigation principale',
    home: 'Accueil',
    customization: 'Personnaliser',
    welcome: 'Que souhaitez-vous faire ?'
  },
  ja: {
    navigation: 'メインナビゲーション',
    home: 'ホーム',
    customization: 'カスタマイズ',
    welcome: '何をしましょうか？'
  },
  ru: {
    navigation: 'Главная навигация',
    home: 'Главная',
    customization: 'Настроить',
    welcome: 'Что вы хотите сделать?'
  },
  zh: { navigation: '主导航', home: '首页', customization: '自定义', welcome: '你想做些什么？' },
  'zh-hant': { navigation: '主導覽', home: '首頁', customization: '自訂', welcome: '你想做些什麼？' }
} satisfies Record<BundledLocale, MeuShellCopy>
