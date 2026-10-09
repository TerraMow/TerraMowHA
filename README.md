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
- Start mowing a single zone
- Monitor battery status and activity
- Track the current session: mowed area, mowing time, and progress
- Diagnose problems with the latest event, active fault, and mission status sensors
- View the map status and a map image with the mowing path and robot position
- Adjust mowing height, speed, blade speed, edge cutting distance, spacing, and main direction
- Track blade and base station maintenance and the next scheduled start
- MQTT based real-time communication

See [Entities](docs/en/entities.md) for what each entity shows and when it is unknown or unavailable.

### Installation

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=TerraMow&repository=TerraMowHA&category=Integration)

#### Method 1: HACS (Recommended)
1. Make sure [HACS](https://hacs.xyz/) is installed
2. Use the button above to add to HACS
3. Go to HACS → Integrations → + → Search for "TerraMow"
4. Install and restart Home Assistant

#### Method 2: Manual Installation
1. Copy the `custom_components/terramow` folder to your Home Assistant `/config/custom_components` folder
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "TerraMow" and follow the configuration steps

### Configuration

The following parameters are required:
- **Host**: IP address or hostname of the TerraMow device
- **Password**: MQTT password for authentication

To change either value later, open Settings → Devices & Services → TerraMow and
choose **Reconfigure** from the integration's menu. Existing entities and their
names are retained. An address already used by another TerraMow configuration
cannot be selected.

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
