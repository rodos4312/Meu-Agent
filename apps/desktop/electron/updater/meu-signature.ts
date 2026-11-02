import { execFile } from 'node:child_process'
import path from 'node:path'
import { promisify } from 'node:util'

const exec = promisify(execFile)
const SCRIPT = `
$ErrorActionPreference='Stop'
$ProgressPreference='SilentlyContinue'
$env:PSModulePath=Join-Path $PSHOME 'Modules'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
$file=[Environment]::GetEnvironmentVariable('MEU_VERIFY_FILE','Process')
$s=Get-AuthenticodeSignature -LiteralPath $file
$v=[Diagnostics.FileVersionInfo]::GetVersionInfo($file)
[pscustomobject]@{status=$s.Status.ToString();kind=$s.SignatureType.ToString();path=$s.Path;subject=$s.SignerCertificate.Subject;version=$v.ProductVersion} | ConvertTo-Json -Compress
`

export interface MeuSignature {
  status: string
  kind: string
  path: string
  subject: string
  version: string
}

/** A verifier failure is a refusal, including missing PowerShell or malformed output. */
export function assertMeuSignature(info: MeuSignature, file: string, publisher: string, version: string): void {
  if (
    !publisher.startsWith('CN=') ||
    info.status !== 'Valid' ||
    info.kind !== 'Authenticode' ||
    info.subject !== publisher
  ) {
    throw new Error('Meu update signature does not match the trusted publisher.')
  }
  if (typeof info.path !== 'string' || path.resolve(info.path).toLowerCase() !== path.resolve(file).toLowerCase()) {
    throw new Error('Meu signature verification returned a different file.')
  }
  if (info.version !== version) throw new Error('Signed Meu executable version differs from the release.')
}

export async function verifyMeuSignature(file: string, publisher: string, version: string): Promise<void> {
  const systemRoot = process.env.SystemRoot
  if (!systemRoot) throw new Error('Windows signature verifier is unavailable.')
  const { stdout } = await exec(
    path.join(systemRoot, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'),
    ['-NoProfile', '-NonInteractive', '-EncodedCommand', Buffer.from(SCRIPT, 'utf16le').toString('base64')],
    {
      windowsHide: true,
      timeout: 30_000,
      maxBuffer: 128 * 1024,
      env: { ...process.env, MEU_VERIFY_FILE: path.resolve(file) }
    }
  )
  assertMeuSignature(JSON.parse(stdout.trim()), file, publisher, version)
}
