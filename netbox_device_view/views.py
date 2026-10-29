from netbox.views import generic
from dcim.models import Device, DeviceType, Interface, RearPort, Site, Rack
from django.db.models import Exists, OuterRef
from . import forms, models, tables, filtersets
from utilities.views import ViewTab, register_model_view
# utilities.permissions.PermissionRequiredMixin was incorrect, removed.
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin # Standard Django mixins
from .utils import (
    prepare,
    build_device_view_lookup,
    get_device_type_layout_data,
    get_devices_missing_view,
    apply_css_prefix,
    build_template_ports,
    collect_device_ports,
    build_panels,
)
from .grid_css import (
    BASE_SELECTOR,
    EMPTY_TOKEN,
    area_problems,
    generate_layout_css,
    normalize_config,
    parse_grid_css,
)
from django.http import Http404, HttpResponse, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
import json
from django.apps import apps
from django.views import View as DjangoView
from django.conf import settings
import pprint

from netbox.views.generic import BulkImportView
from utilities.paginator import EnhancedPaginator, get_paginate_count
from .forms import DeviceViewImportForm


# A patch panel has rear ports and no interfaces; everything else counts as a network device.
_IS_PATCH_PANEL = Exists(RearPort.objects.filter(device=OuterRef("pk"))) & ~Exists(
    Interface.objects.filter(device=OuterRef("pk"))
)
SITE_DISPLAY_FILTERS = {
    "network": {"pk__in": Device.objects.exclude(_IS_PATCH_PANEL).values("pk")},
    "patch": {"pk__in": Device.objects.filter(_IS_PATCH_PANEL).values("pk")},
}

SITE_SORT_ORDERS = {
    "name": ("name", "pk"),
    "role": ("role__name", "name", "pk"),
    "location": ("location__name", "rack__name", "-position", "name", "pk"),
}

PREVIEW_CELL_SIZES = {"small": 20, "medium": 40, "large": 60}


def render_layout_preview(layout, ports, display_size="medium"):
    """
    Render one layout variant with the production port templates.  Only ports
    placed in the grid are drawn; the rest would be auto-placed into extra
    implicit grid tracks and distort the preview.
    """
    cell = PREVIEW_CELL_SIZES.get(display_size, 40)
    placed = {token for row in layout["grid"] for token in row if token != EMPTY_TOKEN}
    shown = [port for port in ports if port.stylename in placed]
    return render_to_string(
        "netbox_device_view/includes/_preview.html",
        {
            "css": apply_css_prefix(generate_layout_css(layout, selector=BASE_SELECTOR), "dv-preview"),
            "cell": cell,
            "ports": shown,
            "unplaced": len(ports) - len(shown),
            "unmatched": sorted(placed - {port.stylename for port in ports}),
            "display_size": display_size if display_size in PREVIEW_CELL_SIZES else "medium",
            "link_type": "interface",
            "cable_colors": "vlan_role",
            "port_type": "vlan_letter",
        },
    )


class DeviceViewView(generic.ObjectView):
    queryset = models.DeviceView.objects
    template_name = "netbox_device_view/deviceview_detail.html"

    def get_extra_context(self, request, instance):
        device_type = instance.device_types.first()
        parsed = parse_grid_css(instance.grid_template_area)
        previews = []
        if device_type is not None:
            ports = build_template_ports(device_type)
            previews = [
                {"label": layout["label"] or layout["selector"], "html": render_layout_preview(layout, ports)}
                for layout in parsed["layouts"]
            ]
        return {
            "previews": previews,
            "preview_device_type": device_type,
            "layouts": parsed["layouts"],
        }


class DeviceViewListView(generic.ObjectListView):
    queryset = models.DeviceView.objects
    table = tables.DeviceViewTable


class DeviceViewEditView(generic.ObjectEditView):
    queryset = models.DeviceView.objects
    form = forms.DeviceViewForm
    template_name = "netbox_device_view/deviceview_edit.html"

    def get_extra_context(self, request, instance):
        from . import config

        return {"plugin_version": config.version}


class DeviceViewBulkImportView(BulkImportView):
    queryset = models.DeviceView.objects.all()
    model_form = DeviceViewImportForm


class DeviceViewDeleteView(generic.ObjectDeleteView):
    queryset = models.DeviceView.objects


class DeviceViewBulkDeleteView(generic.BulkDeleteView):
    queryset = models.DeviceView.objects
    table = tables.DeviceViewTable


class DeviceTypeLayoutDataView(DjangoView):

    def get(self, request, pk):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)

        try:
            device_type = DeviceType.objects.get(pk=pk)
        except DeviceType.DoesNotExist:
            raise Http404

        return JsonResponse(get_device_type_layout_data(device_type))


def _preview_error(request, message):
    return render(request, "netbox_device_view/includes/_preview_error.html", {"error": message})


class DeviceViewParseCssView(DjangoView):
    """Parse DeviceView CSS into builder layouts (used when the Advanced CSS is edited)."""

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)
        parsed = parse_grid_css(request.POST.get("css", ""))
        if not parsed["layouts"]:
            return JsonResponse({"error": "No grid-template-areas rule found in this CSS."}, status=400)
        return JsonResponse(parsed)


class DeviceViewPreviewView(DjangoView):
    """Render an HTML fragment previewing one variant of a (possibly unsaved) layout."""

    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)
        if not request.user.has_perm("netbox_device_view.view_deviceview"):
            return JsonResponse({"error": "Permission denied"}, status=403)

        try:
            config = normalize_config(json.loads(request.POST.get("layout_config") or "{}"))
        except json.JSONDecodeError:
            return HttpResponseBadRequest("Invalid layout_config")
        layouts = config["layouts"] if config else parse_grid_css(request.POST.get("grid_template_area"))["layouts"]
        if not layouts:
            return _preview_error(request, "Nothing to preview yet. Assign ports in the grid.")

        try:
            layout = layouts[int(request.POST.get("variant") or 0)]
        except (ValueError, IndexError):
            layout = layouts[0]

        problems = area_problems(layout["grid"])
        if problems:
            return _preview_error(
                request,
                "The browser would ignore this grid: "
                + " ".join(f"'{token}' {problem}" for token, problem in problems.items()),
            )

        ports = None
        device_id = request.POST.get("device_id")
        if device_id:
            device = Device.objects.restrict(request.user, "view").filter(pk=device_id).first()
            if device is not None:
                ports = collect_device_ports(device)
        if ports is None:
            device_type = DeviceType.objects.filter(pk=request.POST.get("device_type_id") or 0).first()
            if device_type is None:
                return _preview_error(request, "Select a reference device type to preview.")
            ports = build_template_ports(device_type)

        return HttpResponse(render_layout_preview(layout, ports, request.POST.get("display_size", "medium")))


class DeviceTypeDevicesView(DjangoView):
    """List devices of a device type, for the builder's reference-device picker."""

    def get(self, request, pk):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=403)
        devices = (
            Device.objects.restrict(request.user, "view")
            .filter(device_type_id=pk)
            .select_related("site")
            .order_by("name")[:100]
        )
        return JsonResponse(
            {
                "devices": [
                    {"id": d.pk, "name": f"{d.name or d.pk} ({d.site})"} for d in devices
                ]
            }
        )


@register_model_view(Device, "deviceview", path="device-view")
class DeviceDeviceView(generic.ObjectView):
    queryset = models.DeviceView.objects

    tab = ViewTab(
        label="Device View",
        badge=lambda obj: models.DeviceView.objects.filter(
            device_types=obj.device_type
        ).count(),
        hide_if_empty=True,
    )

    def get_extra_context(self, request, instance):
        dv, modules, ports_chassis = prepare(instance)
        display_size_param = request.GET.get("display_size", "medium")
        if display_size_param == "small":
            display_cell_size = 20
        elif display_size_param == "large":
            display_cell_size = 60
        else:  # medium or default
            display_cell_size = 40
        
        render_height = instance.device_type.u_height * 2 * display_cell_size + instance.device_type.u_height * 2
        
        return {
            "device_view": models.DeviceView.objects.filter(
                device_types=instance.device_type
            ).first(),
            "dv": dv,
            "modules": modules,
            "render_height": render_height,
            "ports_chassis": ports_chassis,
            "panels": build_panels(instance, ports_chassis or {}),
            "cable_colors": request.GET.get("cable_colors", "vlan_role"),
            "port_type": request.GET.get("port_type", "vlan_letter"),
            "display_size": display_size_param,
            "link_type": request.GET.get("link_type", "interface"),
            "something_else": request.GET.get("something_else", "off"),
        }

    def get_object(self, **kwargs):
        return Device.objects.get(pk=kwargs.get("pk"))


# Define the view class without decorator first
class SiteDeviceElevationView(generic.ObjectView):
    queryset = Site.objects.all()
    template_name = 'netbox_device_view/site_device_elevation.html'

    def get_extra_context(self, request, instance):
        request.GET = request.GET.copy()
        request.GET['site_slug'] = instance.slug

        site_slug = request.GET.get('site_slug')
        show = request.GET.get("show", "both")
        sort = request.GET.get("sort", "name")
        display_size_param = request.GET.get("display_size", "medium")

        if display_size_param == "small":
            display_cell_size = 20
        elif display_size_param == "large":
            display_cell_size = 60
        else:
            display_cell_size = 40

        # ------------------------------------------------------------------
        # Step 1 – Identify which device_types have a DeviceView defined.
        # ------------------------------------------------------------------
        device_types_with_view = models.DeviceView.objects.values_list('device_types', flat=True)

        # ------------------------------------------------------------------
        # Step 2 – Fetch all matching devices in a SINGLE query with deep
        # prefetch_related so that per-device and per-interface sub-queries
        # are avoided inside prepare() / process_interfaces() / process_ports().
        #
        # Key relationships that were previously triggering N+1 queries:
        #   • consoleports          – was a separate query per device
        #   • interfaces__cable     – lazy-loaded in template / process_interfaces
        #   • interfaces___path     – needed by connected_endpoints
        #   • interfaces__untagged_vlan__role – lazy-loaded in process_interfaces
        #   • frontports__cable / rearports__cable – lazy-loaded in template
        #   • virtual_chassis__members (+ their own sub-relations)
        # ------------------------------------------------------------------
        # One entry per virtual chassis (drawing any member draws the whole
        # stack), in the requested order, paginated like NetBox lists.
        candidates = (
            Device.objects
            .filter(site__slug=site_slug, device_type_id__in=device_types_with_view)
            .filter(**SITE_DISPLAY_FILTERS.get(show, {}))
            .order_by(*SITE_SORT_ORDERS.get(sort, SITE_SORT_ORDERS["name"]))
            .values_list("pk", "virtual_chassis_id")
        )
        entry_ids = []
        seen_chassis = set()
        for pk, chassis_id in candidates:
            if chassis_id:
                if chassis_id in seen_chassis:
                    continue
                seen_chassis.add(chassis_id)
            entry_ids.append(pk)
        paginator = EnhancedPaginator(entry_ids, get_paginate_count(request))
        page = paginator.get_page(request.GET.get("page"))
        page_ids = list(page.object_list)

        devices_list = list(
            Device.objects
            .filter(pk__in=page_ids)
            .select_related(
                'device_type',
                'virtual_chassis',
            )
            .prefetch_related(
                # Modules
                'modules',
                # Interfaces and their deeply-nested relations
                'interfaces__cable',
                'interfaces___path',                    # CablePath → powers connected_endpoints
                'interfaces__untagged_vlan__role',
                'interfaces__tagged_vlans',
                # Front / rear ports
                'frontports__cable',
                'rearports__cable',
                # Console ports (replaces per-device ConsolePort.objects.filter())
                'consoleports',
                # Virtual-chassis members and their sub-relations
                'virtual_chassis__members__device_type',
                'virtual_chassis__members__modules',
                'virtual_chassis__members__interfaces__cable',
                'virtual_chassis__members__interfaces___path',
                'virtual_chassis__members__interfaces__untagged_vlan__role',
                'virtual_chassis__members__consoleports',
            )
        )
        devices_list.sort(key=lambda device: page_ids.index(device.pk))

        # ------------------------------------------------------------------
        # Build the DeviceView lookup in ONE query for all device_types on
        # this page (including stack members), so prepare() issues no
        # per-device DeviceView queries.
        # ------------------------------------------------------------------
        device_type_ids = {d.device_type_id for d in devices_list}
        for device in devices_list:
            if device.virtual_chassis_id:
                device_type_ids.update(m.device_type_id for m in device.virtual_chassis.members.all())
        dv_lookup = build_device_view_lookup(device_type_ids)

        prepared_devices_data = []
        for device in devices_list:
            instance_id = f"dev-{device.pk}"
            dv_css_map, modules_map, ports_chassis_map = prepare(
                device,
                instance_prefix=instance_id,
                device_view_lookup=dv_lookup,
            )

            if dv_css_map is not None:
                device_render_height = int(
                    device.device_type.u_height * 2 * display_cell_size
                    + device.device_type.u_height * 2
                )
                prepared_devices_data.append({
                    'device_obj': device,
                    'chassis': device.virtual_chassis,
                    'instance_id': instance_id,
                    'dv_css_map': dv_css_map,
                    'modules_map': modules_map,
                    'panels': build_panels(device, ports_chassis_map),
                    'device_render_height': device_render_height,
                })

        return {
            'prepared_devices': prepared_devices_data,
            'missing_devices': get_devices_missing_view(instance, SITE_DISPLAY_FILTERS.get(show)),
            'title': 'Port View',
            'cable_colors': request.GET.get("cable_colors", "vlan_role"),
            'port_type': request.GET.get("port_type", "vlan_letter"),
            'display_size': display_size_param,
            'link_type': request.GET.get("link_type", "interface"),
            'show': show,
            'sort': sort,
            'show_site_filters': True,
            'paginator': paginator,
            'page': page,
        }

    tab = ViewTab(
        label=settings.PLUGINS_CONFIG.get('netbox_device_view', {}).get('ports_tab_label', 'Port View'),
        badge=lambda obj: obj.devices.filter(
            device_type_id__in=models.DeviceView.objects.values_list('device_types', flat=True)
        ).count(),
        hide_if_empty=True,
    )


# Conditionally register the view based on plugin settings
if settings.PLUGINS_CONFIG.get('netbox_device_view', {}).get('show_site_ports', True):
    SiteDeviceElevationView = register_model_view(Site, name='ports', path='ports')(SiteDeviceElevationView)
