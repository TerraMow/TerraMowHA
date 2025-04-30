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

- Home Assistant 2023.9.3 or later (tested with 2025.1.1)
- TerraMow firmware version 6.6.0 or later
- TerraMow APP version 1.6.0 or later

### Support

Open an issue on [GitHub](https://github.com/TerraMow/TerraMowHA/issues) for support.

### Developer Information

For developers interested in understanding or extending this integration, please refer to the [Developer Guide](docs/en/developers.md).

---

## License

This project is licensed under the GNU General Public License v3.0 - see the [LICENSE](LICENSE) file for details.