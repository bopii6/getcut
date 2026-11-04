param([string]$Json = "E:\getcut\fx_fx.json", [string]$Out = "E:\getcut\article.md")
$j = Get-Content $Json -Raw | ConvertFrom-Json
$a = $j.tweet.article
"TITLE: $($a.title)"
$content = $a.content
"CONTENT KEYS: " + ($content.PSObject.Properties.Name -join ', ')
$blocks = $content.blocks
"BLOCK COUNT: $($blocks.Count)"
$entities = @{}
foreach ($e in $content.entityMap) { $entities[[string]$e.key] = $e.value }

$sb = New-Object System.Text.StringBuilder
[void]$sb.AppendLine("# " + $a.title)
[void]$sb.AppendLine()
foreach ($b in $blocks) {
    $type = $b.type
    $text = $b.text
    $extra = @()
    foreach ($er in $b.entityRanges) {
        $k = [string]$er.key
        if ($entities.ContainsKey($k)) {
            $v = $entities[$k]
            if ($v.type -eq 'MARKDOWN') { $extra += $v.data.markdown }
            elseif ($v.type -eq 'MEDIA') {
                $ids = @()
                foreach ($mi in $v.data.mediaItems) { $ids += $mi.mediaId }
                $extra += ("[IMAGE mediaId=" + ($ids -join ',') + "]")
            }
            elseif ($v.type -eq 'LINK') { $extra += "[LINK " + $v.data.url + "]" }
        }
    }
    switch ($type) {
        'header-one'   { [void]$sb.AppendLine("## " + $text) }
        'header-two'   { [void]$sb.AppendLine("### " + $text) }
        'header-three' { [void]$sb.AppendLine("#### " + $text) }
        'unstyled'     { if ($text.Trim()) { [void]$sb.AppendLine($text) } }
        'atomic'       { }
        default        { if ($text.Trim()) { [void]$sb.AppendLine($text) } }
    }
    foreach ($x in $extra) { [void]$sb.AppendLine($x) }
    if ($type -ne 'atomic') { [void]$sb.AppendLine() }
}
$sb.ToString() | Out-File -Encoding utf8 $Out
"WROTE $Out  chars=$($sb.Length)"
