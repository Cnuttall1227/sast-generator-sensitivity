import os
import json
import time
import socket
import logging
import platform

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("AGENT_BROKER_HOST", "mqtt.example.local")
BROKER_PORT = int(os.environ.get("AGENT_BROKER_PORT", "8883"))
DEVICE_ID = os.environ.get("AGENT_DEVICE_ID", socket.gethostname())
CA_CERT = os.environ.get("AGENT_CA_CERT", "/etc/kiosk-agent/ca.pem")
CLIENT_CERT = os.environ.get("AGENT_CLIENT_CERT", "/etc/kiosk-agent/device.pem")
CLIENT_KEY = os.environ.get("AGENT_CLIENT_KEY", "/etc/kiosk-agent/device.key")
WIFI_INTERFACE = os.environ.get("AGENT_WIFI_IFACE", "wlan0")
HEARTBEAT_SECONDS = 30

COMMAND_TOPIC = f"kiosks/{DEVICE_ID}/commands"
STATUS_TOPIC = f"kiosks/{DEVICE_ID}/status"
RESULT_TOPIC = f"kiosks/{DEVICE_ID}/results"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("kiosk-agent")


def read_uptime():
    with open("/proc/uptime", "r", encoding="ascii") as handle:
        return int(float(handle.read().split()[0]))


def status_payload():
    load1, load5, load15 = os.getloadavg()
    return {
        "device": DEVICE_ID,
        "platform": platform.platform(),
        "uptime_seconds": read_uptime(),
        "load": [round(load1, 2), round(load5, 2), round(load15, 2)],
        "timestamp": int(time.time()),
    }


def connect_wifi(ssid, passphrase):
    if not ssid.isprintable() or not passphrase.isprintable():
        raise ValueError("ssid and passphrase must not contain control characters")
    if not 1 <= len(ssid.encode("utf-8")) <= 32:
        raise ValueError("ssid must be 1-32 bytes")
    if not 8 <= len(passphrase) <= 63:
        raise ValueError("passphrase must be 8-63 characters")
    log.info("Switching %s to network %s", WIFI_INTERFACE, ssid)
    exit_code = os.spawnlp(
        os.P_WAIT,
        "nmcli", "nmcli",
        "device", "wifi", "connect", ssid,
        "password", passphrase,
        "ifname", WIFI_INTERFACE,
    )
    return {"ok": exit_code == 0, "exit_code": exit_code}

def set_volume(level):
    level = int(level)
    if not 0 <= level <= 100:
        raise ValueError("volume must be 0-100")
    exit_code = os.spawnlp(os.P_WAIT, "amixer", "amixer", "-q", "sset", "Master", f"{level}%")
    return {"ok": exit_code == 0, "volume": level}


def handle_command(command):
    action = command.get("action")
    if action == "ping":
        return {"ok": True, "pong": int(time.time())}
    if action == "status":
        return {"ok": True, **status_payload()}
    if action == "volume":
        return set_volume(command.get("level", 50))
    if action == "wifi":
        ssid = str(command.get("ssid", ""))
        passphrase = str(command.get("passphrase", ""))
        if not ssid or len(ssid) > 32:
            raise ValueError("ssid must be 1-32 characters")
        if not 8 <= len(passphrase) <= 63:
            raise ValueError("passphrase must be 8-63 characters")
        return connect_wifi(ssid, passphrase)
    raise ValueError(f"unknown action {action!r}")


def on_connect(client, userdata, flags, reason_code, properties=None):
    log.info("Connected to broker (%s)", reason_code)
    client.subscribe(COMMAND_TOPIC, qos=1)
    client.publish(STATUS_TOPIC, json.dumps({"online": True}), qos=1, retain=True)


def on_message(client, userdata, message):
    try:
        command = json.loads(message.payload.decode("utf-8"))
        request_id = command.get("id")
        result = handle_command(command)
    except (ValueError, UnicodeDecodeError) as exc:
        request_id, result = None, {"ok": False, "error": str(exc)}
    result["id"] = request_id
    client.publish(RESULT_TOPIC, json.dumps(result), qos=1)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"kiosk-{DEVICE_ID}")
    client.tls_set(ca_certs=CA_CERT, certfile=CLIENT_CERT, keyfile=CLIENT_KEY)
    client.will_set(STATUS_TOPIC, json.dumps({"online": False}), qos=1, retain=True)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()
    try:
        while True:
            client.publish(STATUS_TOPIC, json.dumps({"online": True, **status_payload()}), qos=0)
            time.sleep(HEARTBEAT_SECONDS)
    except KeyboardInterrupt:
        log.info("Shutting down")
    finally:
        client.publish(STATUS_TOPIC, json.dumps({"online": False}), qos=1, retain=True)
        client.loop_stop()
        client.disconnect()

