# Resolume integration for Home Assistant

This custom integration exposes a Resolume Arena/Avenue server to Home Assistant.

## Features

* Devices for every Layer, Layer-Group and the Composition
* Entities
  * Clip trigger buttons and clip thumbnails (camera entities)
  * Layer: Clear, Bypass, Solo, Opacity, Blend-mode
  * Layer-Group: Clear, Solo, Bypass, Master level
  * Composition: BPM, Crossfader, Master level

## Requirements

* Resolume Websocket API enabled (Arena ≥ 7.13) – default port 8080.
* Home Assistant 2023.8 or later.

## Installation

1. Copy this repository to `config/custom_components/resolume/` **or** add the repo to HACS » Custom Repositories.
2. Restart Home Assistant or reload custom integrations.

## Configuration

1. Go to *Settings → Devices & Services*.
2. Click *Add Integration* and search for "Resolume".
3. Enter the host name or IP address and the websocket port (default 8080).

After a few seconds the integration will create the devices and entities.  All entities update live; no polling interval is required.

## Lovelace example

A sample dashboard that resembles the Resolume web UI is provided in `resolume_dashboard.yaml`.  Import it as a YAML dashboard and ensure the following custom cards are installed from HACS:

* `button-card`
* `auto-entities`
* `slider-entity-row`

## Troubleshooting

Enable debug logging to watch websocket traffic:

```yaml
logger:
  default: warn
  logs:
    custom_components.resolume: debug
```
