import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

BarWidget {
  id: root
  moduleName: "io.github.noahbrier.next-event"

  property string displayText: ""
  property string displayTooltip: ""
  property string displayClass: ""
  property string errorText: ""
  property bool forceRefreshPending: false

  readonly property int refreshIntervalSec: intSetting("refreshIntervalSec", 60, 30, 3600)
  readonly property string runnerPath: localPath("runner.sh")
  readonly property string configuredPythonPath: String(setting("pythonPath", "") || "").trim()
  readonly property bool hasDisplay: displayText.trim() !== ""
  readonly property color displayColor: {
    if (!bar) return Color.foreground
    if (displayClass === "started") return bar.urgent
    if (displayClass === "soon") return Color.accent
    if (displayClass === "ongoing") return Color.muted
    return bar.barForeground
  }

  function intSetting(name, fallback, minimum, maximum) {
    var value = parseInt(String(setting(name, fallback)), 10)
    if (!isFinite(value)) value = fallback
    return Math.max(minimum, Math.min(maximum, value))
  }

  function localPath(relativePath) {
    var value = String(Qt.resolvedUrl(relativePath))
    if (value.indexOf("file://") === 0) value = value.substring(7)
    return decodeURIComponent(value)
  }

  function refresh(forceRefresh) {
    if (statusProcess.running) {
      if (forceRefresh === true && statusProcess.command.indexOf("--force-refresh") === -1) {
        forceRefreshPending = true
      }
      return
    }
    var command
    if (configuredPythonPath !== "") {
      command = [configuredPythonPath, root.scriptPath()]
    } else {
      command = [root.runnerPath]
    }
    if (forceRefresh === true) command.push("--force-refresh")
    statusProcess.command = command
    statusProcess.running = true
  }

  function forceRefresh() {
    refresh(true)
  }

  function applyOutput(raw) {
    var parsed
    try {
      parsed = JSON.parse(String(raw || "").trim())
    } catch (error) {
      showError("Calendar output was not valid JSON")
      return
    }

    if (!parsed || typeof parsed !== "object") {
      showError("Calendar output was empty")
      return
    }

    displayText = String(parsed.text || "")
    displayTooltip = String(parsed.tooltip || "")
    displayClass = String(parsed.class || "")
    errorText = ""
  }

  function showError(message) {
    errorText = String(message || "Calendar unavailable")
    displayText = "Calendar setup"
    displayTooltip = errorText + "\nRun setup.sh in the plugin directory."
    displayClass = "none"
  }

  function openMeeting() {
    var command = configuredPythonPath !== ""
      ? [configuredPythonPath, root.scriptPath(), "--open"]
      : [root.runnerPath, "--open"]
    Quickshell.execDetached(command)
  }

  function openCalendar() {
    Quickshell.execDetached(["xdg-open", "https://calendar.google.com"])
  }

  function scriptPath() {
    return localPath("next-event")
  }

  visible: hasDisplay
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  Component.onCompleted: Qt.callLater(root.refresh)
  onSettingsChanged: Qt.callLater(root.refresh)

  IpcHandler {
    target: root.moduleName

    function refresh(): void { root.broadcast("forceRefresh") }
    function open(): void { root.openMeeting() }
  }

  Process {
    id: statusProcess
    command: []

    stdout: StdioCollector {
      id: statusStdout
      waitForEnd: true
    }

    stderr: StdioCollector {
      id: statusStderr
      waitForEnd: true
    }

    onExited: function(exitCode) {
      var stdout = String(statusStdout.text || "")
      var stderr = String(statusStderr.text || "").trim()
      if (exitCode === 0) root.applyOutput(stdout)
      else root.showError(stderr || stdout || ("Calendar helper exited with code " + exitCode))
      if (root.forceRefreshPending) {
        root.forceRefreshPending = false
        root.refresh(true)
      }
    }
  }

  Timer {
    interval: root.refreshIntervalSec * 1000
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: root.refresh()
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.displayText
    tooltipText: root.displayTooltip || root.errorText || "Next calendar event"
    foreground: root.displayColor
    horizontalMargin: 8.75
    verticalPadding: 8.75

    onPressed: function(buttonCode) {
      if (buttonCode === Qt.MiddleButton) root.forceRefresh()
      else if (buttonCode === Qt.RightButton) root.openCalendar()
      else root.openMeeting()
    }
  }
}
