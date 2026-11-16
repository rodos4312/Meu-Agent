# Loaded only by the packaged installer's source stage. No profile/config writes.
function Expand-MeuSourceSeed {
    if ($env:MEU_AGENT_MODE -ne '1' -or $Branch -cne 'dev/meu-foundation' -or
        $Commit -cnotmatch '^[a-f0-9]{40}$' -or $SourceSeedSha256 -cnotmatch '^[a-f0-9]{64}$' -or
        $SourceSeedRepository -cne 'https://github.com/rodos4312/Meu-Agent-RC-private.git' -or -not $BackendOnly) {
        throw 'Invalid packaged Meu core authority'
    }
    $file = Get-Item -LiteralPath $SourceSeed -Force
    if ($file.PSIsContainer -or $file.LinkType -or $file.Length -gt 536870912 -or
        (Get-FileHash -LiteralPath $SourceSeed -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SourceSeedSha256) {
        throw 'Meu core package checksum failed; reinstall this application'
    }
    $cache = Join-Path $HermesHome "cache/s-$($SourceSeedSha256.Substring(0,16))"
    $seed = Join-Path $cache 'source.git'
    if (-not (Test-Path -LiteralPath $seed -PathType Container)) {
        $stage = "$cache.tmp-$PID"
        New-Item -ItemType Directory -Path $stage -Force | Out-Null
        # The archive is generated from Git objects, has no hooks/config/secrets,
        # and was checked against the hash baked into this exact app before extraction.
        Expand-Archive -LiteralPath $SourceSeed -DestinationPath $stage
        Move-Item -LiteralPath $stage -Destination $cache
    }
    $actual = (Invoke-Native { git -C $seed rev-parse "refs/heads/$Branch" }).Trim()
    if ($LASTEXITCODE -or $actual -cne $Commit) { throw 'Packaged Meu source revision mismatch' }
    Invoke-Native { git -C $seed fsck --connectivity-only } | Out-Null
    if ($LASTEXITCODE) { throw 'Packaged Meu source history is incomplete' }
    return $seed
}
