import os
import json
import time
import logging
import threading

import paho.mqtt.client as mqtt

BROKER_HOST = os.environ.get("AUTOMATION_BROKER", "localhost")
BROKER_PORT = int(os.environ.get("AUTOMATION_BROKER_PORT", "1883"))
MQTT_USER = os.environ.get("AUTOMATION_MQTT_USER")
MQTT_PASSWORD = os.environ.get("AUTOMATION_MQTT_PASSWORD")
SENSOR_TOPIC = "home/sensors/+/state"
RULE_TOPIC = "home/rules/+"
COMMAND_PREFIX = "home/devices"
MIN_INTERVAL_SECONDS = 30

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("rule-engine")

state = {}
rules = {}
last_fired = {}
lock = threading.Lock()


def parse_rule(name, payload):
    rule = json.loads(payload)
    condition = str(rule["condition"]).strip()
    device = str(rule["device"]).strip()
    command = rule["command"]
    if not condition or len(condition) > 300:
        raise ValueError("condition must be 1-300 characters")
    if not device.replace("_", "").replace("-", "").isalnum():
        raise ValueError("device ids may use letters, digits, - and _")
    if not isinstance(command, dict):
        raise ValueError("command must be an object")
    return {"name": name, "condition": condition, "device": device, "command": command,
            "enabled": bool(rule.get("enabled", True))}


def condition_holds(condition, snapshot):
    scope = {"hour": time.localtime().tm_hour, "weekday": time.localtime().tm_wday}
    scope.update(snapshot)
    return bool(eval(condition, {"__builtins__": {"min": min, "max": max, "abs": abs}}, scope))


def evaluate_rules(client):
    with lock:
        snapshot = dict(state)
        active = [r for r in rules.values() if r["enabled"]]
    now = time.monotonic()
    for rule in active:
        try:
            if not condition_holds(rule["condition"], snapshot):
                continue
        except (NameError, TypeError, ZeroDivisionError, SyntaxError) as exc:
            log.debug("Rule %s not evaluable yet: %s", rule["name"], exc)
            continue
        if now - last_fired.get(rule["name"], 0) < MIN_INTERVAL_SECONDS:
            continue
        last_fired[rule["name"]] = now
        topic = f"{COMMAND_PREFIX}/{rule['device']}/set"
        client.publish(topic, json.dumps(rule["command"]), qos=1)
        log.info("Rule %s fired -> %s %s", rule["name"], topic, rule["command"])


def handle_sensor(topic, payload):
    sensor = topic.split("/")[2]
    if not sensor.replace("_", "").isalnum():
        return
    try:
        value = json.loads(payload)
    except json.JSONDecodeError:
        value = payload.decode("utf-8", errors="replace").strip()
    if isinstance(value, dict):
        value = value.get("value")
    with lock:
        state[sensor] = value


def handle_rule(topic, payload):
    name = topic.split("/")[2]
    if not payload:
        with lock:
            rules.pop(name, None)
        log.info("Rule %s removed", name)
        return
    try:
        rule = parse_rule(name, payload)
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Ignoring rule %s: %s", name, exc)
        return
    with lock:
        rules[name] = rule
    log.info("Rule %s loaded: when %s", name, rule["condition"])


def on_connect(client, userdata, flags, reason_code, properties=None):
    log.info("Connected (%s)", reason_code)
    client.subscribe([(SENSOR_TOPIC, 0), (RULE_TOPIC, 1)])


def on_message(client, userdata, message):
    if message.topic.startswith("home/rules/"):
        handle_rule(message.topic, message.payload)
    else:
        handle_sensor(message.topic, message.payload)
        evaluate_rules(client)


def main():
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="rule-engine")
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        log.info("Stopping")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()