# Remote access

Remote access lets a paired device interact with an application browser retained on the PC. Use it to complete sign-in, CAPTCHA or verification steps yourself. It does not provide general access to the Windows desktop or the local dashboard API.

## Pair a device

1. Keep JobPilot running on the PC. Open **Remote access** locally and enable it.
2. Wait for the HTTPS connection, then open the displayed private link or scan its QR code on your device.
3. Keep the link private: it authorizes pairing. A Home Screen launch may require pasting the same link or code into the pairing box.
4. Optionally enable notifications on that device. Browser notification permission is required; use **Send test** to check delivery. On iPhone or iPad, follow the portal's Home Screen instructions before enabling notifications.

Installation downloads a pinned, SHA-256-verified `cloudflared` helper. For a source run using the data directory from [setup](setup.md), install it with:

```powershell
.\scripts\Install-RemoteTools.ps1 -InstallRoot (Join-Path $env:LOCALAPPDATA 'JobPilot-Source')
```

The helper is at `<parent of the data directory>\tools\cloudflared.exe`; the installer follows this layout even with a custom `-DataRoot`. The current implementation uses a **temporary Cloudflare Quick Tunnel hostname**. Restarting the tunnel can change its address; open the new link from the local dashboard and re-pair or re-enable notifications as needed. This is not a stable hosted address or an always-on service.

## Continue an application

Select a waiting application to see its browser image. Tap a field, type the required value or code, and complete the employer's challenge. The password and code entry boxes clear after sending. Choose **Resume application** after a pre-submission challenge clears. After a submission attempt, JobPilot resumes confirmation only when it observes a new matching employer receipt; completing verification alone is not proof of submission.

The PC, worker, browser context and internet connection must stay available. Cancelling, timing out or losing a submitted session keeps its outcome uncertain. Check the employer portal before resolving that outcome; do not submit the same application again just to test connectivity.

## Privacy and revocation

The paired device can see and control the retained application browser, including information visible on that page. The browser view travels through Cloudflare; optional generic notifications travel through the device's push provider. Input commands are transient and are not saved as application answers or durable input logs. Ordinary employer browser sessions can still retain the employer's cookies.

Use the local **Revoke paired devices** control if a link or device is exposed. Disable remote access when it is no longer needed; finish or cancel active sessions first. Revocation and disconnects do not establish an application receipt. See [SECURITY.md](../SECURITY.md) for reporting a vulnerability.
