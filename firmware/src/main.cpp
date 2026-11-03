// SPDX-License-Identifier: Apache-2.0
// Dragonfly ESP32 firmware entry point.
//
// Start-up order matters for safety: the laser output is driven LOW before
// anything else runs, and the interlock starts disarmed. The tracker and the
// Doppler pipeline are not ported to C++ yet, so for now the system state is
// always SEARCH and the laser can never switch on.
#include <Arduino.h>
#include <esp_task_wdt.h>

#include "aim.hpp"
#include "board.hpp"
#include "interlock.hpp"
#include "rd03d.hpp"

namespace {

df::Rd03dParser g_parser;
df::Interlock g_interlock;
df::Frame g_last_frame;
volatile std::uint32_t g_last_frame_ms = 0;
constexpr std::uint32_t kWatchdogTimeoutS = 2;

void laser_off() { digitalWrite(board::kLaserEnablePin, LOW); }

void radar_task(void*) {
    esp_task_wdt_add(nullptr);
    for (;;) {
        while (Serial2.available() > 0) {
            df::Frame f;
            if (g_parser.push(static_cast<std::uint8_t>(Serial2.read()), f)) {
                g_last_frame = f;
                g_last_frame_ms = millis();
            }
        }
        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void control_task(void*) {
    esp_task_wdt_add(nullptr);
    TickType_t wake = xTaskGetTickCount();
    for (;;) {
        const bool armed = digitalRead(board::kArmSwitchPin) == LOW;
        const float telemetry_age_s =
            static_cast<float>(millis() - g_last_frame_ms) / 1000.0f;
        // Until the tracker is ported, there is never a target to aim at.
        const df::InterlockInputs in{armed, false, true, telemetry_age_s,
                                     df::SystemState::Search, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f};
        const bool on = g_interlock.laser_on(in);
        digitalWrite(board::kLaserEnablePin, on ? HIGH : LOW);
        esp_task_wdt_reset();
        vTaskDelayUntil(&wake, pdMS_TO_TICKS(20));  // 50 Hz
    }
}

}  // namespace

void setup() {
    pinMode(board::kLaserEnablePin, OUTPUT);
    laser_off();  // first action after reset
    pinMode(board::kArmSwitchPin, INPUT_PULLUP);

    Serial.begin(board::kTelemetryBaud);
    Serial2.begin(board::kRadarBaud, SERIAL_8N1, board::kRadarRxPin, board::kRadarTxPin);

    esp_task_wdt_init(kWatchdogTimeoutS, true);  // reset on hang; laser pin resets LOW
    xTaskCreatePinnedToCore(radar_task, "radar", 4096, nullptr, 3, nullptr, 0);
    xTaskCreatePinnedToCore(control_task, "control", 4096, nullptr, 4, nullptr, 1);
}

void loop() { vTaskDelay(pdMS_TO_TICKS(1000)); }
