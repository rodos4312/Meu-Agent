export const jaUpdateChannel = {
  title: 'アップデートチャンネル',
  description:
    '安定版は公開済みのリリースのみをインストールします。すべてのコミットは main ブランチの変更に追従します。',
  stable: '安定版リリース',
  main: 'すべてのコミット',
  stableConfirmTitle: '安定版リリースに切り替えますか？',
  stableConfirmBody:
    'Meu は最新の公開リリースに移動します。現在のコードより古い場合があります。新しいコードが書き込んだデータは正しく読めない可能性があるため、先にバックアップしてください。',
  stableConfirm: '安定版に切り替え',
  failed: 'アップデートチャンネルを変更できませんでした',
  detailsLabel: 'チャンネル',
  branch: (b: string) => `ブランチ: ${b}`,
  change: '変更',
  latestRelease: (v: string) => `最新の安定版リリース（${v}）を使用しています。`,
  rollbackTitle: (v: string) => `安定版リリース ${v} に戻す`,
  rollbackBody: (v: string) =>
    `このビルドは安定版リリース ${v} より新しいです。インストールすると Meu はそのリリースに戻ります。`,
  heldBody: (v: string) =>
    `このビルドは安定版 ${v} より新しく、セッションはすでに ${v} では開けないゲートウェイ ランタイムを使っています。新しい安定版が出るまで、Meu はこのビルドのままです。`,
  rollbackAction: (v: string) => `${v} に戻す`,
  allChanges: 'すべての変更を見る',
  meuDescription: '安定版は署名済みの公開 Meu リリースをインストールします。RC はプレリリース版のテスト用です。',
  meuStable: '安定版',
  meuRc: 'RC',
  rcConfirmTitle: 'RC ビルドに切り替えますか？',
  rcWarning: 'RC ビルドはテスト用のプレリリース版です。',
  rcConfirm: 'RC に切り替える',
  rcManual: 'Meu が RC を自動でインストールすることはありません。手動でダウンロードしてください。',
  rcReleases: 'RC リリース'
}
