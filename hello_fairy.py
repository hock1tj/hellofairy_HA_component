"""BLE control for Hello Fairy LED device."""
from __future__ import annotations

import asyncio
import enum
import logging
from typing import Callable, Optional

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection
from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Known Hello Fairy characteristics
CONTROL_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"  # Exposed but not used
CMD_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"      # Write commands
NTF_UUID = "49535343-1E4D-4BD9-BA61-23C647249616"      # Notifications


class ConnState(enum.Enum):
    DISCONNECTED = 1
    CONNECTING = 2
    CONNECTED = 3


class HelloFairyLamp:
    """Hello Fairy BLE device wrapper."""

    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self._hass = hass
        self._address = address.upper()

        self._client: Optional[BleakClient] = None
        self._conn_state = ConnState.DISCONNECTED
        self._conn_lock = asyncio.Lock()

        self._is_on = False
        self._rgb = (255, 255, 255)
        self._brightness = 100

        self._callbacks: list[Callable[[], None]] = []

    # ----------------------------------------------------------------------
    # Callback registration
    # ----------------------------------------------------------------------
    def add_callback_on_state_changed(self, cb: Callable[[], None]) -> None:
        """Registers callback for state change."""
        self._callbacks.append(cb)

    def _notify_state_change(self) -> None:
        for cb in self._callbacks:
            try:
                cb()
            except Exception:
                _LOGGER.exception("State callback error")

    # ----------------------------------------------------------------------
    # Notification handler
    # ----------------------------------------------------------------------
    def _notification_handler(self, handle: int, data: bytearray) -> None:
        """Handle incoming BLE notifications."""
        _LOGGER.debug(
            "Notification from %s (handle %s): %s",
            self._address,
            handle,
            data.hex(),
        )
        # TODO: decode notification format once protocol known

    # ----------------------------------------------------------------------
    # BLE disconnect handler
    # ----------------------------------------------------------------------
    def _handle_disconnect(self, client: BleakClient) -> None:
        if client is not self._client:
            return
        _LOGGER.debug("BLE disconnected from %s", self._address)
        self._client = None
        self._conn_state = ConnState.DISCONNECTED
        self._notify_state_change()

    # ----------------------------------------------------------------------
    # BLE connection handling
    # ----------------------------------------------------------------------
    async def _ensure_connected(self) -> None:
        """Ensure BLE connection is active."""
        async with self._conn_lock:

            if self._client and self._client.is_connected:
                return

            # Lookup BLEDevice from HA Bluetooth Scanner
            device = bluetooth.async_ble_device_from_address(
                self._hass, self._address, connectable=True
            )

            if not device:
                raise BleakError(
                    f"BLE device {self._address} not found in Home Assistant Bluetooth registry"
                )

            _LOGGER.debug("Connecting to %s using %s", self._address, device)
            self._conn_state = ConnState.CONNECTING

            try:
                self._client = await establish_connection(
                    BleakClient,
                    device=device,
                    name=self._address,
                    disconnected_callback=self._handle_disconnect,
                    max_attempts=6,
                )

                # Subscribe to notifications
                await self._client.start_notify(NTF_UUID, self._notification_handler)

                self._conn_state = ConnState.CONNECTED
                _LOGGER.debug("Connected to %s with notifications enabled", self._address)

            except Exception as err:
                self._client = None
                self._conn_state = ConnState.DISCONNECTED
                _LOGGER.error("Failed to connect to %s: %s", self._address, err)
                raise

    # ----------------------------------------------------------------------
    # Command sender
    # ----------------------------------------------------------------------
    async def _send_cmd(self, payload: bytes) -> bool:
        """Send BLE command to CMD_UUID."""
        try:
            await self._ensure_connected()
        except Exception as err:
            _LOGGER.error("Connect before send failed for %s: %s", self._address, err)
            return False

        if not self._client:
            _LOGGER.error("No active BLE client for %s after connecting", self._address)
            return False

        try:
            _LOGGER.debug(
                "Sending to %s CMD_UUID: %s",
                self._address,
                payload.hex(),
            )
            await self._client.write_gatt_char(CMD_UUID, payload)
            return True

        except Exception as err:
            _LOGGER.error("Failed BLE write on %s: %s", self._address, err)
            return False

    # ----------------------------------------------------------------------
    # Disconnect
    # ----------------------------------------------------------------------
    async def disconnect(self) -> None:
        async with self._conn_lock:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
            self._client = None
            self._conn_state = ConnState.DISCONNECTED

    # ----------------------------------------------------------------------
    # State exposure
    # ----------------------------------------------------------------------
    @property
    def available(self) -> bool:
        return self._conn_state is ConnState.CONNECTED

    @property
    def is_on(self) -> bool:
        return self._is_on

    # ----------------------------------------------------------------------
    # Light commands
    # ----------------------------------------------------------------------
    async def turn_on(self) -> None:
        payload = bytes.fromhex("aa020101bb")
        if await self._send_cmd(payload):
            self._is_on = True
            self._notify_state_change()

    async def turn_off(self) -> None:
        payload = bytes.fromhex("aa020100bb")
        if await self._send_cmd(payload):
            self._is_on = False
            self._notify_state_change()

    async def set_color(self, red: int, green: int, blue: int, brightness: int) -> None:
        """Placeholder color command (protocol TBD)."""
        payload = bytes.fromhex("aa030701001403e8038cbb")
        if await self._send_cmd(payload):
            self._rgb = (red, green, blue)
            self._brightness = brightness
            self._is_on = True
            self._notify_state_change()
