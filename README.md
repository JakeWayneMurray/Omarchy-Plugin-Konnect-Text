# Konnect Text

An Omarchy shell plugin for the small, useful part of KDE Connect: open the
five most recently texted conversations, read the thread, and send a reply.

It uses KDE Connect's public session D-Bus API and does not replace or modify
`kdeconnectd`. The plugin does not persist SMS content, contacts, device IDs,
or network addresses. Message text is passed to the helper over stdin rather
than as a process argument.

## Install

On an Omarchy system:

```sh
omarchy plugin add https://github.com/JakeWayneMurray/Omarchy-Plugin-Konnect-Text.git --enable
```

Then click the Konnect Text envelope in the bar. The plugin checks for KDE
Connect when opened and clearly distinguishes:

- **KDE Connect is not installed** — install KDE Connect first.
- **KDE Connect is not running** — start `kdeconnectd` or open KDE Connect.
- **No recent SMS conversations** — KDE Connect is available but no paired
  device currently exposes the SMS plugin.

## Requirements

- Omarchy with the Quickshell shell
- `kdeconnect-cli` and a paired device with the KDE Connect SMS plugin
- `busctl` from systemd
- Python 3 with `python-gobject` for the send operation

No credentials, certificates, pairing keys, or phone network details are
included in this repository. KDE Connect remains responsible for pairing,
encryption, discovery, and delivery.

## Development

Run the helper checks without changing any KDE Connect state:

```sh
python3 -m py_compile konnect-text.py
./konnect-text.py status
./konnect-text.py list
```

Validate the plugin from its checkout:

```sh
omarchy plugin validate .
qmllint -I "$OMARCHY_PATH/shell" BarWidget.qml Panel.qml
```

## Remove

```sh
omarchy plugin remove io.github.jakewaynemurray.konnect-text
```

## License

MIT
