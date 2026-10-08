# PID Departure Boards → Home Assistant

[Čeština](README.cs.md)

[![GitHub Release](https://img.shields.io/github/release/hondzik/pid-departure-boards.svg?style=for-the-badge)](https://github.com/hondzik/pid-departure-boards/releases)
[![License](https://img.shields.io/github/license/hondzik/pid-departure-boards.svg?style=for-the-badge)](LICENSE)
[![Project Maintenance](https://img.shields.io/badge/maintainer-hondzik-blue.svg?style=for-the-badge)](https://github.com/hondzik)
![Github](https://img.shields.io/github/followers/hondzik.svg?style=for-the-badge)
[![GitHub Activity](https://img.shields.io/github/last-commit/hondzik/pid-departure-boards?style=for-the-badge)](https://github.com/hondzik/pid-departure-boards/commits/main)

## Description

Home Assistant integration that shows departures of Prague Integrated Transport (PID)
for the platforms you choose. Data comes from the [Golemio API](https://api.golemio.cz/pid/docs/openapi/).

- One **sensor per platform** (a stop in one direction). The state is the time of the next
  departure; the `departures` attribute lists the next N departures of the lines you track.
- Each departure has the line, destination, scheduled and predicted time, delay in minutes,
  vehicle type, low-floor and air-conditioning flags, and cancellation / night / regional /
  replacement-transport flags. The `infotexts` attribute holds current notices (diversions).
- The sensor also has `latitude` / `longitude` attributes of the platform, so it appears on the
  Map card (see [Location](#location)).
- Services `pid_departure_boards.refresh` and `pid_departure_boards.get_departures`.

## Installation

### HACS

[![Open in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hondzik&repository=pid-departure-boards&category=integration)

1. HACS → Integrations → three dots → Custom repositories.
2. Add `https://github.com/hondzik/pid-departure-boards` as an "Integration".
3. Install "PID Departure Boards" and restart Home Assistant.

### Manual

Copy `custom_components/pid_departure_boards` to `<config>/custom_components/pid_departure_boards`
and restart Home Assistant.

## Setup

1. Create a free API key at <https://api.golemio.cz/api-keys>.
2. Settings → Devices & services → Add integration → "PID Departure Boards", enter the key.
   Global settings are in the integration options, see [Options](#options).
3. On the integration page choose **Add stop**:
   - search the stop by name (diacritics are optional),
   - choose the platform — each one serves one direction, shown as
     `platform — destinations (lines)`,
   - choose the lines to track (empty = all),
   - set the number of departures and, optionally, a refresh interval for this stop.

Lines, number of departures and interval can be changed later via **Reconfigure**.

## Options

Settings → Devices & services → PID Departure Boards → **Configure**. They apply to the whole
integration, i.e. to all stops the same way:

| Option | Default | Description |
|---|---|---|
| Default refresh interval | 60 s | How often departures are refreshed (minimum 30 s — the API allows 20 requests per 8 seconds per key). A single stop can override it when added or reconfigured. |

Saving the options reloads the integration.

## History (recorder)

The large `departures` and `infotexts` attributes are **never** stored in the Home Assistant
history — the integration excludes them itself. Only the sensor state (the time of the next
departure) is recorded.

If you do not want even that, exclude the sensors in the [recorder](https://www.home-assistant.io/integrations/recorder/)
configuration in `configuration.yaml`. The entity ID is derived from the stop name, e.g.
`sensor.andel_b`:

```yaml
recorder:
  exclude:
    entities:
      - sensor.andel_b
      - sensor.palmovka_a
```

Entity IDs are not prefixed with the integration name, so `entity_globs` is only practical if you
rename the sensors to a common prefix. Already stored history is not removed by the exclusion;
delete it with the `recorder.purge_entities` service.

## Location

Since version **1.1.0** the sensor of each platform has the attributes `latitude` and `longitude`
(WGS84), taken from the PID stop list when the stop is added. Thanks to them the sensor can be
shown on the **Map** card.

Stops added **before version 1.1.0 do not have the location** and it is not filled in
automatically. To add it, remove the stop and add it again (**Add stop**).

## Services

| Service | Purpose |
|---|---|
| `pid_departure_boards.refresh` | Refresh now — all stops, or only the given sensors. |
| `pid_departure_boards.get_departures` | Returns departures (and notices) as a response. Give either a `entity_id` of a sensor, or a GTFS `stop_id`; `routes` and `limit` are optional overrides. |

## Notes

- Delay is only known when the vehicle reports its position; otherwise the scheduled time is used.
- The list of stops is downloaded once and cached for 7 days.
- The Lovelace card lives in a separate repository, `pid-departure-boards-ui`.
