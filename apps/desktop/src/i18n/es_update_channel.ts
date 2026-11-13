export const esUpdateChannel = {
  title: 'Canal de actualizaciones',
  description: 'Estable instala solo versiones publicadas. Cada commit sigue la rama main a medida que llegan cambios.',
  stable: 'Versiones estables',
  main: 'Cada commit',
  stableConfirmTitle: '¿Cambiar a versiones estables?',
  stableConfirmBody:
    'Meu pasará a la última versión publicada, que puede ser más antigua que el código que usas ahora. Los datos escritos por código más nuevo podrían no leerse bien, así que haz una copia antes.',
  stableConfirm: 'Cambiar a estable',
  failed: 'No se pudo cambiar el canal de actualizaciones',
  detailsLabel: 'Canal',
  branch: (b: string) => `Rama: ${b}`,
  change: 'Cambiar',
  latestRelease: (v: string) => `Tienes la última versión estable (${v}).`,
  rollbackTitle: (v: string) => `Volver a la versión estable ${v}`,
  rollbackBody: (v: string) =>
    `Esta compilación es más reciente que la versión estable ${v}. Al instalarla, Meu vuelve a esa versión.`,
  heldBody: (v: string) =>
    `Esta versión es más reciente que la versión estable ${v}, y tus sesiones ya usan su entorno de gateway, que ${v} no puede abrir. Meu se queda en esta versión hasta que salga una versión estable más reciente.`,
  rollbackAction: (v: string) => `Volver a ${v}`,
  allChanges: 'Ver todos los cambios',
  meuDescription: 'Estable instala versiones públicas firmadas de Meu. RC es para probar versiones preliminares.',
  meuStable: 'Estable',
  meuRc: 'RC',
  rcConfirmTitle: '¿Cambiar a versiones RC?',
  rcWarning: 'Las versiones RC son preliminares y están pensadas para pruebas.',
  rcConfirm: 'Cambiar a RC',
  rcManual: 'Meu nunca instala un RC por sí solo: descárgalo manualmente.',
  rcReleases: 'Versiones RC'
}
