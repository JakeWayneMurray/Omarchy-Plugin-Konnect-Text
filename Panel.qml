import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

Panel {
  id: root
  moduleName: "io.github.jakewaynemurray.konnect-text"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property bool checking: true
  property bool busy: false
  property bool installed: false
  property bool serviceAvailable: false
  property string statusText: ""
  property var devices: []
  property var conversations: []
  property var messages: []
  property var selectedConversation: null
  property int conversationIndex: 0
  property int requestGeneration: 0
  readonly property string helperPath: Qt.resolvedUrl("konnect-text.py").toString().replace("file://", "")
  readonly property var barIdentity: hostWidget || root

  function open() {
    root.controller.show()
    root.checkStatus()
  }

  function close() { root.controller.hide() }

  function toggle() {
    if (root.opened) root.close()
    else root.open()
  }

  function parseOutput(text, fallback) {
    try { return JSON.parse(String(text).trim()) }
    catch (error) { return {ok: false, error: fallback} }
  }

  function checkStatus() {
    root.checking = true
    root.statusText = ""
    statusProc.running = true
  }

  function refreshConversations() {
    if (root.busy || !root.serviceAvailable) return
    root.busy = true
    root.statusText = "Loading recent conversations…"
    listProc.running = true
  }

  function openConversation(conversation) {
    if (!conversation || root.busy) return
    root.selectedConversation = conversation
    root.messages = []
    root.busy = true
    root.statusText = "Loading conversation…"
    threadProc.command = [root.helperPath, "thread", String(conversation.deviceId), String(conversation.conversationId)]
    threadProc.running = true
  }

  function sendMessage() {
    if (!root.selectedConversation || root.busy || !composer.text.trim()) return
    root.busy = true
    root.statusText = "Sending message…"
    sendProc.command = [root.helperPath, "send", String(root.selectedConversation.deviceId), String(root.selectedConversation.conversationId)]
    sendProc.message = composer.text
    sendProc.running = true
  }

  function showList() {
    root.selectedConversation = null
    root.messages = []
    root.statusText = ""
    root.refreshConversations()
  }

  function moveConversationCursor(delta) {
    if (root.selectedConversation || root.checking || conversationList.count === 0) return
    root.conversationIndex = Math.max(0, Math.min(conversationList.count - 1, root.conversationIndex + delta))
    conversationList.positionViewAtIndex(root.conversationIndex, ListView.Contain)
  }

  function activateConversationCursor() {
    if (root.selectedConversation || root.checking || conversationList.count === 0) return
    var conversation = conversationList.model[root.conversationIndex]
    if (conversation) root.openConversation(conversation)
  }

  function formatTime(value) {
    var date = new Date(Number(value || 0))
    if (isNaN(date.getTime())) return ""
    return Qt.formatTime(date, "h:mm AP")
  }

  function formatDate(value) {
    var date = new Date(Number(value || 0))
    if (isNaN(date.getTime())) return ""
    return Qt.formatDate(date, "MMM d")
  }

  Component.onCompleted: root.checkStatus()
  onOpenedChanged: if (opened) root.checkStatus()

  Process {
    id: statusProc
    command: [root.helperPath, "status"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var data = root.parseOutput(text, "Could not check KDE Connect.")
        root.checking = false
        root.installed = data.installed === true
        root.serviceAvailable = data.serviceAvailable === true
        root.devices = data.devices || []
        if (!root.installed) {
          root.statusText = "KDE Connect is not installed."
        } else if (!root.serviceAvailable) {
          root.statusText = "KDE Connect is not running."
        } else {
          root.statusText = ""
          root.refreshConversations()
        }
      }
    }
  }

  Process {
    id: listProc
    command: [root.helperPath, "list"]
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var data = root.parseOutput(text, "Could not load conversations.")
        root.busy = false
        if (data.ok !== true) {
          root.statusText = String(data.error || "Could not load conversations.")
          return
        }
        root.conversations = data.conversations || []
        root.conversationIndex = 0
        root.statusText = root.conversations.length > 0 ? "" : "No recent SMS conversations."
      }
    }
  }

  Process {
    id: threadProc
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var data = root.parseOutput(text, "Could not load this conversation.")
        root.busy = false
        if (data.ok !== true) {
          root.statusText = String(data.error || "Could not load this conversation.")
          return
        }
        root.messages = data.messages || []
        root.statusText = root.messages.length > 0 ? "" : "No messages loaded yet."
        if (root.messages.length > 0) Qt.callLater(function() { composer.forceActiveFocus() })
      }
    }
  }

  Process {
    id: sendProc
    property string message: ""
    stdinEnabled: true
    onStarted: {
      write(message + "\n")
      message = ""
      stdinEnabled = false
    }
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var data = root.parseOutput(text, "Could not send message.")
        root.busy = false
        if (data.ok !== true) {
          root.statusText = String(data.error || "Could not send message.")
          return
        }
        composer.text = ""
        root.statusText = "Message sent."
        refreshDelay.restart()
      }
    }
  }

  Timer {
    id: refreshDelay
    interval: 500
    onTriggered: {
      if (root.selectedConversation) root.openConversation(root.selectedConversation)
      else root.refreshConversations()
    }
  }

  KeyboardPanel {
    id: popup
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: popup.fittedContentWidth(Style.space(520))
    contentHeight: popup.fittedContentHeight(content.implicitHeight, Style.space(700))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: searchField.activeFocus || composer.activeFocus
      onMoveRequested: function(dx, dy) { root.moveConversationCursor(dy) }
      onActivateRequested: root.activateConversationCursor()
      onCloseRequested: root.close()
    }

    Column {
      id: content
      anchors.left: parent.left
      anchors.right: parent.right
      anchors.top: parent.top
      spacing: Style.space(10)

      Row {
        width: parent.width
        spacing: Style.space(9)
        Text {
          text: root.selectedConversation ? "‹" : "✉"
          color: root.bar ? root.bar.foreground : Color.accent
          font.family: Style.font.family
          font.pixelSize: Style.font.display
          MouseArea { anchors.fill: parent; enabled: !!root.selectedConversation; onClicked: root.showList() }
        }
        Column {
          width: parent.width - Style.space(45)
          Text {
            text: root.selectedConversation ? String(root.selectedConversation.title) : "Konnect Text"
            color: root.bar ? root.bar.foreground : Color.foreground
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
            elide: Text.ElideRight
            width: parent.width
          }
          Text {
            text: root.selectedConversation ? String(root.selectedConversation.deviceName || "KDE Connect") : "Recent SMS conversations"
            color: Qt.darker(root.bar ? root.bar.foreground : Color.foreground, 1.45)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
            width: parent.width
          }
        }
      }

      Text {
        visible: root.checking
        text: "Checking KDE Connect…"
        color: Color.foreground
        font.family: Style.font.family
        font.pixelSize: Style.font.body
      }

      Column {
        visible: !root.checking && !root.selectedConversation
        width: parent.width
        spacing: Style.space(7)

        TextField {
          id: searchField
          width: parent.width
          placeholderText: "Search recent conversations…"
          Keys.onPressed: function(event) {
            if (event.key === Qt.Key_Escape) {
              root.close()
              event.accepted = true
            }
          }
        }

        ListView {
          id: conversationList
          width: parent.width
          height: Math.min(contentHeight, Style.space(430))
          clip: true
          spacing: Style.space(4)
          model: root.conversations.filter(function(item) {
            var query = searchField.text.trim().toLowerCase()
            return !query || String(item.title).toLowerCase().indexOf(query) >= 0
              || String(item.body).toLowerCase().indexOf(query) >= 0
          })
          delegate: Rectangle {
            required property var modelData
            required property int index
            width: ListView.view.width
            height: Style.space(64)
            radius: Style.cornerRadius
            color: conversationMouse.containsMouse ? Qt.alpha(Color.accent, 0.18) : Qt.alpha(Color.foreground, 0.055)
            border.width: 1
            border.color: index === root.conversationIndex ? Color.accent : Qt.alpha(Color.foreground, 0.09)
            RowLayout {
              anchors.fill: parent
              anchors.margins: Style.space(10)
              spacing: Style.space(10)
              Rectangle {
                Layout.preferredWidth: Style.space(34)
                Layout.preferredHeight: Style.space(34)
                radius: width / 2
                color: Qt.alpha(Color.accent, 0.2)
                Text {
                  anchors.centerIn: parent
                  text: String(modelData.title || "?").charAt(0).toUpperCase()
                  color: Color.accent
                  font.family: Style.font.family
                  font.bold: true
                }
              }
              ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                RowLayout {
                  Layout.fillWidth: true
                  Text {
                    Layout.fillWidth: true
                    text: String(modelData.title)
                    color: Color.foreground
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                    font.bold: modelData.read !== true
                    elide: Text.ElideRight
                  }
                  Text {
                    text: root.formatTime(modelData.dateMs)
                    color: Qt.darker(Color.foreground, 1.5)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                  }
                }
                Text {
                  Layout.fillWidth: true
                  text: String(modelData.body || "").replace(/\s+/g, " ")
                  color: Qt.darker(Color.foreground, 1.35)
                  font.family: Style.font.family
                  font.pixelSize: Style.font.caption
                  elide: Text.ElideRight
                }
              }
            }
            MouseArea {
              id: conversationMouse
              anchors.fill: parent
              hoverEnabled: true
              onClicked: {
                root.conversationIndex = index
                root.openConversation(modelData)
              }
            }
          }
        }
      }

      Column {
        visible: !root.checking && !!root.selectedConversation
        width: parent.width
        spacing: Style.space(7)

        Row {
          width: parent.width
          spacing: Style.space(7)
          Text {
            text: root.selectedConversation ? String(root.selectedConversation.participants.join(", ")) : ""
            color: Qt.darker(Color.foreground, 1.25)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
            width: parent.width - backButton.width - Style.space(7)
          }
          Button { id: backButton; text: "All"; bordered: true; onClicked: root.showList() }
        }

        ScrollView {
          width: parent.width
          height: Style.space(390)
          clip: true
          ListView {
            width: parent.width
            model: root.messages
            spacing: Style.space(6)
            delegate: Row {
              required property var modelData
              width: ListView.view.width
              layoutDirection: modelData.outgoing ? Qt.RightToLeft : Qt.LeftToRight
              Rectangle {
                width: Math.min(messageText.implicitWidth + Style.space(22), parent.width * 0.86)
                height: messageText.implicitHeight + Style.space(18)
                radius: Style.cornerRadius
                color: modelData.outgoing ? Qt.alpha(Color.accent, 0.23) : Qt.alpha(Color.foreground, 0.08)
                Text {
                  id: messageText
                  anchors.fill: parent
                  anchors.margins: Style.space(10)
                  text: String(modelData.body || "")
                  color: Color.foreground
                  font.family: Style.font.family
                  font.pixelSize: Style.font.body
                  wrapMode: Text.WordWrap
                }
              }
            }
          }
        }

        RowLayout {
          width: parent.width
          spacing: Style.space(7)
          TextField {
            id: composer
            Layout.fillWidth: true
            placeholderText: "Message…"
            enabled: !root.busy
            onAccepted: root.sendMessage()
            Keys.onPressed: function(event) {
              if (event.key === Qt.Key_Escape) {
                root.close()
                event.accepted = true
              }
            }
          }
          Button {
            text: root.busy ? "…" : "Send"
            bordered: true
            enabled: !root.busy && composer.text.trim().length > 0
            onClicked: root.sendMessage()
          }
        }
      }

      Text {
        visible: root.statusText.length > 0
        width: parent.width
        text: root.statusText
        color: root.statusText.indexOf("not installed") >= 0 || root.statusText.indexOf("failed") >= 0 || root.statusText.indexOf("Could not") >= 0 ? Color.urgent : Qt.darker(Color.foreground, 1.35)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        wrapMode: Text.WordWrap
      }
    }
  }
}
