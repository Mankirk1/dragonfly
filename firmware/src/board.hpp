// SPDX-License-Identifier: Apache-2.0
// Pin assignments and hardware constants for the ESP32 DevKit.
// ASSUMPTION: these are placeholders until the wiring is fixed. Update them
// together with the wiring diagram in docs/.
#pragma once

#include <cstdint>

namespace board {

constexpr int kRadarRxPin = 16;     // UART2 RX  <- RD-03D TX
constexpr int kRadarTxPin = 17;     // UART2 TX  -> RD-03D RX (configuration only)
constexpr std::uint32_t kRadarBaud = 256000;

constexpr int kDopplerAdcPin = 36;  // ADC1_CH0 (ADC1 only: ADC2 conflicts with Wi-Fi)

constexpr int kPanServoPin = 25;
constexpr int kTiltServoPin = 26;

constexpr int kLaserEnablePin = 27;  // drives the laser transistor; HIGH = on
constexpr int kArmSwitchPin = 14;    // arm switch sense, active LOW with pull-up

constexpr std::uint32_t kTelemetryBaud = 460800;

}  // namespace board
