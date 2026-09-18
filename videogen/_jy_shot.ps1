$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UD {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[UD]::SetProcessDPIAware() | Out-Null
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
$bmp = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Left, $bounds.Top, 0, 0, $bmp.Size)
$bmp.Save('C:\Users\wang\AppData\Local\Temp\jy_now.png', [System.Drawing.Imaging.ImageFormat]::Png)
Write-Output ("shot " + $bounds.Width + "x" + $bounds.Height)
