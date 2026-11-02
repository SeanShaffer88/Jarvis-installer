# Fixed Windows toast script. Untrusted text arrives ONLY through -Title,
# -Message, and -Subtitle argv values and is assigned via InnerText, never
# interpolated into PowerShell, XML source, or a command string.
param(
    [string]$AppId = 'SeanShaffer.Jarvis.Windows',
    [string]$Title = '',
    [string]$Message = '',
    [string]$Subtitle = ''
)

$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class JarvisAppUserModelId {
    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    public static extern int SetCurrentProcessExplicitAppUserModelID(string appId);
}
'@

[JarvisAppUserModelId]::SetCurrentProcessExplicitAppUserModelID($AppId) | Out-Null

[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]

$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent(
    [Windows.UI.Notifications.ToastTemplateType]::ToastText02)
$textNodes = $template.GetElementsByTagName('text')
$textNodes.Item(0).InnerText = $Title
if ([string]::IsNullOrEmpty($Subtitle)) {
    $textNodes.Item(1).InnerText = $Message
} else {
    $textNodes.Item(1).InnerText = $Subtitle + [Environment]::NewLine + $Message
}

$toast = [Windows.UI.Notifications.ToastNotification]::new($template)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($AppId)
$notifier.Show($toast)
