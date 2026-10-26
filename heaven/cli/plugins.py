"""HEAVEN plugin management commands."""

from __future__ import annotations

import json

import click

from heaven.plugins.manager import demo_enabled, discover_plugins, load_plugin, run_plugin


@click.group(name="plugins")
def plugins() -> None:
    """List and execute HEAVEN plugins."""


@plugins.command(name="list")
def list_plugins() -> None:
    """Display every discovered plugin."""

    plugins = discover_plugins()
    if not plugins:
        click.echo("No HEAVEN plugins discovered.")
        click.echo("Add .py files under ./heaven_plugins/ or set HEAVEN_PLUGIN_PATH.")
    else:
        for plugin in plugins:
            click.echo(f"{plugin.name:<18} {plugin.version:<8} {plugin.description}")
            click.echo(f"  source: {plugin.path}")

    if not any(plugin.name == "demo" for plugin in plugins) and not demo_enabled():
        click.echo("\nNote: the bundled 'demo' example is disabled because it injects "
                   "synthetic evidence.\n      Set HEAVEN_ENABLE_DEMO=1 to load it.")


@plugins.command(name="describe")
@click.argument("name")
def describe_plugin(name: str) -> None:
    """Show metadata for one plugin."""

    plugin = load_plugin(name)
    click.echo(f"Name: {plugin.name}")
    click.echo(f"Version: {plugin.version}")
    click.echo(f"Description: {plugin.description}")
    click.echo(f"Author: {plugin.author}")
    click.echo(f"Path: {plugin.path}")
    click.echo(f"Entry point: {plugin.entry_point}")


@plugins.command(name="hooks")
def list_hooks() -> None:
    """List plugins that expose lifecycle hooks."""

    found = False
    for plugin in discover_plugins():
        if plugin.module is None:
            continue
        hooks = [name for name in dir(plugin.module) if name.startswith("hook_")]
        if hooks:
            found = True
            click.echo(f"{plugin.name}: {', '.join(h for h in hooks if h.startswith('hook_'))}")
    if not found:
        click.echo("No lifecycle hooks discovered.")


@plugins.command(name="report")
@click.option("--json", "json_output", is_flag=True, default=False)
def plugin_report(json_output: bool) -> None:
    """Render plugin-defined report sections for the current scan summary."""

    from heaven.plugins.manager import get_report_sections
    sections = get_report_sections(summary={"sample": True}, target="example.com")
    if not sections:
        click.echo("No plugin report sections available.")
        return

    if json_output:
        click.echo(json.dumps(sections, indent=2, default=str))
        return

    for section in sections:
        title = section.get("title") or section.get("name") or "Plugin section"
        content = section.get("content") or json.dumps(section.get("data", {}), indent=2, default=str)
        click.echo(f"\n## {title}\n{content}")


@plugins.command(name="run")
@click.argument("name")
@click.option("--arg", "extra_args", multiple=True,
              help="Extra plugin arguments in KEY=VALUE form. Example: --arg target=example.com")
def run_plugin_cmd(name: str, extra_args: tuple[str, ...]) -> None:
    """Execute a plugin with optional KEY=VALUE arguments."""

    params: dict[str, object] = {}
    for item in extra_args:
        if "=" in item:
            key, value = item.split("=", 1)
            params[key] = value
        else:
            params[item] = True

    result = run_plugin(name, **params)
    click.echo(json.dumps(result, indent=2, sort_keys=True, default=str))


def register(cli: click.Group) -> None:
    cli.add_command(plugins)
