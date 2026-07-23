# Generated for netbox-device-view layout builder

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_device_view", "0003_alter_deviceview_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="deviceview",
            name="layout_config",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Structured layout-builder configuration used to generate grid CSS",
            ),
        ),
    ]
