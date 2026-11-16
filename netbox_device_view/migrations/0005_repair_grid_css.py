"""
Repair DeviceView CSS damaged before validation existed, so an upgrade fixes
stored data without anyone running check_deviceview_css --fix by hand.

The repair (grid_css.repair_view_data) only rewrites CSS when it removes
problems: import-damaged quoting (first grid row unquoted, stray quote after
the closing brace) and legacy grids the browser rejects (scattered filler
names, ragged rows).  Valid CSS is left untouched; views that still need a
manual edit are listed and flagged on the Ports pages.
"""

from django.db import migrations


def repair_grid_css(apps, schema_editor):
    from netbox_device_view.grid_css import repair_view_data

    DeviceView = apps.get_model("netbox_device_view", "DeviceView")
    views = DeviceView.objects.using(schema_editor.connection.alias).order_by("pk")
    repaired, manual = [], []
    for view in views.only("pk", "grid_template_area", "layout_config"):
        css, config, remaining = repair_view_data(view.grid_template_area, view.layout_config)
        if css != view.grid_template_area:
            # update() rather than save(): no signals or change logging during migrations.
            views.filter(pk=view.pk).update(grid_template_area=css, layout_config=config)
            repaired.append(view.pk)
        if remaining:
            manual.append(view.pk)
    if repaired or manual:
        print(f"\n  netbox_device_view: repaired CSS of {len(repaired)} device view(s) {repaired or ''}".rstrip())
        if manual:
            print(f"  netbox_device_view: {len(manual)} view(s) still need a manual edit: {manual}")


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_device_view", "0004_deviceview_layout_config"),
    ]

    operations = [
        migrations.RunPython(repair_grid_css, migrations.RunPython.noop),
    ]
