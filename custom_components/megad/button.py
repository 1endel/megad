import logging
from time import monotonic

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from . import MegaDCoordinator
from .const import COMMAND, CURRENT_ENTITY_IDS, DOMAIN, ENTRIES, PULSE_BUTTONS
from .core.base_ports import ReleyPortOut
from .core.megad import MegaD

_LOGGER = logging.getLogger(__name__)


def build_pulse_command(port: int, pause: int) -> str:
    """Build one controller-side ON/pause/OFF command."""
    if port < 0 or pause < 1 or pause > 255:
        raise ValueError('Invalid MegaD pulse parameters')
    return f'{port}:1;p{pause};{port}:0'


async def async_setup_entry(
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        async_add_entities: AddEntitiesCallback
) -> None:
    entry_id = config_entry.entry_id
    coordinator = hass.data[DOMAIN][ENTRIES][entry_id]
    megad = coordinator.megad
    buttons = []

    for pulse in PULSE_BUTTONS.get(str(megad.id), ()):
        port = megad.get_port(pulse['port'])
        if not isinstance(port, ReleyPortOut):
            _LOGGER.error(
                'Pulse button skipped: MegaD-%s port %s is not a relay output',
                megad.id,
                pulse['port'],
            )
            continue
        unique_id = f'{entry_id}-{megad.id}-port{pulse["port"]}-pulse-button'
        buttons.append(MegaDPulseButton(coordinator, pulse, unique_id))

    for button in buttons:
        hass.data[DOMAIN][CURRENT_ENTITY_IDS][entry_id].append(button.unique_id)
    if buttons:
        async_add_entities(buttons)
        _LOGGER.info('Added verified MegaD pulse buttons: %s', buttons)


class MegaDPulseButton(CoordinatorEntity, ButtonEntity):
    """Momentary output button executed entirely by the MegaD controller."""

    _attr_entity_registry_enabled_default = False

    def __init__(
            self,
            coordinator: MegaDCoordinator,
            config: dict,
            unique_id: str,
    ) -> None:
        super().__init__(coordinator)
        self._megad: MegaD = coordinator.megad
        self._port = config['port']
        self._pause = config['pause']
        self._cooldown = config['cooldown']
        self._attr_name = config['name']
        self._attr_icon = config['icon']
        self._attr_unique_id = unique_id
        self._attr_device_info = coordinator.devices_info()
        self.entity_id = 'button.' + slugify(
            f'{self._megad.id}_port{self._port}_pulse'
        )
        self._last_press = 0.0

    async def async_press(self) -> None:
        """Send one atomic controller-side pulse command."""
        now = monotonic()
        if now - self._last_press < self._cooldown:
            raise HomeAssistantError(
                f'Pulse button cooldown is {self._cooldown} seconds'
            )

        command = build_pulse_command(self._port, self._pause)
        self._last_press = now
        response = await self._megad.request_to_megad(
            f'{COMMAND}={command}'
        )
        response.raise_for_status()
        text = (await response.text()).strip().lower()
        if text == 'busy':
            raise HomeAssistantError('MegaD controller is busy; pulse not started')

        _LOGGER.info(
            'MegaD-%s started verified pulse on port %s for %.1f seconds',
            self._megad.id,
            self._port,
            self._pause / 10,
        )
