# TerraMow Developer Guide

This document provides development information about the TerraMow Home Assistant integration component, helping developers understand the code structure and extend functionality.


<!-- @import "[TOC]" {cmd="toc" depthFrom=2 depthTo=6 orderedList=false} -->

<!-- code_chunk_output -->

- [Communication Method](#communication-method)
- [MQTT Topics Definition](#mqtt-topics-definition)

<!-- /code_chunk_output -->

## Communication Method

Communication between TerraMow and Home Assistant is primarily through the MQTT protocol. To simplify configuration, we don't use the MQTT Broker on the Home Assistant side, but instead have built a lightweight MQTT Broker into TerraMow. This way, during setup, you only need to enter the TerraMow IP and password.

It's worth noting that TerraMow's MQTT Broker uses the default port 1883 and does not enable SSL/TLS encryption, so it's best to use it within a local network and ensure your Wifi network has appropriate encryption (WPA/WPA2).

## MQTT Topics Definition

In TerraMow, the main data protocol is defined in units of Data Points. To achieve bidirectional communication, TerraMow needs to publish the state of data points to Home Assistant via MQTT Topics, while also listening to topics published by Home Assistant to receive commands.

The topic definitions related to Data Points are as follows:

| Topic | Description |
| ------- | ------ |
| data_point/{dp_id}/robot | Direction of messages published by the robot (from robot to application) |
| data_point/{dp_id}/app | Direction of messages published to the robot (from application to robot) |

Where `{dp_id}` is the ID of the Data Point, an integer ranging from 0 to 200.

For specific Data Point definitions, please refer to [Data Point Definition](./developers/data_point.md).