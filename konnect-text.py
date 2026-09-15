#!/usr/bin/env python3
"""Small KDE Connect adapter for the Omarchy Konnect Text plugin.

The helper uses KDE Connect's public session D-Bus API. It deliberately keeps
message text out of process arguments and does not persist messages, contacts,
device IDs, or network addresses.
"""

import datetime as _datetime
import json
import os
import shutil
import subprocess
import sys
import time


BUS = "org.kde.kdeconnect"
ROOT_PATH = "/modules/kdeconnect"
DAEMON_IFACE = "org.kde.kdeconnect.daemon"
DEVICE_IFACE = "org.kde.kdeconnect.device"
CONVERSATION_IFACE = "org.kde.kdeconnect.device.conversations"
MAX_MESSAGE_BYTES = 64 * 1024
HISTORY_LIMIT = 10
CONVERSATION_SYNC_QUIET_SECONDS = 0.35
CONVERSATION_SYNC_TIMEOUT_SECONDS = 4.0
EVENT_MULTI_TARGET = 2


def output(value):
    json.dump(value, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")


def run_busctl(arguments, timeout=10):
    if shutil.which("busctl") is None:
        return None
    command = ["busctl", "--user", "--no-pager"] + list(arguments)
    try:
        return subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def run_json_call(path, interface, method, signature="", *arguments):
    call = ["--json=short", "call", BUS, path, interface, method]
    if signature:
        call.append(signature)
        call.extend(str(argument) for argument in arguments)
    result = run_busctl(call)
    if result is None or result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (TypeError, ValueError):
        return None


def service_available():
    result = run_busctl(["status", BUS], timeout=3)
    return result is not None and result.returncode == 0


def unwrap(value):
    if isinstance(value, dict) and "data" in value:
        return value["data"]
    return value


def device_path(device_id):
    return ROOT_PATH + "/devices/" + device_id


def device_ids():
    response = run_json_call(
        ROOT_PATH, DAEMON_IFACE, "devices", "bb", "false", "false"
    )
    if not response:
        return []
    try:
        return [str(value) for value in response["data"][0]]
    except (KeyError, TypeError):
        return []


def device_properties(device_id):
    response = run_json_call(
        device_path(device_id),
        "org.freedesktop.DBus.Properties",
        "GetAll",
        "s",
        DEVICE_IFACE,
    )
    if not response:
        return {}
    try:
        values = response["data"][0]
    except (KeyError, IndexError, TypeError):
        return {}
    return {key: unwrap(value) for key, value in values.items()}


def devices():
    result = []
    for device_id in device_ids():
        props = device_properties(device_id)
        plugins = [str(value) for value in props.get("supportedPlugins", [])]
        result.append(
            {
                "deviceId": device_id,
                "name": str(props.get("name") or "Unnamed device"),
                "paired": bool(props.get("isPaired")),
                "reachable": bool(props.get("isReachable")),
                "supportsSms": "kdeconnect_sms" in plugins,
            }
        )
    return result


def conversation_response(device_id, request_all=True):
    path = device_path(device_id)
    if request_all:
        wait_for_conversation_sync(device_id)
    response = run_json_call(path, CONVERSATION_IFACE, "activeConversations")
    if not response:
        return []
    try:
        return response["data"][0]
    except (KeyError, IndexError, TypeError):
        return []


def wait_for_conversation_sync(device_id):
    """Wait for KDE Connect's asynchronous conversation refresh to settle."""
    path = device_path(device_id)
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception:
        # Keep compatibility with installations that can read D-Bus through
        # busctl but do not have PyGObject available for signal handling.
        run_busctl(["call", BUS, path, CONVERSATION_IFACE, "requestAllConversationThreads"], timeout=8)
        time.sleep(1.0)
        return

    loop = GLib.MainLoop()
    state = {"seen": False, "lastSignal": 0.0}

    def on_loaded(_connection, _sender, object_path, interface, signal, _parameters, _data):
        if object_path == path and interface == CONVERSATION_IFACE and signal == "conversationLoaded":
            state["seen"] = True
            state["lastSignal"] = time.monotonic()

    def finish_when_quiet():
        if state["seen"] and time.monotonic() - state["lastSignal"] >= CONVERSATION_SYNC_QUIET_SECONDS:
            loop.quit()
            return False
        return True

    subscription = bus.signal_subscribe(
        BUS,
        CONVERSATION_IFACE,
        "conversationLoaded",
        path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_loaded,
        None,
    )
    try:
        bus.call_sync(
            BUS,
            path,
            CONVERSATION_IFACE,
            "requestAllConversationThreads",
            None,
            None,
            Gio.DBusCallFlags.NONE,
            8000,
            None,
        )
        GLib.timeout_add(100, finish_when_quiet)
        GLib.timeout_add(int(CONVERSATION_SYNC_TIMEOUT_SECONDS * 1000), loop.quit)
        loop.run()
    except Exception:
        pass
    finally:
        bus.signal_unsubscribe(subscription)


def phone_key(number):
    return "".join(character for character in str(number) if character.isdigit())


def contact_names(device_id):
    """Read KDE Connect's existing vCard cache without creating a new cache."""
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "share"
    )
    directory = os.path.join(data_home, "kpeoplevcard", "kdeconnect-" + device_id)
    names = {}
    try:
        entries = os.scandir(directory)
    except OSError:
        return names
    with entries:
        for entry in entries:
            if not entry.is_file() or not entry.name.lower().endswith((".vcf", ".vcard")):
                continue
            try:
                with open(entry.path, "r", encoding="utf-8", errors="replace") as card:
                    name = ""
                    numbers = []
                    for line in card:
                        line = line.rstrip("\n\r")
                        if line.startswith("FN:"):
                            name = line[3:].strip()
                        elif line.upper().startswith("TEL") and ":" in line:
                            numbers.append(line.split(":", 1)[1].strip())
                    if name:
                        for number in numbers:
                            key = phone_key(number)
                            if key:
                                names[key] = name
            except OSError:
                continue
    return names


def parse_message(raw, device, names):
    if not isinstance(raw, dict):
        return None
    data = raw.get("data")
    if not isinstance(data, list) or len(data) < 9:
        return None
    addresses = []
    raw_addresses = data[2] if isinstance(data[2], (list, tuple)) else []
    for address in raw_addresses:
        if isinstance(address, list):
            addresses.extend(str(value) for value in address)
        elif isinstance(address, tuple):
            addresses.extend(str(value) for value in address)
        else:
            addresses.append(str(address))
    addresses = [address for address in addresses if address]
    try:
        event_field = int(data[0])
        date_ms = int(data[3])
        message_type = int(data[4])
        # KDE Connect's ConversationMessage layout is:
        # event, body, addresses, date, type, read, threadId, messageId,
        # subId, attachments.
        conversation_id = str(data[6])
        message_id = int(data[7])
    except (TypeError, ValueError, IndexError):
        return None
    participants = [names.get(phone_key(address), address) for address in addresses]
    unique_participants = list(dict.fromkeys(participants))
    if len(unique_participants) > 3:
        title = ", ".join(unique_participants[:3]) + " +" + str(len(unique_participants) - 3)
    else:
        title = ", ".join(unique_participants) or "Unknown conversation"
    is_group = bool(event_field & EVENT_MULTI_TARGET) or len(unique_participants) > 1
    sender = ""
    if is_group:
        if message_type == 1 and addresses:
            sender = names.get(phone_key(addresses[0]), addresses[0])
        elif message_type != 1:
            sender = "You"
    return {
        "deviceId": device["deviceId"],
        "deviceName": device["name"],
        "conversationId": conversation_id,
        "messageId": message_id,
        "body": str(data[1] or ""),
        "addresses": addresses,
        "participants": unique_participants,
        "title": title,
        "isGroup": is_group,
        "sender": sender,
        "dateMs": date_ms,
        "date": _datetime.datetime.fromtimestamp(
            date_ms / 1000, tz=_datetime.timezone.utc
        ).astimezone().isoformat(timespec="minutes"),
        "incoming": message_type == 1,
        "outgoing": message_type != 1,
        "read": bool(data[5]),
    }


def all_conversations():
    result = []
    for device in devices():
        if not device["paired"] or not device["supportsSms"]:
            continue
        names = contact_names(device["deviceId"])
        for raw in conversation_response(device["deviceId"]):
            message = parse_message(raw, device, names)
            if message and message["conversationId"]:
                result.append(message)
    result.sort(key=lambda item: item["dateMs"], reverse=True)
    return result


def find_device(device_id):
    for device in devices():
        if device["deviceId"] == device_id:
            return device
    return None


def thread(device_id, conversation_id):
    device = find_device(device_id)
    if not device or not device["paired"] or not device["supportsSms"]:
        return None, "SMS is unavailable on the selected device."
    path = device_path(device_id)
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except Exception as exc:
        return None, "python-gobject is required to load SMS history: " + str(exc)

    loop = GLib.MainLoop()
    names = contact_names(device_id)
    received = []
    received_ids = set()
    expected_count = None

    def add_message(fields):
        if not isinstance(fields, (tuple, list)):
            return
        parsed = parse_message({"data": list(fields)}, device, names)
        if (
            parsed
            and parsed["conversationId"] == str(conversation_id)
            and parsed["messageId"] not in received_ids
        ):
            received_ids.add(parsed["messageId"])
            received.append(parsed)

    def on_loaded(_connection, _sender, object_path, interface, signal, parameters, _data):
        if object_path != path or interface != CONVERSATION_IFACE or signal != "conversationLoaded":
            return
        values = parameters.unpack()
        if values and str(values[0]) == str(conversation_id):
            nonlocal expected_count
            try:
                expected_count = int(values[1])
            except (IndexError, TypeError, ValueError):
                expected_count = None
            if expected_count is not None and len(received) >= min(HISTORY_LIMIT, expected_count):
                loop.quit()

    def on_updated(_connection, _sender, object_path, interface, signal, parameters, _data):
        if object_path != path or interface != CONVERSATION_IFACE or signal != "conversationUpdated":
            return
        values = parameters.unpack()
        if values:
            add_message(values[0])
        if len(received) >= HISTORY_LIMIT:
            loop.quit()

    subscription = bus.signal_subscribe(
        BUS,
        CONVERSATION_IFACE,
        "conversationLoaded",
        path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_loaded,
        None,
    )
    updated_subscription = bus.signal_subscribe(
        BUS,
        CONVERSATION_IFACE,
        "conversationUpdated",
        path,
        None,
        Gio.DBusSignalFlags.NONE,
        on_updated,
        None,
    )
    try:
        bus.call_sync(
            BUS,
            path,
            CONVERSATION_IFACE,
            "requestConversation",
            GLib.Variant("(xii)", (int(conversation_id), 0, HISTORY_LIMIT)),
            None,
            Gio.DBusCallFlags.NONE,
            8000,
            None,
        )
        # Requested messages arrive as conversationUpdated signals. Keep a
        # bounded timeout for older KDE Connect versions or a disconnected
        # phone, but stop as soon as the requested ten messages arrive.
        GLib.timeout_add(4000, loop.quit)
        loop.run()
    except Exception as exc:
        return None, "KDE Connect could not request this conversation: " + str(exc)
    finally:
        bus.signal_unsubscribe(subscription)
        bus.signal_unsubscribe(updated_subscription)

    # Keep the direct D-Bus signal results as the authoritative history. The
    # activeConversations property intentionally contains only one summary
    # message per thread, so it is only a compatibility fallback here.
    messages = received
    if not messages:
        for raw in conversation_response(device_id, request_all=False):
            add_message(raw.get("data") if isinstance(raw, dict) else None)
    messages.sort(key=lambda item: (item["dateMs"], item["messageId"]))
    return messages, ""


def send_message(device_id, conversation_id, text):
    if not text.strip():
        return False, "Message text cannot be empty."
    if len(text.encode("utf-8")) > MAX_MESSAGE_BYTES:
        return False, "Message is too large."
    device = find_device(device_id)
    if not device or not device["paired"] or not device["supportsSms"]:
        return False, "SMS is unavailable on the selected device."
    try:
        import gi

        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except Exception as exc:
        return False, "python-gobject is required for sending SMS: " + str(exc)
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        parameters = GLib.Variant("(xsav)", (int(conversation_id), text, []))
        bus.call_sync(
            BUS,
            device_path(device_id),
            CONVERSATION_IFACE,
            "replyToConversation",
            parameters,
            None,
            Gio.DBusCallFlags.NONE,
            10000,
            None,
        )
        return True, ""
    except Exception as exc:
        return False, str(exc)


def main():
    verb = sys.argv[1] if len(sys.argv) > 1 else "status"
    installed = shutil.which("kdeconnect-cli") is not None
    available = installed and service_available()
    if verb == "status":
        output(
            {
                "ok": True,
                "installed": installed,
                "serviceAvailable": available,
                "devices": devices() if available else [],
            }
        )
        return 0
    if not installed:
        output({"ok": False, "error": "KDE Connect is not installed.", "installed": False})
        return 1
    if not available:
        output({"ok": False, "error": "KDE Connect is not running.", "installed": True})
        return 1
    if verb == "list":
        output({"ok": True, "conversations": all_conversations()[:5]})
        return 0
    if verb == "thread" and len(sys.argv) >= 3:
        messages, error = thread(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
        if messages is None:
            output({"ok": False, "error": error})
            return 1
        output({"ok": True, "messages": messages})
        return 0
    if verb == "send" and len(sys.argv) >= 4:
        text = sys.stdin.buffer.read(MAX_MESSAGE_BYTES + 1).decode("utf-8", "replace")
        if text.endswith("\n"):
            text = text[:-1]
        ok, error = send_message(sys.argv[2], sys.argv[3], text)
        output({"ok": ok, **({} if ok else {"error": error})})
        return 0 if ok else 1
    output({"ok": False, "error": "Unknown command."})
    return 2


if __name__ == "__main__":
    sys.exit(main())
