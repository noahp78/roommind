# Electrical load forecast

Open RoomMind's **Configure** option under **Settings → Devices & services**. In **Electricity forecasts**, enter one mapping entry per physical electrical system. Use Home Assistant area IDs for its rooms.

```yaml
living_room:
  rooms: [living_room]
  max_electrical_kw: 2.4
  standby_kw: 0.025
  heat_thermal_kw: 4.0
  heating_cop: 3.2
  heating_cop_per_degree: 0.05
  cool_thermal_kw: 3.0
  cooling_cop: 3.5
  power_sensor: sensor.living_room_ac_power
```

This creates `sensor.roommind_living_room_electricity_forecast`. Add it as a forecast sensor in Battery Controller. If you have a separate cumulative electricity meter for the same system, choose **Separately measured** there and select that meter. This allows Battery Controller to remove the system's historical share before adding the predicted draw.

`max_electrical_kw` and `rooms` are required. Thermal capacity and COP are optional. When capacity is given, electrical draw is modeled as thermal capacity divided by COP, scaled by the MPC modulation fraction and bounded by the rated electrical maximum. The optional heating COP slope applies per degree Celsius from 7 °C and uses the MPC outdoor weather forecast. With electrical rating alone, modulation scales the draw above standby. A dedicated optional W or kW sensor adjusts a bounded moving estimate from valid running samples during the current RoomMind session.

For multiple rooms sharing one heat pump, list them together under one system ID. The sensor uses the highest simultaneous room demand and one standby load. Assign each independent meter to one provider. A room with multiple devices on the same electrical system can use their combined rating and dedicated circuit meter. The shared system estimate is approximate when several zone heads modulate independently. The room controller does not predict per-head allocation throughout its horizon.

The sensor projects the actual MPC action and modulation sequence, including price-shifted setpoints and preheat/precool. It substitutes the first action after RoomMind's runtime checks. Later actions can change as room temperatures, weather, presence, equipment limits and prices change. Managed rooms or rooms still learning their thermal model may have no suitable MPC trajectory. Their forecast stays unknown and the consumer can continue with its historical estimate.

The sensor attributes use the [version 1 forecast contract](https://github.com/noahp78/battery_controller/blob/feature/external-load-forecasts/docs/external-load-forecasts.md#version-1-sensor-attributes). They contain absolute intervals with rated or estimated power. The entity state is the power of the first interval.

## Test installation

This optional feature uses the existing RoomMind distribution layout. For a branch checkout, build its normal frontend first.

```shell
cd frontend
npm ci
npm run build
```

Copy `custom_components/roommind/` including the generated assets into the test instance's `config/custom_components/`, and restart Home Assistant. Use the upstream requirements for its Home Assistant version.
