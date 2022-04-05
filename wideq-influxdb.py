#!/usr/bin/env python3

import json
import sys
import time

import influxdb
import wideq


STATE_FILE = "wideq_state.json"


CONFIG_FILE_PATH = "/etc/swarm-gateway/lgwideq.conf"
INFLUX_CONFIG_FILE_PATH = "/etc/swarm-gateway/influx.conf"

# Get LG wideq config.
lg_config = {}
with open(CONFIG_FILE_PATH) as f:
    for l in f:
        fields = l.split("=")
        if len(fields) == 2:
            lg_config[fields[0].strip()] = fields[1].strip()

# Get influxDB config.
influx_config = {}
with open(INFLUX_CONFIG_FILE_PATH) as f:
    for l in f:
        fields = l.split("=")
        if len(fields) == 2:
            influx_config[fields[0].strip()] = fields[1].strip()


with open(STATE_FILE) as f:
    state = json.load(f)
client = wideq.Client.load(state)


tags = {
    "device_id": lg_config["device_id"],
    "location_general": lg_config["location_general"],
}

print("Logging in...")

while True:
    try:
        device = client.get_device(lg_config["device_id"])
        tags["model_id"] = device.model_id
        tags["name"] = device.name
        tags["type"] = device.type

        model = client.model_info(device)
        break

    except wideq.NotLoggedInError:
        client.refresh()


print("Getting dryer state.")

fields = {}

with wideq.Monitor(client.session, lg_config["device_id"]) as mon:

    # Loop because the first requests don't usually work.
    while True:
        data = mon.poll()
        if data:
            try:
                res = model.decode_monitor(data)

                for key, value in res.items():
                    try:
                        desc = model.value(key)
                    except KeyError:
                        continue

                    if isinstance(desc, wideq.EnumValue):
                        enum_val = desc.options.get(value, value)
                        if not enum_val == "-":
                            fields[key] = desc.options.get(value, value)

                    elif isinstance(desc, wideq.RangeValue):
                        fields[key] = value

                if "Remain_Time_H" in fields and "Remain_Time_M" in fields:
                    fields["remaining_minutes"] = 60 * int(
                        fields["Remain_Time_H"]
                    ) + int(fields["Remain_Time_M"])
                    del fields["Remain_Time_H"]
                    del fields["Remain_Time_M"]

                if "Initial_Time_H" in fields and "Initial_Time_M" in fields:
                    fields["starting_minutes"] = 60 * int(
                        fields["Initial_Time_H"]
                    ) + int(fields["Initial_Time_M"])
                    del fields["Initial_Time_H"]
                    del fields["Initial_Time_M"]

                if "MoreLessTime" in fields:
                    fields["more_less_time_minutes"] = int(fields["MoreLessTime"])
                    del fields["MoreLessTime"]

                print(fields)

                break
            except ValueError:
                print("status data: {!r}".format(data))

        time.sleep(1)


point = {
    "measurement": "lg_dryer",
    "fields": fields,
    "tags": tags,
}

influx_client = influxdb.InfluxDBClient(
    influx_config["url"],
    influx_config["port"],
    influx_config["username"],
    influx_config["password"],
    influx_config["database"],
    ssl=True,
    gzip=True,
    verify_ssl=True,
)
influx_client.write_points([point])
