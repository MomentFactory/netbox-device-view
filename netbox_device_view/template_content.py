from netbox.plugins import PluginTemplateExtension
from .utils import prepare
from django.conf import settings
from dcim.models import Device, DeviceType
from .models import DeviceView


class PortView(PluginTemplateExtension):
    def page(self):
        obj = self.context["object"]

        if not isinstance(obj, Device):
            return ""

        request = self.context["request"]
        url = request.build_absolute_uri(obj.get_absolute_url())

        dv, modules, ports_chassis = prepare(obj)

        height = obj.device_type.u_height * 2 * 20 + obj.device_type.u_height * 2

        if dv is None or modules is None or ports_chassis is None:
            return ""

        return self.render(
            "netbox_device_view/ports.html",
            extra_context={
                "dv": dv,
                "modules": modules,
                "height": height,
                "ports_chassis": ports_chassis,
            },
        )


class DevicePortView(PortView):
    model = "dcim.device"

    def full_width_page(self):
        if not settings.PLUGINS_CONFIG["netbox_device_view"]["show_on_device_tab"]:
            return ""
        return self.page()


class DeviceTypeViewMapping(PluginTemplateExtension):
    """Show on the Device Type page whether a device view maps it."""

    model = "dcim.devicetype"

    def right_page(self):
        device_type = self.context["object"]
        if not isinstance(device_type, DeviceType):
            return ""

        return self.render(
            "netbox_device_view/includes/_devicetype_mapping.html",
            extra_context={
                "device_type": device_type,
                "device_view": DeviceView.objects.filter(device_types=device_type).first(),
            },
        )


template_extensions = [DevicePortView, DeviceTypeViewMapping]
