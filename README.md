# TerraMow for Home Assistant

<div align="center">
  <p>
    <a href="#english-version"><img src="https://img.shields.io/badge/English-blue?style=for-the-badge" alt="English"/></a>
    <a href="docs/README_zh.md"><img src="https://img.shields.io/badge/中文-red?style=for-the-badge" alt="中文"/></a>
  </p>
  <img src="docs/images/terramow_logo.png" alt="TerraMow Logo" width="400">
</div>

---

<a id="english-version"></a>

This is a Home Assistant integration for TerraMow robotic lawn mowers.

### Features

- Control lawn mower (start, pause, and dock)
- Monitor battery status and activity
- MQTT based real-time communication

Control actions wait up to five seconds for a matching robot reply. A rejected
command raises a Home Assistant error; a timeout means the result is unconfirmed
and the integration does not retry automatically. Firmware that does not send
command replies will also report an unconfirmed result. Acceptance of a command
does not imply mowing has begun: activity still follows the robot's mission state.

The diagnostic **Last Event** sensor exposes the latest event code, time, and
description. **Active Fault** shows `0` when the robot reports no faults and the
first fault code when faults are present; its attributes contain all active faults.
Both sensors are unknown until feedback arrives. A current fault also sets the
mower activity to `error`; clearing the fault restores the reported mission state.
Historical events do not set the current fault state. The mower's
`back_to_station_reason` attribute explains a return to the station.

### Installation

#### Method 1: HACS (Recommended)
1. Make sure [HACS](https://hacs.xyz/) is installed
2. Go to HACS → Integrations → Three dots menu (⋮) → Custom repositories
3. Add `https://github.com/TerraMow/TerraMowHA` as repository URL with category "Integration"
4. Go to HACS → Integrations → + → Search for "TerraMow"
5. Install and restart Home Assistant

#### Method 2: Manual Installation
1. Copy the `custom_components/terramow` folder to your Home Assistant `/config/custom_components` folder
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "TerraMow" and follow the configuration steps

### Configuration

The following parameters are required:
- **Host**: IP address or hostname of the TerraMow device
- **Password**: MQTT password for authentication

### Requirements

- Home Assistant 2025.3.4 or later (development is tested against 2025.3.4 and the current stable release)
- TerraMow firmware version 6.6.0 or later
- TerraMow APP version 1.6.0 or later

### Development

The recommended development environment is included in this repository. It runs
Home Assistant and all Python dependencies in a VS Code dev container, without
installing packages on the host. See [CONTRIBUTING.md](CONTRIBUTING.md) for the
one-click setup, debugger, tests, and the optional full Home Assistant Core mode.

### Support

Open an issue on [GitHub](https://github.com/TerraMow/TerraMowHA/issues) for support.

### Developer Information

For developers interested in understanding or extending this integration, please refer to the [Developer Guide](docs/en/developers.md).

---

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.
