# omarchy-next-event

A small, ICS-first next-meeting indicator for Omarchy.

This project started as the `next-event` script in the
`computer-cli` dotfiles repo. It is being extracted so it can become a native
Omarchy Quickshell plugin instead of remaining tied to one machine's Waybar
configuration.

## What it does

The current CLI implementation:

- reads one or more ICS feed URLs from `~/.config/next-event/calendars.txt`;
- caches feeds and uses ETag/Last-Modified when refreshing;
- expands recurring events for the next 30 days;
- chooses the next or recently-started meeting;
- detects Zoom, Google Meet, Teams, Webex, and GoToMeeting links;
- emits Waybar-compatible JSON; and
- opens the detected meeting link with `--open`.

The display intentionally stays hidden when the next meeting is more than
three hours away. `BarWidget.qml` exposes the same behavior as a native
Omarchy Quickshell `bar-widget`: left-click opens the next meeting, right-click
opens Google Calendar, and middle-click refreshes the feed.

## Local development

Install [uv](https://docs.astral.sh/uv/) and create a local configuration:

```bash
mkdir -p ~/.config/next-event
cp calendars.example.txt ~/.config/next-event/calendars.txt
${EDITOR:-vi} ~/.config/next-event/calendars.txt
```

Install the calendar dependencies:

```bash
./setup.sh
```

Run the CLI:

```bash
uv run ./next-event
uv run ./next-event --open
```

Do not commit a private calendar URL. The local `calendars.txt` file is
ignored because a private ICS URL grants access to calendar data.

## Omarchy direction

Install the plugin from a public Git repository with:

```bash
omarchy plugin add <repository-url> --enable
```

Omarchy intentionally does not execute arbitrary plugin setup hooks. After the
plugin is installed, set up its Python environment and calendar feed manually:

```bash
PLUGIN_DIR="$HOME/.config/omarchy/plugins/io.github.noahbrier.next-event"
cd "$PLUGIN_DIR"
./setup.sh

mkdir -p "$HOME/.config/next-event"
cp calendars.example.txt "$HOME/.config/next-event/calendars.txt"
${EDITOR:-vi} "$HOME/.config/next-event/calendars.txt"
```

The plugin contains a `manifest.json` and a `bar-widget` entry point. Its
Python calendar logic remains separate from the QML presentation layer so the
CLI can be tested independently and other bars can consume it. The included
`runner.sh` uses the plugin's `.venv` when available, then falls back to `uv`
or the system Python.

To place it in the bar manually:

```bash
omarchy plugin enable io.github.noahbrier.next-event --section center
```

To validate the plugin during development:

```bash
omarchy plugin validate .
qmllint -I "$OMARCHY_PATH/shell" BarWidget.qml
```

## License

MIT. See [LICENSE](LICENSE).
