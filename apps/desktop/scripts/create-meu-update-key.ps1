# Run once on the maintainer's Windows computer. The private key never enters the repository.
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$privateDirectory = Join-Path $root '.meu-tooling/meu-update-key'
$publicPath = Join-Path $root 'apps/desktop/meu-update-key.json'
if ((Test-Path -LiteralPath $publicPath) -or (Test-Path -LiteralPath $privateDirectory)) {
    throw 'A Meu update key already exists. Refusing to replace the update trust identity.'
}
New-Item -ItemType Directory -Path $privateDirectory | Out-Null
$acl = New-Object Security.AccessControl.DirectorySecurity
$acl.SetAccessRuleProtection($true, $false)
$sid = [Security.Principal.WindowsIdentity]::GetCurrent().User
$acl.SetOwner($sid)
$rule = New-Object Security.AccessControl.FileSystemAccessRule($sid, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $privateDirectory -AclObject $acl
$keys = (& node --input-type=commonjs -e "const c=require('node:crypto');const k=c.generateKeyPairSync('ed25519');process.stdout.write(JSON.stringify({publicKey:k.publicKey.export({format:'der',type:'spki'}).toString('base64'),privateKey:k.privateKey.export({format:'pem',type:'pkcs8'})}));") | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or -not $keys.privateKey) { throw 'Could not generate Meu key.' }
$secure = ConvertTo-SecureString -String $keys.privateKey -AsPlainText -Force
$secure | ConvertFrom-SecureString | Set-Content -LiteralPath (Join-Path $privateDirectory 'private-key.dpapi') -Encoding UTF8
@{ algorithm = 'Ed25519'; publicKey = $keys.publicKey } | ConvertTo-Json | Set-Content -LiteralPath $publicPath -Encoding ASCII
$keys = $null
Write-Host 'Created public Meu update key; private key is encrypted for this Windows account in the ignored tooling directory.'
