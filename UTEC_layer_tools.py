"""Main module for UTEC Layer Tools QGIS Plugin."""

import configparser
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from qgis.core import Qgis, QgsProject
from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QObject, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMenu, QToolButton

from .modules.constants import ICONS
from .modules.context import PluginContext
from .modules.geopackage import copy_layers_to_gpkg
from .modules.geopackage_indicators import GeopackageIndicatorManager
from .modules.layer_location import LocationIndicatorManager
from .modules.logs_and_errors import (
    CustomRuntimeError,
    CustomUserError,
    log_debug,
    log_summary_message,
    raise_runtime_error,
)
from .modules.rename import Rename, rename_layers, undo_rename_layers
from .modules.shipping import prepare_layers_for_shipping

if TYPE_CHECKING:
    from qgis.gui import QgsMessageBar

    from modules.constants import ActionResults


class UTECLayerTools(QObject):  # pylint: disable=too-many-instance-attributes
    """QGIS Plugin for actions on layers."""

    def __init__(self, iface: QgisInterface) -> None:
        """Initialize the plugin.

        Args:
            iface: An interface instance that allows interaction with QGIS.
        """
        super().__init__()
        self.plugin_dir: Path = Path(__file__).parent
        PluginContext.init(iface, self.plugin_dir)

        self.project: QgsProject = PluginContext.project()
        self.iface: QgisInterface = iface
        self.msg_bar: QgsMessageBar | None = iface.messageBar()
        self.actions: list = []
        self.plugin_menu: QMenu | None = None
        self.plugin_icon: QIcon = ICONS.main_icon
        self.translator: QTranslator | None = None
        self.indicator_manager: LocationIndicatorManager | None = None
        self.gpkg_indicator_manager: GeopackageIndicatorManager | None = None

        # Read metadata to get the plugin name for UI elements
        self.plugin_name: str = "UTEC Layer Tools (dev)"
        metadata_path: Path = self.plugin_dir / "metadata.txt"
        if metadata_path.exists():
            config = configparser.ConfigParser()
            config.read(metadata_path)
            try:
                self.plugin_name = config.get("general", "name")
            except (configparser.NoSectionError, configparser.NoOptionError):
                log_debug("Could not read name from metadata.txt", Qgis.Warning)

        self.menu: str = self.plugin_name

        # initialize translation
        locale = QSettings().value("locale/userLocale", "en")[:2]
        translator_path: Path = self.plugin_dir / "i18n" / f"{locale}.qm"

        if not translator_path.exists():
            log_debug(f"Translator not found in: {translator_path}", Qgis.Warning)
        else:
            self.translator = QTranslator()
            if self.translator is not None and self.translator.load(
                str(translator_path)
            ):
                QCoreApplication.installTranslator(self.translator)
            else:
                log_debug("Translator could not be installed.", Qgis.Warning)

    def add_action(  # noqa: PLR0913 # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        icon: QIcon,
        button_text: str,
        callback: Callable,
        enabled_flag: bool = True,  # noqa: FBT001, FBT002
        add_to_menu: bool = True,  # noqa: FBT001, FBT002
        add_to_toolbar: bool = True,  # noqa: FBT001, FBT002
        tool_tip: str | None = None,
        parent=None,  # noqa: ANN001
    ) -> QAction:  # pyright: ignore[reportInvalidTypeForm]
        """Create and configure a QAction for the plugin.

        This helper method creates a QAction, connects it to a callback, and
        optionally adds it to the QGIS toolbar and the plugin's menu.

        Args:
            icon: Path to the icon or QIcon object.
            button_text: Text to be displayed for the action in menus.
            callback: The function to execute when the action is triggered.
            enabled_flag: Whether the action should be enabled by default.
            add_to_menu: If True, adds the action to the plugin's menu.
            add_to_toolbar: If True, adds the action to a QGIS toolbar.
            tool_tip: Optional tooltip text for the action.
            parent: The parent widget for the action, typically the QGIS main window.

        Returns:
            The configured QAction instance.
        """

        action = QAction(icon, button_text, parent)
        action.triggered.connect(callback)
        action.setEnabled(enabled_flag)

        if tool_tip is not None:
            action.setToolTip(tool_tip)

        if add_to_toolbar:
            self.iface.addToolBarIcon(action)

        if add_to_menu:
            self.iface.addPluginToMenu(self.menu, action)

        self.actions.append(action)

        return action

    def initGui(self) -> None:  # noqa: N802
        """Create the menu entries and toolbar icons for the plugin.

        Initializes the plugin menu, adds actions to the menu and toolbar, and
        sets up the location indicator manager.
        """

        # Create a menu for the plugin in the "Plugins" menu
        self.plugin_menu = QMenu(self.menu, self.iface.pluginMenu())
        if self.plugin_menu is None:
            # fmt: off
            error_msg: str = QCoreApplication.translate("RuntimeError", "Failed to create the plugin menu.")
            # fmt: on
            raise_runtime_error(error_msg)

        self.plugin_menu.setToolTipsVisible(True)
        self.plugin_menu.setIcon(self.plugin_icon)

        # Add an action for moving layers
        # fmt: off
        # ruff: noqa: E501
        button: str = QCoreApplication.translate("Menu_Button", "Copy Selected Layers to Project's GeoPackage")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<p><b>Copy Selected Layers to Project's GeoPackage</b></p><p><span style='font-weight:normal; font-style:normal;'>Selected layers and layers in selected groups are copied to the project's GeoPackage and added back from the GeoPackage to the top of the layer tree of the current project. The original layers can be removed from the project if desired.</p><p>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</span></p><p><b>CAUTION: This will overwrite layers with the same name and geometry type in the project's GeoPackage!</b></p>")
        #                                                                <p><b>Gewählte Layer in das Projekt-GeoPackage Kopieren</b></p><p><span style='font-weight:normal; font-style:normal;'>Gewählte Layer und Layer in gewählten Gruppen werden in das Projekt-GeoPackage kopiert und von dort in das Projekt (im Layer-Baum ganz oben) eingefügt. Die Ausgangslayer können danach, wenn gewünscht, aus dem Projekt gelöscht werden.</p><p>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</span></p><p><b>Vorsicht: Layer mit mit gleichem Namen und gleichem Geometrietyp im Projekt-GeoPackage werden überschrieben!</b></p>
        # fmt: on
        copy_action = self.add_action(
            icon=ICONS.main_menu_copy,
            button_text=button,
            callback=self.copy_selected_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,  # Added to custom menu
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        self.plugin_menu.addAction(copy_action)

        # Add an action for renaming layers
        # fmt: off
        # ruff: noqa: E501     
        button: str = QCoreApplication.translate("Menu_Button", "Rename Selected Layers by Group Name")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<p><b>Rename Selected Layers by Group Name</b></p><p><span style='font-weight:normal; font-style:normal;'>Selected layers and layers in selected groups are renamed according to their parent group names. If a layer is not in a group, it is not renamed.</p><p>(Mostly useful for renaming layers imported from AutoCAD)</span></p>")
        #                                                                <p><b>Gewählte Layer nach Gruppenname Umbenennen</b></p><p><span style='font-weight:normal; font-style:normal;'>Gewählte Layer und Layer in gewählten Gruppen werden umbenannt, so dass ihr Name der Gruppe entspricht, in der sie liegen. Layer, die sich nicht in einer Gruppe befinden, wird er nicht umbenannt.</p><p>(Nützlich für das Umbenennen von Layern, die aus AutoCAD importiert wurden)</span></p>
        # fmt: on
        rename_action = self.add_action(
            icon=ICONS.main_menu_rename,
            button_text=button,
            callback=self.rename_selected_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,  # Will be added to our custom menu
            add_to_toolbar=False,  # Avoid creating a separate toolbar button
            tool_tip=tool_tip_text,
        )
        self.plugin_menu.addAction(rename_action)

        # Add an action for undoing the last rename
        # fmt: off
        # ruff: noqa: E501
        button: str = QCoreApplication.translate("Menu_Button", "Undo Last Rename")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<p><b>Undo Last Rename</b></p><p><span style='font-weight:normal; font-style:normal;'>Undoes the most recent layer renaming operation performed by this plugin.</span></p>")
        #                                                                <p><b>Letzte Umbenennung Rückgängig Machen</b></p><p><span style='font-weight:normal; font-style:normal;'>Die letzte Umbenennung, die von diesem Plugin ausgeführt wurde, wird rückgängig gemacht.</span></p>
        # fmt: on
        undo_rename_action = self.add_action(
            icon=ICONS.main_menu_undo,
            button_text=button,
            callback=self.undo_last_rename,
            parent=self.iface.mainWindow(),
            add_to_menu=False,  # Added to custom menu
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        self.plugin_menu.addAction(undo_rename_action)

        # Add an action for renaming and moving layers
        # fmt: off
        # ruff: noqa: E501
        button: str = QCoreApplication.translate("Menu_Button", "Rename and Copy Selected Layers to Project's GeoPackage")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<p><b>Rename and Copy Selected Layers to Project's GeoPackage</b></p><p><span style='font-weight:normal; font-style:normal;'>Selected layers and layers in selected groups are renamed according to their parent group names, then copied to the project's GeoPackage and then added back from the GeoPackage to the top of the layer tree of the current project. The original layers can be removed from the project if desired.</p><p>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</span></p><b>CAUTION: This will overwrite layers with the same name and geometry type in the project's GeoPackage!</b></p>")
        #                                                                <p><b>Gewählte Layer Umbenennen und in das Projekt-GeoPackage Kopieren</b></p><p><span style='font-weight:normal; font-style:normal;'>Gewählte Layer und Layer in gewählten Gruppen werden umbenannt, so dass ihr Name der Gruppe entspricht, in der sie liegen, danach in das Projekt-GeoPackage kopiert und von dort in das Projekt (im Layer-Baum ganz oben) eingefügt. Die Ausgangslayer können danach, wenn gewünscht, aus dem Projekt gelöscht werden.</p><p>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</span></p><p><b>Vorsicht: Layer mit mit gleichem Namen und gleichem Geometrietyp im Projekt-GeoPackage werden überschrieben!</b></p>
        # fmt: on
        rename_copy_action = self.add_action(
            icon=ICONS.main_menu_rename_copy,
            button_text=button,
            callback=self.rename_and_copy_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,  # Added to custom menu
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        self.plugin_menu.addAction(rename_copy_action)

        # Add an action for preparing layers for shipping
        # fmt: off
        # ruff: noqa: E501
        button: str = QCoreApplication.translate("Menu_Button", "Prepare Selected Layers for Sending")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<p><b>Prepare Selected Layers for Sending</b></p><p><span style='font-weight:normal; font-style:normal;'>Creates a subfolder in the project folder with a GeoPackage (.gpkg) and a project file (.qgz) containing the selected layers. These two files can be sent e.g. via email.</span></p>")
        #                                                                <p><b>Gewälte Layer für Versand Vorbereiten</b></p><p><span style='font-weight:normal; font-style:normal;'>Im Projektordner wird ein Unterordner mit einem GeoPackage (.gpkg) und einer Projektdatei (.qgz) erstellt, die die gewählten Layer enthalten. Diese beiden Dateien können z.B. per E-Mail versendet werden.</span></p>
        # fmt: on
        shipping_action = self.add_action(
            icon=ICONS.main_menu_send,
            button_text=button,
            callback=self.prepare_shipping,
            parent=self.iface.mainWindow(),
            add_to_menu=False,  # Added to custom menu
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        self.plugin_menu.addAction(shipping_action)

        # Add the fly-out menu to the main "Plugins" menu
        if menu := self.iface.pluginMenu():
            menu.addMenu(self.plugin_menu)
        toolbar_button = QToolButton()
        toolbar_button.setIcon(self.plugin_icon)
        toolbar_button.setToolTip(self.plugin_name)
        toolbar_button.setMenu(self.plugin_menu)
        toolbar_button.setPopupMode(QToolButton.InstantPopup)
        toolbar_action = self.iface.addToolBarWidget(toolbar_button)
        self.actions.append(toolbar_action)

        # Initialize and connect the location indicator manager
        self.indicator_manager = LocationIndicatorManager(self.project, self.iface)
        self.indicator_manager.init_indicators()

        # Initialize and connect the geopackage indicator manager
        self.gpkg_indicator_manager = GeopackageIndicatorManager(
            self.project, self.iface
        )
        self.gpkg_indicator_manager.init_indicators()

    def unload(self) -> None:
        """Plugin unload method.

        Called when the plugin is unloaded according to the plugin QGIS metadata.
        """
        # Unregister the layer tree view indicator
        if self.indicator_manager:
            self.indicator_manager.unload()
            self.indicator_manager = None

        if self.gpkg_indicator_manager:
            self.gpkg_indicator_manager.unload()
            self.gpkg_indicator_manager = None

        # Remove toolbar icons for all actions
        for action in self.actions:
            self.iface.removeToolBarIcon(action)

        # Remove the plugin menu from the "Plugins" menu.
        if self.plugin_menu and (menu := self.iface.pluginMenu()):
            menu.removeAction(self.plugin_menu.menuAction())

        # Remove the translator
        if self.translator:
            QCoreApplication.removeTranslator(self.translator)

        self.actions.clear()
        self.plugin_menu = None

    #
    #
    # --- Plugin actions ---

    def rename_selected_layers(self) -> None:
        """Rename selected layers based on their group hierarchy.

        This method calls the `rename_layers` function from `modules.rename`
        to perform the renaming operation.
        """
        log_debug("... STARTING PLUGIN RUN ... (rename_selected_layers)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            results: ActionResults[None] = rename_layers()
            log_summary_message(
                processed=len(results.processed),
                skipped=results.skips,
                errors=results.errors,
            )

    def copy_selected_layers(self) -> None:
        """Copy selected layers to the project's GeoPackage.

        This method calls the `copy_layers_to_gpkg` function from
        `modules.geopackage` to perform the copy operation.
        """
        log_debug("... STARTING PLUGIN RUN ... (copy_selected_layers)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            results: ActionResults[None] = copy_layers_to_gpkg()
            log_summary_message(
                processed=len(results.processed),
                skipped=results.skips,
                errors=results.errors,
            )

    def undo_last_rename(self) -> None:
        """Undo the last rename operation.

        This method calls the `undo_rename_layers` function from `modules.rename`
        to revert the last renaming action.
        """
        log_debug("... STARTING PLUGIN RUN ... (undo_last_rename)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            results: ActionResults[list[Rename]] = undo_rename_layers()
            log_summary_message(
                processed=len(results.processed),
                skipped=results.skips,
                errors=results.errors,
            )

    def rename_and_copy_layers(self) -> None:
        """Rename selected layers and then copy them to the GeoPackage.

        This convenience method sequentially calls `rename_layers` and then
        `copy_layers_to_gpkg`.
        """
        log_debug("... STARTING PLUGIN RUN ... (rename_and_copy_layers)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            results_rename: ActionResults[None] = rename_layers()
            results_copy: ActionResults[None] = copy_layers_to_gpkg()
            log_summary_message(
                processed=max(
                    len(results_rename.processed), len(results_copy.processed)
                ),
                skipped=results_rename.skips + results_copy.skips,
                errors=results_rename.errors + results_copy.errors,
            )

    def prepare_shipping(self) -> None:
        """Prepare selected layers for shipping.

        This method calls the `prepare_layers_for_shipping` function from
        `modules.shipping` to create a shipping package.
        """
        log_debug("... STARTING PLUGIN RUN ... (prepare_shipping)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            results: ActionResults = prepare_layers_for_shipping()
            log_summary_message(
                processed=len(results.processed),
                skipped=results.skips,
                errors=results.errors,
            )
