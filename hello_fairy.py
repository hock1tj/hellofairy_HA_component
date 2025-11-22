"""Low-level BLE control for Hello Fairy lights."""
from __future__ import annotations

import asyncio
import enum
import logging
from typing import Any, Callable

from bleak import BleakClient, BleakError
from bleak.backends.client import BaseBleakClient
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# This UUID is the "command" characteristic used by Hello Fairy lights,
# derived from the original reverse engineering docs. :contentReference[oaicite:5]{index=5}
CONTROL_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"


class ConnState(enum.Enum):
    """Connection state."""

    DISCONNECTED = 1
    CONNECTING = 2
    CONNECTED = 3


class HelloFairyLamp:
    """Represents a single Hello Fairy BLE device."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        """Initialize the Hello Fairy lamp wrapper."""
        self._hass = hass
        self._address = address.upper()

        self._client: BleakClient | None = None
        self._conn_state = ConnState.DISCONNECTED
        self._conn_lock = asyncio.Lock()

        self._is_on = False
        self._rgb: tuple[int, int, int] = (255, 255, 255)
        self._brightness = 100  # 0–100%

        self._state_callbacks: list[Callable[[], None]] = []

    # ---------------------------------------------------------------------
    # State callback helpers
    # ---------------------------------------------------------------------
    def add_callback_on_state_changed(self, func: Callable[[], None]) -> None:
        """Register a callback called when state changes."""
        self._state_callbacks.append(func)

    def _run_state_changed_callbacks(self) -> None:
        for cb in self._state_callbacks:
            try:
                cb()
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Error in state callback")

    # ---------------------------------------------------------------------
    # BLE connection & command handling
    # ---------------------------------------------------------------------
    def _disconnected_cb(self, client: BaseBleakClient) -> None:
        """Handle BLE disconnect."""
        _LOGGER.debug("Disconnected callback from client %s (%s)", client, self._address)

        # Ignore callbacks from stale clients
        if client is not self._client:
            return

        self._client = None
        self._conn_state = ConnState.DISCONNECTED
        self._run_state_changed_callbacks()

    async def _ensure_connected(self) -> None:
        """Ensure there is a connected BleakClient."""
        async with self._conn_lock:
            if self._client and self._client.is_connected:
                return

            self._conn_state = ConnState.CONNECTING

            ble_device = bluetooth.async_ble_device_from_address(
                self._hass, self._address, connectable=True
            )
            if ble_device is None:
                self._conn_state = ConnState.DISCONNECTED
                raise BleakError(
                    f"No connectable Bluetooth adapter found for {self._address}"
                )

            _LOGGER.debug(
                "Connecting to Hello Fairy device %s (%s)", ble_device.name, ble_device
            )

            try:
                self._client = await establish_connection(
                    BleakClient,
                    device=ble_device,
                    name=self._address,
                    disconnected_callback=self._disconnected_cb,
                    max_attempts=4,
                )
            except (asyncio.TimeoutError, BleakError) as err:
                self._conn_state = ConnState.DISCONNECTED
                _LOGGER.error(
                    "Failed to connect to Hello Fairy %s: %s", self._address, err
                )
                raise

            _LOGGER.debug(
                "Connected to Hello Fairy %s; client=%s",
                self._address,
                self._client,
            )
            self._conn_state = ConnState.CONNECTED

    async def _send_cmd(self, payload: bytes, wait: float = 0.3) -> bool:
        """Send a raw command to the control characteristic."""
        async with self._conn_lock:
            try:
                await self._ensure_connected()
            except (asyncio.TimeoutError, BleakError):
                return False

            if self._client is None:
                return False

            try:
                await self._client.write_gatt_char(CONTROL_UUID, payload)
                if wait > 0:
                    await asyncio.sleep(wait)
                return True
            except asyncio.TimeoutError:
                _LOGGER.error("Timeout sending command to %s", self._address)
            except BleakError as err:
                _LOGGER.error(
                    "Bleak error sending command to %s: %s", self._address, err
                )

            return False

    async def disconnect(self) -> None:
        """Disconnect the client."""
        async with self._conn_lock:
            if self._client is None:
                return
            try:
                await self._client.disconnect()
            except BleakError:
                _LOGGER.debug(
                    "Ignoring error while disconnecting from %s", self._address,
                    exc_info=True,
                )
            self._client = None
            self._conn_state = ConnState.DISCONNECTED

    # ---------------------------------------------------------------------
    # Public properties
    # ---------------------------------------------------------------------
    @property
    def address(self) -> str:
        return self._address

    @property
    def available(self) -> bool:
        return self._conn_state is ConnState.CONNECTED

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int:
        """Brightness 0–100."""
        return self._brightness

    @property
    def color(self) -> tuple[int, int, int]:
        """RGB color 0–255."""
        return self._rgb

    def get_prop_min_max(self) -> dict[str, Any]:
        """Expose ranges to the entity."""
        return {
            "brightness": {"min": 0, "max": 100},
            "color": {"min": 0, "max": 255},
        }

    # ---------------------------------------------------------------------
    # High-level commands
    # ---------------------------------------------------------------------
    async def turn_on(self) -> None:
        """Turn the lamp on (aa020101bb)."""
        payload = bytes.fromhex("aa020101bb")
        _LOGGER.debug("Send Cmd: Turn On to %s", self._address)
        if await self._send_cmd(payload):
            self._is_on = True
            self._run_state_changed_callbacks()

    async def turn_off(self) -> None:
        """Turn the lamp off (aa020100bb)."""
        payload = bytes.fromhex("aa020100bb")
        _LOGGER.debug("Send Cmd: Turn Off to %s", self._address)
        if await self._send_cmd(payload):
            self._is_on = False
            self._run_state_changed_callbacks()

    async def set_brightness(self, brightness: int) -> None:
        """Set brightness 0–100.

        NOTE: This still uses the 'orange' sample payload as a placeholder.
        You can refine this once you fully reverse the protocol for brightness.
        """
        brightness = max(0, min(100, int(brightness)))
        _LOGGER.debug("Set_brightness %s on %s", brightness, self._address)

        # Placeholder – uses one known valid payload, same as upstream.
        payload = bytes.fromhex("aa030701001403e8038cbb")
        if await self._send_cmd(payload, wait=0):
            self._brightness = brightness
            self._run_state_changed_callbacks()

    async def set_color(
        self,
        red: int,
        green: int,
        blue: int,
        brightness: int | None = None,
    ) -> None:
        """Set RGB color (0–255 each).

        NOTE: Currently uses a static "orange" payload as a stand-in command,
        since the full encoding for arbitrary colors is not fully documented.
        You can later map (R,G,B,brightness) into the correct bytes once known.
        """
        red = max(0, min(255, int(red)))
        green = max(0, min(255, int(green)))
        blue = max(0, min(255, int(blue)))

        if brightness is None:
            brightness = self._brightness
        brightness = max(0, min(100, int(brightness)))

        _LOGGER.debug(
            "Set_color (%s, %s, %s), brightness=%s on %s",
            red,
            green,
            blue,
            brightness,
            self._address,
        )

        # Placeholder "set color" payload from reverse engineering examples.
        payload = bytes.fromhex("aa030701001403e8038cbb")

        if await self._send_cmd(payload, wait=0):
            self._rgb = (red, green, blue)
            self._brightness = brightness
            self._is_on = True
            self._run_state_changed_callbacks()