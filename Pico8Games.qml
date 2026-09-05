import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import qs.Ui
import qs.Commons

// PICO-8 Widget - a daily PICO-8 game in the bar.
//
// The bar shows a single gamepad icon:
//   left click  -> popup with today's game: cover, title, description,
//                  an "Open in browser" link, bookmark (heart) and
//                  "roll another" (circle-arrow)
//   right click -> the bookmarked games list
//
// All data work happens in p8.py (fetched through the one Process below and
// serialized through a small job queue); this file is stateless UI only.
// User data lives in ~/.local/share/guy.pico-8-widget/. See README.md.

Panel {
  id: root
  moduleName: "guy.pico-8-widget"

  // ------------------------------------------------------------------
  // theming helpers
  // (Panel already provides barForeground; bar is injected after the
  // component is created, so every color/font has a non-bar fallback.)
  // ------------------------------------------------------------------

  readonly property string uiFontFamily: root.bar ? root.bar.fontFamily : Style.font.family

  // ------------------------------------------------------------------
  // state: today's game + bookmarks
  // ------------------------------------------------------------------

  property int gameTid: 0              // BBS thread id of today's game
  property string gameTitle: ""
  property string gameUrl: ""
  property string gameDesc: ""
  property string gameThumb: ""        // absolute path of the cached cover
  property bool gameFavorite: false    // is the current game bookmarked?
  property int roll: 0                 // current roll for today
  property var favorites: []           // bookmark entries from p8.py
  property bool showFavorites: false   // which popup page is visible
  property bool busy: false            // a helper job is in flight
  property string message: ""          // transient status ("offline", ...)

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // ------------------------------------------------------------------
  // helper process + serialized job queue
  //
  // p8.py lives next to this file; Qt resolves it from the QML source
  // path so the plugin stays relocatable.
  // ------------------------------------------------------------------

  readonly property string helperPath: {
    var path = String(Qt.resolvedUrl("p8.py"))
    if (path.indexOf("file://") === 0) path = path.substring(7)
    try { path = decodeURIComponent(path) } catch (e) { /* keep as-is */ }
    return path
  }

  // One Process serves every request. Jobs queue up because Quickshell's
  // Process can only run one command at a time (a running Process cannot be
  // re-run); each job carries the argv plus a completion callback.
  property var jobs: []
  property var currentJob: null
  property bool jobHandled: true

  function run(args, onDone) {
    root.jobs.push({ args: args, done: onDone })
    root.pump()
  }

  function pump() {
    if (p8Proc.running) return
    if (!root.currentJob && root.jobs.length > 0) root.currentJob = root.jobs.shift()
    if (!root.currentJob) return
    root.jobHandled = false
    p8Proc.command = root.currentJob.args
    p8Proc.running = true
    watchdog.restart()
  }

  function finishCurrent(result) {
    if (root.jobHandled) return
    root.jobHandled = true
    watchdog.stop()
    var callback = root.currentJob ? root.currentJob.done : null
    root.currentJob = null
    if (callback) callback(result)
    root.pump()
  }

  // p8.py prints exactly one JSON object; take the last brace-initialized
  // line so stray warnings above it are harmless.
  function parseHelperOutput(text) {
    var lines = String(text || "").split("\n")
    for (var i = lines.length - 1; i >= 0; i--) {
      var line = lines[i].trim()
      if (line.charAt(0) === "{") {
        try { return JSON.parse(line) } catch (e) { return null }
      }
    }
    return null
  }

  Process {
    id: p8Proc

    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        if (!root.currentJob) return
        var result = root.parseHelperOutput(text)
        root.finishCurrent(result || { ok: false, error: "unreadable helper output" })
      }
    }

    // Fire in every stop path so a job can never wedge the queue.
    onRunningChanged: {
      if (!running && !root.jobHandled) root.finishCurrent({ ok: false, error: "helper timed out" })
    }

    onExited: function(exitCode) {
      if (!root.jobHandled) root.finishCurrent({ ok: false, error: "helper exited " + exitCode })
    }
  }

  // A hung helper (bad network) would otherwise block the queue forever.
  // Bumped past p8.py's worst case (description + cover fetches, each up to
  // ~2 attempts x 10s) so slow sites fail in p8.py, not here.
  Timer {
    id: watchdog
    interval: 60000
    onTriggered: {
      if (p8Proc.running) p8Proc.running = false // onRunningChanged finishes the job
    }
  }

  // ------------------------------------------------------------------
  // data commands
  // ------------------------------------------------------------------

  // Retry state for loadToday: failed lookups are retried a couple of times
  // a few seconds apart so a single slow response doesn't surface as
  // "offline" (the BBS occasionally stalls connections).
  // Retry state for loadToday: failed lookups are retried a couple of times
  // a few seconds apart so a single slow response doesn't surface as
  // "offline" (the BBS occasionally stalls connections). retryRoll is a var
  // because "undefined" means "restore today's pick" (no explicit roll).
  property var retryRoll: undefined
  property int retryLeft: 0

  Timer {
    id: retryTimer
    interval: 4000
    onTriggered: {
      root.message = "Looking for today's game…"
      root.loadToday(root.retryRoll, root.retryLeft)
    }
  }

  function scheduleRetry(rollArg, remaining) {
    root.retryRoll = rollArg
    root.retryLeft = remaining
    retryTimer.restart()
  }

  function refreshPool() {
    run(["python3", root.helperPath, "refresh"], function(result) {
      // Never clears busy here: a loadToday queued behind this refresh owns
      // the busy flag, and clobbering it would let a second load start.
      if (!result || !result.ok) {
        if (root.gameTid === 0) root.message = "Couldn't reach lexaloffle.com…"
      }
    })
  }

  // With no argument, restores today's pick from disk (stable across shell
  // restarts); with a roll number, explicitly picks that roll (the ↻ button).
  // Failures retry automatically `retries` times before showing the offline
  // message, so a first click usually needs no second one.
  function loadToday(explicitRoll, retries) {
    if (root.busy) return
    if (retries === undefined || retries === null) retries = 2
    retryTimer.stop()
    root.busy = true
    root.message = root.gameTid === 0 ? "Looking for today's game…" : ""
    var args = ["python3", root.helperPath, "pick"]
    if (explicitRoll !== undefined && explicitRoll !== null) {
      args.push("--roll", String(explicitRoll))
    }
    run(args, function(result) {
      root.busy = false
      if (result && result.ok) {
        root.roll = Number(result.roll)
        root.gameTid = result.tid
        root.gameTitle = result.title || ""
        root.gameUrl = result.url || ""
        root.gameDesc = result.description || ""
        root.gameThumb = result.thumb || ""
        root.gameFavorite = !!result.favorite
        root.message = ""
        root.refreshFavorites()
      } else if (result && result.error === "pool empty") {
        // First run ever: warm the pool, then retry the pick once it is there.
        root.message = "Building the game pool…"
        root.refreshPool()
        if (retries > 0) root.scheduleRetry(explicitRoll, retries - 1)
      } else if (retries > 0) {
        root.message = "Couldn't reach lexaloffle.com — retrying…"
        root.scheduleRetry(explicitRoll, retries - 1)
      } else {
        root.message = "PICO-8 is offline — click to try again."
      }
    })
  }

  function rollAnother() {
    if (root.busy) return
    root.loadToday(root.roll + 1)
  }

  function toggleFavorite() {
    if (root.gameTid <= 0 || root.busy) return
    var action = root.gameFavorite ? "remove" : "add"
    run(["python3", root.helperPath, "favorite", action,
         String(root.gameTid), root.gameTitle], function() {
      root.refreshFavorites()
    })
  }

  function removeFavorite(tid) {
    run(["python3", root.helperPath, "favorite", "remove", String(tid)], function() {
      root.refreshFavorites()
    })
  }

  function refreshFavorites() {
    run(["python3", root.helperPath, "favorite", "list"], function(result) {
      if (!result || !result.ok) return
      root.favorites = result.favorites || []
      var isFavorite = false
      for (var i = 0; i < root.favorites.length; i++) {
        if (Number(root.favorites[i].tid) === root.gameTid) { isFavorite = true; break }
      }
      root.gameFavorite = isFavorite
    })
  }

  // ------------------------------------------------------------------
  // opening links
  // ------------------------------------------------------------------

  function bbsUrl(tid) {
    return "https://www.lexaloffle.com/bbs/?tid=" + tid
  }

  function openGame() {
    if (root.gameUrl !== "") openUrl(root.gameUrl)
  }

  function openUrl(url) {
    if (url === "") return
    // Launch through the bar host (the path the stock widgets use);
    // shellQuote keeps the URL safe.
    if (root.bar) root.bar.run("xdg-open " + Util.shellQuote(url))
  }

  // ------------------------------------------------------------------
  // lifecycle
  // ------------------------------------------------------------------

  Connections {
    target: root
    function onOpenedChanged() {
      if (!root.opened) return
      if (root.gameTid === 0 && !root.busy) root.loadToday()
      else root.refreshFavorites()
    }
  }

  Component.onCompleted: {
    // Warm the pool (a no-op on days it already ran), then today's game,
    // then the bookmarks — all serialized through the one helper process.
    refreshPool()
    loadToday()
    refreshFavorites()
  }

  // Re-check hourly: rolls the pick over at midnight and refreshes the pool
  // once per day. Both calls are cheap no-ops when nothing is due.
  Timer {
    id: dailyTimer
    interval: 60 * 60 * 1000
    running: true
    repeat: true
    onTriggered: {
      refreshPool()
      loadToday()
    }
  }

  // ------------------------------------------------------------------
  // bar icon
  // ------------------------------------------------------------------

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: "\uf11b" // gamepad glyph (Font Awesome 6)

    tooltipText: root.busy ? "PICO-8…"
      : (root.message !== "" ? root.message
        : (root.gameTitle !== "" ? root.gameTitle + " — PICO-8"
          : "PICO-8 daily game"))

    onPressed: function(buttonPressed) {
      if (buttonPressed === Qt.RightButton) {
        root.showFavorites = !root.showFavorites
        root.toggle()
      } else if (buttonPressed === Qt.LeftButton) {
        root.toggle()
      }
    }
  }

  // ------------------------------------------------------------------
  // popup
  // ------------------------------------------------------------------

  KeyboardPanel {
    id: popup
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    contentWidth: popup.fittedContentWidth(Style.space(400))
    contentHeight: popup.fittedContentHeight(view.implicitHeight, Style.space(580))

    // Popup pages swap by visibility; Qt positioners skip invisible items,
    // so only the visible page contributes to the popup height.
    Column {
      id: view
      width: parent.width
      spacing: Style.spacing.panelGap

      // ----- today's game --------------------------------------------

      Column {
        id: todayView
        width: parent.width
        spacing: Style.spacing.controlGap
        visible: !root.showFavorites

        Image {
          id: cover
          width: parent.width
          height: root.gameThumb === "" ? 0 : Style.space(168)
          fillMode: Image.PreserveAspectFit
          source: root.gameThumb
          sourceSize.width: 512
          smooth: false
          visible: height > 0

          // The cover is a link too.
          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openGame()
          }
        }

        // Title (clickable) or the transient status message.
        Text {
          id: titleText
          width: parent.width
          textFormat: Text.PlainText
          text: root.gameTitle !== "" ? root.gameTitle : root.message
          color: root.barForeground
          font.family: root.uiFontFamily
          font.pixelSize: Style.font.title
          font.bold: true
          wrapMode: Text.WordWrap
          visible: root.gameTitle !== "" || root.message !== ""

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: if (root.gameUrl !== "") root.openGame()
          }
        }

        // The unmistakable open link, right under the title.
        Row {
          width: parent.width
          visible: root.gameUrl !== "" && root.gameTitle !== ""

          MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: root.openGame()
          }

          Text {
            textFormat: Text.PlainText
            text: "\u25b6 Open in browser on lexaloffle.com \u2197"
            color: root.barForeground
            font.family: root.uiFontFamily
            font.pixelSize: Style.font.body
            font.bold: true
            font.underline: true
          }
        }

        // Manual retry once the automatic attempts are exhausted.
        Button {
          visible: root.gameTid === 0 && root.message === "PICO-8 is offline — click to try again."
          text: "Try again"
          foreground: root.barForeground
          fontFamily: root.uiFontFamily
          onClicked: root.loadToday()
        }

        // Description, scrollable when long, hidden when absent.
        ScrollView {
          id: descScroll
          width: parent.width
          visible: root.gameDesc !== ""
          height: visible ? Math.min(Style.space(210), descText.implicitHeight + Style.space(4)) : 0
          implicitHeight: height
          clip: true
          ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
          ScrollBar.vertical.policy: ScrollBar.AsNeeded

          Text {
            id: descText
            width: descScroll.availableWidth
            textFormat: Text.PlainText
            text: root.gameDesc
            color: root.barForeground
            font.family: root.uiFontFamily
            font.pixelSize: Style.font.body
            lineHeight: 1.25
            wrapMode: Text.WordWrap
          }
        }

        // Actions: bookmark + roll another, left-aligned.
        Row {
          width: parent.width
          height: actionsRow.implicitHeight

          Row {
            id: actionsRow
            spacing: Style.spacing.controlGap

            PanelActionButton {
              id: favButton
              iconText: root.gameFavorite ? "\u2665" : "\u2661" // ♥ / ♡
              foreground: root.barForeground
              hoverColor: root.gameFavorite ? root.bar.urgent : root.barForeground
              fontFamily: root.uiFontFamily
              fontSize: Style.font.icon
              tooltipText: root.gameFavorite ? "Remove bookmark" : "Bookmark this game"
              enabled: root.gameTid > 0
              onClicked: root.toggleFavorite()
            }

            PanelActionButton {
              id: nextButton
              iconText: "\u21bb" // ↻
              foreground: root.barForeground
              fontFamily: root.uiFontFamily
              fontSize: Style.font.icon
              tooltipText: "Roll another game for today"
              enabled: !root.busy && root.gameTid > 0
              onClicked: root.rollAnother()
            }
          }

          // Right-side spacer keeps the actions left-aligned.
          Item {
            width: parent.width - actionsRow.implicitWidth
            height: 1
          }
        }
      }

      // ----- bookmarks -------------------------------------------------

      Column {
        id: favsView
        width: parent.width
        spacing: Style.spacing.controlGap
        visible: root.showFavorites

        Row {
          width: parent.width
          spacing: Style.spacing.controlGap

          Button {
            id: backButton
            text: "\u2039 Back"
            foreground: root.barForeground
            fontFamily: root.uiFontFamily
            onClicked: root.showFavorites = false
          }

          Text {
            textFormat: Text.PlainText
            text: "Saved (" + root.favorites.length + ")"
            color: root.barForeground
            font.family: root.uiFontFamily
            font.pixelSize: Style.font.subtitle
            anchors.verticalCenter: parent.verticalCenter
          }
        }

        ScrollView {
          id: favScroll
          width: parent.width
          visible: root.favorites.length > 0
          height: visible ? Math.min(Style.space(320), favList.implicitHeight + Style.space(4)) : 0
          implicitHeight: height
          clip: true
          ScrollBar.horizontal.policy: ScrollBar.AlwaysOff
          ScrollBar.vertical.policy: ScrollBar.AsNeeded

          Column {
            id: favList
            width: favScroll.availableWidth
            spacing: Style.spacing.xxs

            Repeater {
              model: root.favorites

              // One row per bookmark: tap anywhere to open, ✕ to remove.
              delegate: Row {
                required property var modelData
                width: favList.width
                height: Style.spacing.popupRowHeight
                spacing: Style.spacing.controlGap

                MouseArea {
                  anchors.fill: parent
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.openUrl(root.bbsUrl(Number(modelData.tid)))
                }

                Text {
                  textFormat: Text.PlainText
                  text: modelData.title
                  color: root.barForeground
                  font.family: root.uiFontFamily
                  font.pixelSize: Style.font.body
                  elide: Text.ElideRight
                  width: parent.width - removeButton.implicitWidth - parent.spacing
                  anchors.verticalCenter: parent.verticalCenter
                }

                PanelActionButton {
                  id: removeButton
                  iconText: "\u2715" // ✕
                  foreground: root.barForeground
                  fontFamily: root.uiFontFamily
                  fontSize: Style.font.caption
                  tooltipText: "Remove bookmark"
                  onClicked: root.removeFavorite(Number(modelData.tid))
                }
              }
            }
          }
        }

        Text {
          textFormat: Text.PlainText
          text: "Nothing saved yet — bookmark a game with the heart."
          color: Qt.darker(root.barForeground, 1.4)
          font.family: root.uiFontFamily
          font.pixelSize: Style.font.bodySmall
          wrapMode: Text.WordWrap
          width: parent.width
          visible: root.favorites.length === 0
        }
      }
    }
  }
}
