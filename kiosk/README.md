# LexSign kiosk setup for display players

Makes a Windows display player (for example a Scala Media Player-SP) open a LexSign
display screen full screen at boot, with no address bar, rotated for vertical screens,
and reopen it automatically if the browser is ever closed.

Files:

- `lexsign-kiosk.cmd` – the launcher. Edit the three lines at the top per screen.
- `install-kiosk.cmd` – one-time installer. Copies the launcher to `C:\Tools\LexSign`,
  adds it to the Startup folder and stops the screen from ever sleeping.

## Per-screen settings (top of `lexsign-kiosk.cmd`)

| Setting | Meaning | Example |
|---|---|---|
| `SERVER_URL` | Where LexSign runs. LAN IP of the server during testing, the HTTPS domain in production. | `http://10.215.95.165:8000` or `https://court.example.in` |
| `SCREEN` | Which display to show. | `court-1` … `court-4`, `master-1` … `master-4` |
| `ROTATE` | `90` clockwise, `270` anti-clockwise, `0` for a landscape screen or when Windows itself is set to Portrait. | `90` |

If the picture appears upside down, switch `90` to `270`.

## Install on a player

1. Plug in a keyboard and mouse. Log in as the account that will auto-log in at boot.
   On a Scala player this is normally the **Configure Player** (`scala`) account.
2. Scala players only: make sure the write filter is off, otherwise nothing is saved.
   Run `C:\Tools\DISABLE_UWF_C.CMD` and reboot if it reports a change.
3. Install Google Chrome or Microsoft Edge. Internet Explorer cannot run LexSign.
4. Copy this `kiosk` folder to the player (USB stick). Edit `lexsign-kiosk.cmd`.
5. Right-click `install-kiosk.cmd`, **Run as administrator**.
6. Make the account log in automatically at boot:
   - Scala player: run `C:\CONFIG.WES\WES10_RegKeys\hlm\HLM_EnableSCALA-CFG-AdminAutologon.reg`
     (for the `scala` account) after putting its password in the file, or use the
     Start-menu **AutoLogon** scripts described in the Scala manual.
   - Plain Windows PC: run `netplwiz`, untick "Users must enter a user name and password".
7. Scala player only: stop the Scala Player app from taking over the screen. In the Start
   menu run **Disable Transmission Client** and do not use "AutoLogon Player Account".
8. Reboot. The LexSign screen should appear full screen within about 30 seconds of logon.
9. Scala player only: once it works, run `C:\Tools\ENABLE_UWF_C.CMD` to lock the
   configuration against changes.

## Daily operation

- **Alt+F4** closes the kiosk; it reopens after 5 seconds. To stop it for maintenance,
  end `lexsign-kiosk.cmd` (cmd.exe) in Task Manager, then close Chrome.
- The launcher waits until the LexSign server answers before opening the browser, so a
  player that boots before the server simply shows a black screen until the server is up.
- Change the URL or screen by editing `C:\Tools\LexSign\lexsign-kiosk.cmd` and rebooting.
- Two screens on one player: run the installer, then copy the launcher to a second file
  with a different `SCREEN`, add `--window-position=1920,0` to the browser line and
  `_2` to the `PROFILE` folder, and add that file to the Startup folder as well.

## Vertical screens: two ways to rotate

- **Recommended for Scala players:** keep Windows in landscape and use `ROTATE=90` or `270`.
  LexSign rotates the page itself.
- **Alternative:** Windows Settings → System → Display → Orientation → Portrait, and set
  `ROTATE=0`. LexSign detects a portrait screen on its own. Do not do both.
