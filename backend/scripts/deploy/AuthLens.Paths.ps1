# Part of AuthLens.Deploy, dot-sourced into the same module. No operations run on import.
# Path safety shared by publication, ACL audit and remediation: no reparse points on the way, no hidden links inside a tree, no overlapping roots.

function Test-ALPathTree([string]$Path) {
    $item = [System.IO.Path]::GetFullPath($Path)
    while ($item) {
        if (Test-Path -LiteralPath $item) {
            if ((Get-Item -LiteralPath $item -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-AL "Installation paths must not traverse reparse points ($item)." }
        }
        $item = [IO.Path]::GetDirectoryName($item)
    }
}

function Get-ALTreeFiles([string]$Root) {
    Test-ALPathTree $Root
    foreach ($item in Get-ChildItem -LiteralPath $Root -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { Stop-AL "Installation trees must not contain reparse points ($($item.FullName))." }
        if ($item.PSIsContainer) { Get-ALTreeFiles $item.FullName } else { $item }
    }
}

function Test-ALPathOverlap([string]$Left, [string]$Right) {
    $a = [IO.Path]::GetFullPath($Left).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $b = [IO.Path]::GetFullPath($Right).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    $a.StartsWith($b, [StringComparison]::OrdinalIgnoreCase) -or $b.StartsWith($a, [StringComparison]::OrdinalIgnoreCase)
}
