"""Main module for UTEC Layer Tools QGIS Plugin."""

import configparser
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, cast

from qgis.gui import QgisInterface
from qgis.PyQt.QtCore import QCoreApplication, QObject, QSettings, QTranslator
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QMenu, QToolButton

try:
    from qgis.PyQt.QtWidgets import QAction
except ImportError:
    from qgis.PyQt.QtGui import QAction


from .modules.constants import ICONS
from .modules.context import ContextRuntimeError, PluginContext
from .modules.geopackage import (
    copy_layers_to_gpkg,
    create_gpkg_layer,
    delete_gpkg_layers,
    manage_gpkg_tables,
)
from .modules.layer_location import LocationIndicatorManager
from .modules.logs_and_errors import (
    CustomRuntimeError,
    CustomUserError,
    log_debug,
    log_summary_message,
    lvl,
    raise_runtime_error,
)
from .modules.print_layout import create_print_layout
from .modules.print_layout_export import export_layouts_to_pdf
from .modules.project_variables import edit_project_variables
from .modules.rename import Rename, rename_layers, undo_rename_layers
from .modules.shipping import prepare_layers_for_shipping

if TYPE_CHECKING:
    from qgis.core import QgsProject
    from qgis.gui import QgsMessageBar

    from modules.constants import ActionResults


class UTECLayerTools(QObject):
    """QGIS Plugin for actions on layers."""

    def __init__(self, iface: QgisInterface) -> None:
        """Initialize the plugin.

        Args:
            iface: An interface instance that allows interaction with QGIS.
        """
        super().__init__()
        self.plugin_dir: Path = Path(__file__).parent
        PluginContext.init(iface, self.plugin_dir)
        log_debug(
            f"Detected {'dark' if PluginContext.is_dark_theme() else 'light'} theme."
        )

        self.project: QgsProject = PluginContext.project()
        self.iface: QgisInterface = iface
        self.msg_bar: QgsMessageBar | None = iface.messageBar()
        self.actions: list = []
        self.plugin_menu: QMenu | None = None
        self.plugin_icon: QIcon = ICONS.main_icon
        self.translator: QTranslator | None = None
        self.indicator_manager: LocationIndicatorManager | None = None

        # Read metadata to get the plugin name for UI elements
        self.plugin_name: str = "UTEC Layer Tools (dev)"
        metadata_path: Path = self.plugin_dir / "metadata.txt"
        if metadata_path.exists():
            config = configparser.ConfigParser()
            config.read(metadata_path)
            try:
                self.plugin_name = config.get("general", "name")
            except (configparser.NoSectionError, configparser.NoOptionError):
                log_debug("Could not read name from metadata.txt", lvl.Warning)

        self.menu: str = self.plugin_name

        # initialize translation
        locale: str = QSettings().value("locale/userLocale", "en")[:2]
        translator_path: Path = self.plugin_dir / "i18n" / f"{locale}.qm"

        if not translator_path.exists():
            log_debug(f"Translator not found in: {translator_path}", lvl.Warning)
        else:
            self.translator = QTranslator()
            if self.translator is not None and self.translator.load(
                str(translator_path)
            ):
                QCoreApplication.installTranslator(self.translator)
            else:
                log_debug("Translator could not be installed.", lvl.Warning)

    def add_action(  # noqa: PLR0913
        self,
        icon: QIcon,
        button_text: str,
        callback: Callable,
        *,
        enabled_flag: bool = True,
        add_to_menu: bool = True,
        add_to_toolbar: bool = True,
        tool_tip: str | None = None,
        parent=None,  # noqa: ANN001
    ) -> QAction:
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
        """Create the menu entries and toolbar icons for the plugin."""
        self._setup_main_menu()

        # -- Project Metadata & Layouts --
        self._add_project_variables_action()
        self._add_print_layout_action()
        self._add_export_layouts_action()

        if self.plugin_menu:
            self.plugin_menu.addSeparator()

        # -- Data Management --
        self._add_geopackage_actions()

        if self.plugin_menu:
            self.plugin_menu.addSeparator()

        # -- Layer Management --
        self._add_rename_actions()

        # Integrate the plugin menu into QGIS
        if (menu := self.iface.pluginMenu()) and self.plugin_menu:
            menu.addMenu(self.plugin_menu)

        self._setup_toolbar()

        # Initialize indicators
        self.indicator_manager = LocationIndicatorManager(self.project, self.iface)
        self.indicator_manager.init_indicators()

    def _setup_main_menu(self) -> None:
        """Initialize the main plugin menu structure."""
        if (menu := QMenu(self.menu, self.iface.pluginMenu())) is None:
            raise_runtime_error("Failed to create the plugin menu.")

        self.plugin_menu = menu
        menu.setToolTipsVisible(True)
        menu.setIcon(self.plugin_icon)

    def _add_project_variables_action(self) -> None:
        """Add the action for editing project variables."""
        # fmt: off
        # ruff: noqa: E501
        button_text: str = QCoreApplication.translate("Menu_Button", "Edit Project Variables")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Edit Project Variables</b></p><p>Define project-specific metadata like project number and name. These are stored as project variables (see Project → Properties...) and can be used in expressions, e.g. [% @project_number %]. They are automatically used in new print layouts. If not defined here, they are created from the first print layout.</p></div>")
        # <div style='font-weight:normal;'><p><b>Projektvariablen bearbeiten</b></p><p>Metadaten wie Projektnummer und Name definieren. Diese werden als Projektvariablen gespeichert (siehe Projekt → Eigenschaften...) und können in Ausdrücken verwendet werden, z.B. [% @project_number %]. Sie werden automatisch in neuen Drucklayouts verwendet. Wenn nicht hier definiert, werden sie aus dem ersten Drucklayout erstellt.</p></div>
        # fmt: on
        project_vars_action = self.add_action(
            icon=ICONS.main_menu_variables,
            button_text=button_text,
            callback=self.manage_project_variables,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(project_vars_action)

    def _add_print_layout_action(self) -> None:
        """Add a direct action for creating a print layout."""
        # fmt: off
        button_text: str = QCoreApplication.translate("Menu_Button", "Create Print Layout")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Create New Print Layout</b></p><p>Tip: If the same name is entered under 'Drawing Type' as a named layer theme ('Eye-menu' in the layer manager), the main map of the layout will automatically follow this theme.</p></div>")
        # <div style='font-weight:normal;'><p><b>Neues Drucklayout Erstellen</b></p><p>Tipp: wenn unter "Planart" der gleiche Name eingetragen wird wie ein benanntes Layer-Thema ("Auge-Menu" im Layermanager), folgt die Hauptkarte des Layouts automatisch diesem Thema.</p></div>
        # fmt: on
        create_layout_action = self.add_action(
            icon=ICONS.main_menu_print,
            button_text=button_text,
            callback=self.create_layout,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(create_layout_action)

    def _add_export_layouts_action(self) -> None:
        """Add the action for exporting layouts as PDF."""
        # fmt: off
        # ruff: noqa: E501
        button_text: str = QCoreApplication.translate("Menu_Button", "Export Print Layouts as PDF")
        tool_tip_text: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Export Print Layouts as PDF</b></p><p>The PDFs will be saved in the specified folder (defaults to 'pdf' within the project directory) without overwriting existing files. Existing files with the same name will be moved to a folder called 'alt'.</p></div>")
        # <div style='font-weight:normal;'><p><b>Drucklayouts als PDF exportieren</b></p><p>Die pdf-Dateien werden im angegebenen Ordner (Standardordner: 'pdf' im Projektverzeichnis) gespeichert ohne vorhandene Dateien zu überschreiben. Vorhandene Dateien mit demselben Namen werden in einen Unterordner namens 'alt' verschoben.</p></div>
        # fmt: on
        export_layouts_action = self.add_action(
            icon=ICONS.main_menu_export,
            button_text=button_text,
            callback=self.export_layouts,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_text,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(export_layouts_action)

    def _add_geopackage_actions(self) -> None:
        """Add actions for copying layers and preparing shipping packages."""
        # fmt: off
        # ruff: noqa: E501
        button_new_layer: str = QCoreApplication.translate("Menu_Button", "Create New Layer in Project's GeoPackage")
        tool_tip_new_layer: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Create New Layer in Project's GeoPackage</b></p><p>Creates a new layer in the project's GeoPackage. The new layer is added to the top of the layer tree of the current project.</p><p><i>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Neuen Layer im Projekt-GeoPackage Erstellen</b></p><p>Erstellt einen neuen Layer im Projekt-GeoPackage. Der neue Layer wird von dort in das Projekt (im Layer-Baum ganz oben) eingefügt.</p><p><i>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</i></p></div>
        # fmt: on
        new_layer_action = self.add_action(
            icon=ICONS.main_menu_new_layer,
            button_text=button_new_layer,
            callback=self.create_new_gpkg_layer,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_new_layer,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(new_layer_action)

        # fmt: off
        # ruff: noqa: E501
        button_manage: str = QCoreApplication.translate("Menu_Button", "Manage Project GeoPackage")
        tool_tip_manage: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Manage Project GeoPackage</b></p><p>Rename or delete layers (tables) in the project's GeoPackage. After deleting layers, disk space is automatically freed using the 'VACUUM' command.</p><p><i>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Projekt-GeoPackage Verwalten</b></p><p>Layer (Tabellen) im Projekt-GeoPackage umbenennen oder löschen. Nach dem Löschen von Layern wird der Speicherplatz automatisch freigegeben (VACUUM-Befehl).</p><p><i>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</i></p></div>
        # fmt: on
        manage_gpkg_action = self.add_action(
            icon=ICONS.main_menu_manage_geopackage,
            button_text=button_manage,
            callback=self.manage_gpkg_tables,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_manage,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(manage_gpkg_action)

            self.plugin_menu.addSeparator()

        # fmt: off
        # ruff: noqa: E501
        button_copy: str = QCoreApplication.translate("Menu_Button", "Copy Selected Layers to Project's GeoPackage")
        tool_tip_copy: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Copy Selected Layers to Project's GeoPackage</b></p><p>Selected layers and layers in selected groups are copied to the project's GeoPackage and added back from the GeoPackage to the top of the layer tree of the current project. The original layers can be removed from the project if desired.</p><p><b>!!! CAUTION !!!</b><br>This will overwrite layers with the same name and geometry type in the project's GeoPackage!</p><p><i>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Gewählte Layer in das Projekt-GeoPackage Kopieren</b></p><p>Gewählte Layer und Layer in gewählten Gruppen werden in das Projekt-GeoPackage kopiert und von dort in das Projekt (im Layer-Baum ganz oben) eingefügt. Die Ausgangslayer können danach, wenn gewünscht, aus dem Projekt gelöscht werden.</p><p><b>!!! Vorsicht !!!</b><br>Layer mit mit gleichem Namen und gleichem Geometrietyp im Projekt-GeoPackage werden überschrieben!</b></p><p><i>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</i></p></div>
        # fmt: on
        copy_action = self.add_action(
            icon=ICONS.main_menu_copy,
            button_text=button_copy,
            callback=self.copy_selected_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_copy,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(copy_action)

        # fmt: off
        #ruff: noqa: E501
        button_ship: str = QCoreApplication.translate("Menu_Button", "Prepare Selected Layers for Sending")
        tool_tip_ship: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Prepare Selected Layers for Sending</b></p><p>Creates a subfolder in the project folder with a GeoPackage (.gpkg) and a project file (.qgz) containing the selected layers. These two files can be sent e.g. via email.</p></div>")
        # <div style='font-weight:normal;'><p><b>Gewählte Layer für Versand Vorbereiten</b></p><p>Im Projektordner wird ein Unterordner mit einem GeoPackage (.gpkg) und einer Projektdatei (.qgz) erstellt, die die gewählten Layer enthalten. Diese beiden Dateien können z.B. per E-Mail versendet werden.</p></div>
        # fmt: on
        shipping_action = self.add_action(
            icon=ICONS.main_menu_send,
            button_text=button_ship,
            callback=self.prepare_shipping,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_ship,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(shipping_action)

        # fmt: off
        # ruff: noqa: E501
        button_delete: str = QCoreApplication.translate("Menu_Button", "Delete Selected Layers from the Project and from the Project's GeoPackage")
        tool_tip_delete: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Delete Selected Layers from the Project and from the Project's GeoPackage</b></p><p><b>!!! CAUTION !!!</b><br>Selected layers and layers in selected groups are deleted from the project as well as from the project's GeoPackage.</p><p><i>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Gewählte Layer aus dem Projekt-GeoPackage Löschen</b></p><p><b>!!! VORSICHT !!!</b><br>Gewählte Layer und Layer in gewählten Gruppen werden sowohl aus dem Projekt, als auch aus dem Projekt-GeoPackage gelöscht.</p><p><i>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</i></p></div>
        # fmt: on
        delete_action = self.add_action(
            icon=ICONS.main_menu_delete_layers,
            button_text=button_delete,
            callback=self.delete_selected_gpkg_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_delete,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(delete_action)

    def _add_rename_actions(self) -> None:
        """Add actions for renaming layers and undoing operations."""
        # fmt: off
        # ruff: noqa: E501
        button_rename: str = QCoreApplication.translate("Menu_Button", "Rename Selected Layers by Group Name")
        tool_tip_rename: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Rename Selected Layers by Group Name</b></p><p>Selected layers and layers in selected groups are renamed according to their parent group names. If a layer is not in a group, it is not renamed.</p><p><i>(Mostly useful for renaming layers imported from AutoCAD)</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Gewählte Layer nach Gruppenname Umbenennen</b></p><p>Gewählte Layer und Layer in gewählten Gruppen werden umbenannt, so dass ihr Name der Gruppe entspricht, in der sie liegen. Layer, die sich nicht in einer Gruppe befinden, werden nicht umbenannt.</p><p><i>(Nützlich für das Umbenennen von Layern, die aus AutoCAD importiert wurden)</i></p></div>
        # fmt: on
        rename_action = self.add_action(
            icon=ICONS.main_menu_rename,
            button_text=button_rename,
            callback=self.rename_selected_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_rename,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(rename_action)

        # fmt: off
        # ruff: noqa: E501
        button_ren_copy: str = QCoreApplication.translate("Menu_Button", "Rename and Copy Selected Layers to Project's GeoPackage")
        tool_tip_ren_copy: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Rename and Copy Selected Layers to Project's GeoPackage</b></p><p>Selected layers and layers in selected groups are renamed according to their parent group names, then copied to the project's GeoPackage and then added back from the GeoPackage to the top of the layer tree of the current project. The original layers can be removed from the project if desired.</p><p><b>!!! CAUTION !!!</b><br>This will overwrite layers with the same name and geometry type in the project's GeoPackage!</p><p><i>The project's GeoPackage is a GeoPackage (.gpkg) in the project folder with the same name as the project file (.qgz).</i></p></div>")
        # <div style='font-weight:normal;'><p><b>Gewählte Layer Umbenennen und in das Projekt-GeoPackage Kopieren</b></p><p>Gewählte Layer und Layer in gewählten Gruppen werden umbenannt, so dass ihr Name der Gruppe entspricht, in der sie liegen, danach in das Projekt-GeoPackage kopiert und von dort in das Projekt (im Layer-Baum ganz oben) eingefügt. Die Ausgangslayer können danach, wenn gewünscht, aus dem Projekt gelöscht werden.</p><p><b>!!! Vorsicht !!!</b><br>Layer mit mit gleichem Namen und gleichem Geometrietyp im Projekt-GeoPackage werden überschrieben!</p><p><i>Das Projekt-GeoPackage ist ein GeoPackage (.gpkg) im Projektordner mit dem gleichen Namen wie die Projektdatei (.qgz).</i></p></div>
        # fmt: on
        rename_copy_action = self.add_action(
            icon=ICONS.main_menu_rename_copy,
            button_text=button_ren_copy,
            callback=self.rename_and_copy_layers,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_ren_copy,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(rename_copy_action)

        # fmt: off
        # ruff: noqa: E501
        button_undo: str = QCoreApplication.translate("Menu_Button", "Undo Last Rename")
        tool_tip_undo: str = QCoreApplication.translate("Menu_ToolTip", "<div style='font-weight:normal;'><p><b>Undo Last Rename</b></p><p>Undoes the most recent layer renaming operation performed by this plugin.</p></div>")
        # <div style='font-weight:normal;'><p><b>Letzte Umbenennung Rückgängig machen</b></p><p>Die letzte Umbenennung, die von diesem Plugin ausgeführt wurde, wird rückgängig gemacht.</p></div>
        # fmt: on
        undo_rename_action = self.add_action(
            icon=ICONS.main_menu_undo,
            button_text=button_undo,
            callback=self.undo_last_rename,
            parent=self.iface.mainWindow(),
            add_to_menu=False,
            add_to_toolbar=False,
            tool_tip=tool_tip_undo,
        )
        if self.plugin_menu:
            self.plugin_menu.addAction(undo_rename_action)

    def _setup_toolbar(self) -> None:
        """Set up the toolbar button and popup menu for the plugin."""
        toolbar_button = QToolButton()
        toolbar_button.setIcon(self.plugin_icon)
        toolbar_button.setToolTip(self.plugin_name)
        if self.plugin_menu is not None:
            toolbar_button.setMenu(self.plugin_menu)

        mode = cast(
            "QToolButton.ToolButtonPopupMode",
            QToolButton.ToolButtonPopupMode.InstantPopup,
        )
        toolbar_button.setPopupMode(mode)

        toolbar_action = self.iface.addToolBarWidget(toolbar_button)
        self.actions.append(toolbar_action)

    def unload(self) -> None:
        """Plugin unload method.

        Called when the plugin is unloaded according to the plugin QGIS metadata.
        """
        # Unregister the layer tree view indicator
        if self.indicator_manager:
            self.indicator_manager.unload()
            self.indicator_manager = None

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

    def create_new_gpkg_layer(self) -> None:
        """Create a new layer in the project's GeoPackage."""
        log_debug("... STARTING PLUGIN RUN ... (create_new_gpkg_layer)", icon="✨✨✨")
        with contextlib.suppress(
            CustomUserError, CustomRuntimeError, ContextRuntimeError
        ):
            create_gpkg_layer()

    def delete_selected_gpkg_layers(self) -> None:
        """Delete selected project layers and their GeoPackage tables."""
        log_debug(
            "... STARTING PLUGIN RUN ... (delete_selected_gpkg_layers)", icon="✨✨✨"
        )
        with contextlib.suppress(
            CustomUserError, CustomRuntimeError, ContextRuntimeError
        ):
            delete_gpkg_layers()

    def manage_gpkg_tables(self) -> None:
        """Open the project's GeoPackage table manager."""
        log_debug("... STARTING PLUGIN RUN ... (manage_gpkg_tables)", icon="✨✨✨")
        with contextlib.suppress(
            CustomUserError, CustomRuntimeError, ContextRuntimeError
        ):
            manage_gpkg_tables()

    def manage_project_variables(self) -> None:
        """Open the custom project variables editor."""
        log_debug(
            "... STARTING PLUGIN RUN ... (manage_project_variables)", icon="✨✨✨"
        )
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            edit_project_variables()

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

    def create_layout(self) -> None:
        """Open the dialog to create a print layout."""
        log_debug("... STARTING PLUGIN RUN ... (create_layout)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            create_print_layout()

    def export_layouts(self) -> None:
        """Export selected layouts as PDF files."""
        log_debug("... STARTING PLUGIN RUN ... (export_layouts)", icon="✨✨✨")
        with contextlib.suppress(CustomUserError, CustomRuntimeError):
            if results := export_layouts_to_pdf():
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
