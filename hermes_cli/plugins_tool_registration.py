"""Scoped plugin tool registration; PluginContext owns serialization and the public signature."""
import logging

logger = logging.getLogger("hermes_cli.plugins")


def register_plugin_tool(self, name, toolset, schema, handler, **options):
    from hermes_cli.plugins import PluginToolOverrideError
    override = options.get("override", False)
    if override and not self._tool_override_allowed(name):
        raise PluginToolOverrideError(
            f"Plugin {self.manifest.name!r} cannot override built-in tool {name!r}. Set "
            f"plugins.entries.{self.plugin_id}.allow_tool_override: true "
            f"in config.yaml to allow this plugin to replace built-in tools."
        )
    from tools.registry import registry
    scope = self._manager.scope_key
    previous = registry.snapshot_registration(name, scope=scope)
    if previous is None and not override and registry.get_entry(name, scope=scope) is not None:
        logger.warning("Plugin %s tried to shadow global tool %s without override=True",
                       self.manifest.name, name)
        return None
    registry.register(
        name=name, toolset=toolset, schema=schema, handler=handler, scope=scope, **options,
    )
    registered = registry.snapshot_registration(name, scope=scope)
    handle = None
    if registered is not None and registered is not previous and registered.handler is handler:
        self._manager._plugin_tool_names.add(name)
        handle = self._manager._track_scoped_registration(
            self.manifest, "tool", name, registry, registered, previous,
            finalize=lambda: self._manager._remove_tool_name_if_unowned(name),
        )
    logger.debug("Plugin %s registered tool: %s%s", self.manifest.name, name,
                 " (override)" if override else "")
    return handle
