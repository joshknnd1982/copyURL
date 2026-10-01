# Copy URL

Copy URL is an NVDA add-on for web browsers. It copies the current web page URL or a link's destination URL to the clipboard and announces the result.

## Commands

- Press `Alt+Control+Windows+C` in a browse-mode document to copy the current page URL.
- Move the browse-mode cursor or navigator object to a link and press `Alt+Control+Windows+L` to copy its destination without opening it.

Both commands appear in NVDA's **Input Gestures** dialog under the **Copy URL** category, where their shortcuts can be changed or removed.

## Settings

Open **NVDA menu > Preferences > Settings > Copy URL** to:

- Turn the "URL copied" prefix for page URLs on or off.
- Enable or disable the Copy Link URL command.
- Turn the "Link URL copied" prefix for link URLs on or off.
- Turn the daily check for updates on or off, or check now.

## Updates

Copy URL checks for updates. Once a day, a little after NVDA starts, the add-on asks its GitHub repository, [github.com/joshknnd1982/copyURL](https://github.com/joshknnd1982/copyURL), whether a newer version has been released, and says nothing unless there is one. When there is, a dialog shows what's new in a box you can read line by line, and offers to download and install it. The download must match the release's SHA-256 checksum. Then NVDA asks you to confirm the installation and offers to restart. Your settings are kept.

To check yourself, open the NVDA menu, choose **Tools**, then **Check for add-on updates**, and choose **Copy URL...**. Or press **Check for updates now** in the add-on's settings: NVDA menu, Preferences, Settings, **Copy URL**. You can also assign a gesture to **Checks for Copy URL updates** in NVDA's Input Gestures dialog, under **Copy URL**. To stop the daily check, clear **Check for Copy URL updates automatically** in the same settings panel.

## Compatibility

- Minimum NVDA version: 2019.3.0
- Last tested NVDA version: 2026.1.1
- Designed only for web-browser content in browsers such as Firefox, Chrome, and Edge. It is not designed for browse mode in non-browser applications such as Microsoft Word.

## UIA browse mode

Both commands work in UIA browse mode, when NVDA reads Microsoft Edge or another Chromium browser through UI Automation. That happens when **Use UIA with Microsoft Edge and other Chromium based browsers when available** is set to **Yes** in NVDA's Advanced settings, and NVDA can also choose UI Automation itself under the default setting. Copy Page URL copies the page's own address, which in UIA browse mode is the document's value rather than the identifier NVDA uses to remember your place.

In Chromium browsers, Copy Page URL also works when focus is in the address bar or on the toolbar: it copies the address of the page in the tab on screen.

Copy Link URL finds the link at the navigator object first, so a link you reached with object navigation is copied. If there is none there, it looks at the browse-mode cursor, which matters when **Follow caret** is off in NVDA's Review Cursor settings, and then at the focus, which is the link itself in focus mode. The cursor can be on the link's text, or on bold or other formatted text up to ten levels inside the link.

## Privacy and security

Copy URL collects no information. It reads a URL exposed by NVDA and places that URL on the clipboard only when you invoke one of its commands.

Once a day, and whenever you ask it to, Copy URL asks GitHub (api.github.com) for the latest release of github.com/joshknnd1982/copyURL. The request carries only the add-on's name and version. It downloads an update only when you choose Download and install. It keeps its update settings, whether to check automatically and when it last checked, in `addonUpdates\copyURL.json` in NVDA's user configuration folder. Clear **Check for Copy URL updates automatically** in its settings to stop the daily check.

## Author and contact

Dennis Long <dennisl@fastmail.com>

## Source and license

Source: https://github.com/joshknnd1982/copyURL, a fork of https://github.com/Dennisl123/copyURL

To test, run `python -m unittest discover -s tests`. To build the add-on, run `python build.py`. It writes `dist/copyURL-<version>.nvda-addon` and a `.sha256` file beside it; upload both to the GitHub release, tagged `v<version>`. `globalPlugins/copyURL/updater.py` is the update check, shared by all of joshknnd1982's add-ons; keep it identical to theirs.

Copyright (C) 2026 Dennis Long and Josh Kennedy. Licensed under the [MIT License](LICENSE.md).

## Changes in 1.9.4

- Works in UIA browse mode. When NVDA reads Edge or another Chromium browser through UI Automation, Copy Page URL copies the page's address. Before, it said "No URL found" or copied a number such as 792.
- In Chromium browsers, Copy Page URL also works when focus is in the address bar or on the toolbar.
- Copy Link URL finds the link at the browse-mode cursor even when the navigator object has not followed it, finds the focused link in focus mode, and finds links whose text is formatted several levels deep.

## Changes in 1.9.3

- Checks GitHub for updates once a day and offers to install them. Choose Tools, Check for add-on updates, Copy URL in the NVDA menu, or press Check for updates now in Copy URL's settings, to check yourself.
- Updates come from github.com/joshknnd1982/copyURL.

## Changes in 1.9.2

- Clarified that Copy URL is designed only for web browsers, not browse mode in applications such as Microsoft Word.
- Documented the Copy Page URL limitation in Edge when UIA browse mode is enabled.

## Changes in 1.9.1

- Updated the author, compatibility, licensing, and documentation metadata for NVDA Add-on Store submission.
- Made settings-panel registration and cleanup safe during add-on reloads.
