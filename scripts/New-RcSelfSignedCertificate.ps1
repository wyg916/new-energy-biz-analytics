param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [ValidatePattern("^[A-Za-z0-9.-]+$")]
    [string]$DnsName = "localhost",
    [ValidateRange(1, 30)]
    [int]$ValidDays = 7
)

$ErrorActionPreference = "Stop"
$resolvedDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $resolvedDirectory -Force | Out-Null
$dockerMount = $resolvedDirectory.Replace("\", "/")
$subjectAlternativeName = if ($DnsName -eq "localhost") {
    "DNS:localhost,IP:127.0.0.1"
} else {
    "DNS:$DnsName,DNS:localhost"
}

& docker run --rm `
    --volume "${dockerMount}:/out" `
    alpine:3.20 `
    sh -ec `
    "apk add --no-cache openssl >/dev/null && openssl req -x509 -newkey rsa:2048 -sha256 -nodes -keyout /out/tls.key -out /out/tls.crt -days $ValidDays -subj /CN=$DnsName -addext subjectAltName=$subjectAlternativeName"

if ($LASTEXITCODE -ne 0) {
    throw "Docker-backed self-signed certificate generation failed"
}

[pscustomobject]@{
    OutputDirectory = $resolvedDirectory
    DnsName = $DnsName
    ValidDays = $ValidDays
    Purpose = "local RC validation only"
}
