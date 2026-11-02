from dcim.models import ConsolePort
from .models import DeviceView
from django.core.exceptions import ObjectDoesNotExist
from django.apps import apps
from django.conf import settings

import re
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Query-count helpers
# ---------------------------------------------------------------------------

def build_device_view_lookup(device_type_ids):
    """
    Pre-fetch all DeviceView objects for the given device_type IDs and
    return a dict keyed by device_type_id → DeviceView instance.

    Replaces the per-device DeviceView.objects.filter(...).first() call
    that occurs inside prepare() when called in a loop, eliminating an
    N-queries-per-device pattern.

    Usage::

        lookup = build_device_view_lookup(
            [d.device_type_id for d in devices]
        )
        for device in devices:
            prepare(device, device_view_lookup=lookup)
    """
    device_view_model = apps.get_model('netbox_device_view', 'DeviceView')
    qs = (
        device_view_model.objects
        .filter(device_types__id__in=device_type_ids)
        .prefetch_related('device_types')
    )
    lookup = {}
    for dv_obj in qs:
        for dt in dv_obj.device_types.all():
            # Keep the first DeviceView found for each device_type (mirrors .first())
            if dt.id not in lookup:
                lookup[dt.id] = dv_obj
    return lookup


def apply_css_prefix(css_text, prefix):
    """Prefix every CSS selector block with *.prefix* so several views can share a page."""
    if not prefix:
        return css_text
    prefixed = []
    for line in css_text.splitlines():
        stripped = line.strip()
        if (stripped.startswith('.') or stripped.startswith('#')) and '{' in stripped:
            prefixed.append(f".{prefix} {stripped}")
        else:
            prefixed.append(line)
    return "\n".join(prefixed)


def build_template_ports(device_type):
    """
    Build stand-in port objects from a DeviceType's component templates so a
    layout can be previewed without a real Device.  The objects carry only the
    attributes the port templates read.
    """
    layout_data = get_device_type_layout_data(device_type)
    ports = []
    for key, is_port in (
        ("interfaces", False),
        ("front_ports", True),
        ("rear_ports", True),
        ("console_ports", True),
    ):
        for item in layout_data[key]:
            ports.append(
                SimpleNamespace(
                    name=item["name"],
                    stylename=item["area"],
                    port_number=extract_port_number(item["name"]),
                    type=item["type"],
                    is_port=is_port,
                    enabled=True,
                    cable=None,
                    connected_endpoints=[],
                    link_peers=[],
                    untagged_vlan=None,
                    vlan_role_color=None,
                    label="",
                    mode="",
                    poe_mode="",
                    poe_type="",
                )
            )
    return ports


def collect_device_ports(device):
    """Return the processed port list for a real Device, as prepare() would."""
    ports_chassis = {}
    process_interfaces(device.interfaces.all(), ports_chassis, device.name)
    process_ports(device.frontports.all(), ports_chassis, "Front")
    process_ports(device.rearports.all(), ports_chassis, "Rear")
    process_ports(device.consoleports.all(), ports_chassis, device.name)
    return [port for ports in ports_chassis.values() for port in ports]


def build_panels(device, ports_chassis):
    """
    Turn prepare()'s ports_chassis map into an ordered list of panels with a
    human label: stack members as "Member 2 · sw-02", extra strips as
    "Front ports"/"Rear ports" when the device has more than one strip.
    """
    members = {}
    if device.virtual_chassis_id:
        members = {member.vc_position: member for member in device.virtual_chassis.members.all()}

    panels = []
    for key, ports in ports_chassis.items():
        if key in members:
            label = f"Member {key} · {members[key].name}"
        elif key in ("Front", "Rear") and len(ports_chassis) > 1:
            label = f"{key} ports"
        else:
            label = ""
        panels.append({"key": key, "label": label, "ports": ports})

    if members:
        panels.sort(key=lambda panel: panel["key"] if isinstance(panel["key"], int) else 0)
    return panels


def get_devices_missing_view(site, extra_filter=None, user=None):
    """
    Return devices at *site* whose role is listed in the ``missing_view_roles``
    plugin setting but whose device type has no DeviceView mapping, grouped by
    device type: ``[{"device_type": DeviceType, "devices": [Device, ...]}, ...]``.
    """
    from dcim.models import Device

    roles = settings.PLUGINS_CONFIG.get("netbox_device_view", {}).get(
        "missing_view_roles", []
    )
    if not roles:
        return []

    devices = Device.objects.restrict(user, "view") if user is not None else Device.objects.all()
    devices = (
        devices.filter(site=site, role__slug__in=roles)
        .filter(device_type__device_views__isnull=True)
        .filter(**(extra_filter or {}))
        .select_related("device_type__manufacturer", "role")
        .order_by("device_type__model", "name")
    )

    grouped = {}
    for device in devices:
        entry = grouped.setdefault(
            device.device_type_id, {"device_type": device.device_type, "devices": []}
        )
        entry["devices"].append(device)
    return list(grouped.values())


def get_hostname_last_segment(hostname):
    """
    Extract the last segment of a hostname after splitting by dashes.
    
    Args:
        hostname: The hostname string to process
    
    Returns:
        The last segment of the hostname after splitting by '-'
        If no dashes are present, returns the original hostname
        
    Examples:
        "FVR2-CTL-XAG01" → "XAG01"
        "switch-01" → "01" 
        "router" → "router"
    """
    if not isinstance(hostname, str):
        return hostname
    
    parts = hostname.split('-')
    if parts:
        return parts[-1]
    return hostname


def extract_port_number(port_name):
    """
    Extract the last contiguous group of digits from a port name.
    Preserves zero-padding.
    
    Args:
        port_name: The port name string to process
    
    Returns:
        The last contiguous group of digits as a string
        Returns empty string if no digits are found
        
    Examples:
        "Port 1" → "1"
        "Port 01" → "01"
        "GigabitEthernet1/0/1" → "1"
        "Ethernet0/0/12" → "12"
        "eth-0/1/2" → "2"
    """
    if not isinstance(port_name, str):
        return ""
    
    # Match the last contiguous group of digits
    match = re.search(r'(\d+)(?!.*\d)', port_name)
    if match:
        return match.group(1)
    return ""


def normalize_grid_area_name(name, fallback=None):
    """Return the same CSS-safe area name used for rendered ports."""
    if not isinstance(name, str):
        name = ""

    stylename = re.sub(r"[/\.\s\+]+", "-", name.lower())
    stylename = re.sub(r"-+", "-", stylename).strip("-")

    if not stylename and fallback is not None:
        stylename = f"iface-{fallback}"

    if stylename and (stylename[0].isdigit() or stylename[0] == "-"):
        stylename = f"p{stylename}"

    return stylename


def port_area_name(name):
    """Area name used for front, rear and console ports (see process_ports)."""
    stylename = re.sub(r"[^.a-zA-Z\d]", "-", str(name or "").lower())
    if stylename.isdigit():
        stylename = f"p{stylename}"
    return stylename


def get_device_type_layout_data(device_type):
    """Build serializable layout-builder data for a NetBox DeviceType."""
    def _templates(model_name, *manager_names):
        for manager_name in manager_names:
            manager = getattr(device_type, manager_name, None)
            if manager is not None:
                return manager.all().order_by("name")

        try:
            template_model = apps.get_model("dcim", model_name)
        except LookupError:
            return []

        return template_model.objects.filter(device_type=device_type).order_by("name")

    def _template_payload(template, port=False):
        return {
            "id": template.pk,
            "name": template.name,
            "area": port_area_name(template.name) if port else normalize_grid_area_name(template.name, template.pk),
            "type": getattr(template, "type", "") or "",
        }

    def _is_physical_interface_template(template):
        return getattr(template, "type", "") not in {"virtual", "lag"}

    front_image = getattr(device_type, "front_image", None)
    image_url = front_image.url if front_image else ""
    u_height = float(device_type.u_height or 1)
    rows = max(2, int(u_height * 2))

    front_ports = [
        _template_payload(template, port=True)
        for template in _templates("FrontPortTemplate", "front_port_templates", "frontporttemplates")
    ]

    return {
        "id": device_type.pk,
        "model": device_type.model,
        "u_height": u_height,
        "rows": rows,
        "columns": 32,
        "front_image_url": image_url,
        "interfaces": [
            _template_payload(template)
            for template in _templates("InterfaceTemplate", "interface_templates", "interfacetemplates")
            if _is_physical_interface_template(template)
        ],
        "front_ports": front_ports,
        # Front and rear ports share grid names and only the front is drawn,
        # so rear ports are offered only for devices without front ports.
        "rear_ports": [] if front_ports else [
            _template_payload(template, port=True)
            for template in _templates("RearPortTemplate", "rear_port_templates", "rearporttemplates")
        ],
        "console_ports": [
            _template_payload(template, port=True)
            for template in _templates("ConsolePortTemplate", "console_port_templates", "consoleporttemplates")
        ],
    }


def process_interfaces(interfaces, ports_chassis, dev):
    if interfaces is not None:
        for itf in interfaces:
            if itf.type == "virtual" or itf.type == "lag":
                continue
            stylename = re.sub(r"[/\.\s\+]+", "-", itf.name.lower())

            stylename = re.sub(r"-+", "-", stylename).strip("-")

            if not stylename:
                stylename = f"iface-{itf.pk}"

            itf.stylename = stylename

            if itf.stylename and (
                itf.stylename[0].isdigit() or itf.stylename[0] == "-"
            ):
                itf.stylename = f"p{itf.stylename}"

            # Extract port number from interface name
            itf.port_number = extract_port_number(itf.name)

            # Add hostname processing for connected endpoints
            if hasattr(itf, 'connected_endpoints') and itf.connected_endpoints:
                for ce in itf.connected_endpoints:
                    if hasattr(ce, 'device') and hasattr(ce.device, 'name'):
                        ce.device.name_last_segment = get_hostname_last_segment(ce.device.name)

            # Get VLAN role color from plugin configuration
            itf.vlan_role_color = None
            itf.debug_vlan_role_name = "N/A"

            if not hasattr(itf, 'untagged_vlan') or not itf.untagged_vlan:
                itf.debug_vlan_role_name = "No untagged VLAN"
            elif not itf.untagged_vlan.role:
                itf.debug_vlan_role_name = "Untagged VLAN has no role"
            else:
                role_name = itf.untagged_vlan.role.name
                itf.debug_vlan_role_name = role_name
                
                # Get color mapping from plugin configuration with safe fallbacks
                try:
                    # Try to get from PLUGINS_CONFIG
                    vlan_colors = settings.PLUGINS_CONFIG.get('netbox_device_view', {}).get('vlan_role_colors', {})
                    
                    # Fallback to default settings if not configured
                    if not vlan_colors:
                        from . import NetBoxDeviceViewConfig
                        vlan_colors = NetBoxDeviceViewConfig.default_settings.get('vlan_role_colors', {})
                    
                    # Look up color for this role, with gray as ultimate fallback
                    if role_name in vlan_colors:
                        itf.vlan_role_color = vlan_colors[role_name]
                    else:
                        # Default gray color for unmapped roles
                        itf.vlan_role_color = "6C757D"
                        
                except Exception as e:
                    # If anything goes wrong, use default gray and log the error
                    print(f"Error looking up VLAN role color for interface {itf.name}: {e}")
                    itf.vlan_role_color = "6C757D"

            if dev not in ports_chassis:
                ports_chassis[dev] = []
            ports_chassis[dev].append(itf)
    return ports_chassis


def process_ports(ports, ports_chassis, dev):
    if ports is not None:
        for port in ports:
            if port.type == "virtual":
                continue
            port.is_port = True
            port.stylename = port_area_name(port.name)

            # Extract port number from port name
            port.port_number = extract_port_number(port.name)

            port.debug_vlan_role_name = "N/A (Not an Interface)"
            port.vlan_role_color = None

            # Add hostname processing for link peers
            if hasattr(port, 'link_peers') and port.link_peers:
                for lp in port.link_peers:
                    if hasattr(lp, 'device') and hasattr(lp.device, 'name'):
                        lp.device.name_last_segment = get_hostname_last_segment(lp.device.name)

            if dev not in ports_chassis:
                ports_chassis[dev] = []
            ports_chassis[dev].append(port)
    return ports_chassis


def prepare(obj, instance_prefix=None, device_view_lookup=None):
    """
    Build the dv (CSS map), modules map, and ports_chassis map for *obj*.

    Parameters
    ----------
    obj : Device
        The Device instance to prepare data for.
    instance_prefix : str, optional
        CSS class prefix used when rendering multiple devices on the same
        page (e.g. the site elevation view).
    device_view_lookup : dict, optional
        Pre-built mapping of ``device_type_id → DeviceView`` produced by
        :func:`build_device_view_lookup`.  When supplied, the per-device
        ``DeviceView`` database query is skipped entirely; when omitted the
        original per-call query is issued (single-device views, template
        extensions, etc.).
    """
    ports_chassis = {}
    dv = {}
    modules = {}
    device_view_model = apps.get_model('netbox_device_view', 'DeviceView')

    def _get_device_view(device):
        """Return the DeviceView for *device*, using the lookup when available."""
        if device_view_lookup is not None:
            return device_view_lookup.get(device.device_type_id)
        return device_view_model.objects.filter(device_types=device.device_type).first()

    def _apply_prefix(css_text):
        return apply_css_prefix(css_text, instance_prefix)

    def _console_ports(device):
        """
        Return console ports for *device*.

        If console ports were prefetched (i.e. the attribute is cached on
        the queryset) we use the cache; otherwise fall back to a DB query.
        This avoids an extra SELECT per device when the view has already
        prefetched ``consoleports``.
        """
        # Django caches prefetch_related results on the instance's
        # _prefetched_objects_cache dict under the accessor name.
        cache = getattr(device, '_prefetched_objects_cache', {})
        if 'consoleports' in cache:
            return device.consoleports.all()
        return ConsolePort.objects.filter(device_id=device.id)

    try:
        if obj.virtual_chassis is None:
            device_view_instance = _get_device_view(obj)
            if not device_view_instance:
                return None, None, None
            grid_css = device_view_instance.grid_template_area

            dv[1] = _apply_prefix(grid_css)

            modules[1] = obj.modules.all()
            ports_chassis = process_interfaces(
                obj.interfaces.all(), ports_chassis, obj.name
            )
            # Patch panels are read from the front; rear ports are only drawn
            # when a device has no front ports at all.
            front_ports = obj.frontports.all()
            ports_chassis = process_ports(front_ports, ports_chassis, "Front")
            if not front_ports:
                ports_chassis = process_ports(obj.rearports.all(), ports_chassis, "Rear")
            ports_chassis = process_ports(
                _console_ports(obj),
                ports_chassis,
                obj.name,
            )
        else:
            for member in obj.virtual_chassis.members.all():
                member_device_view_instance = _get_device_view(member)
                if not member_device_view_instance:
                    continue
                member_grid_css = member_device_view_instance.grid_template_area

                processed_member_grid_css = member_grid_css.replace(
                    ".area", ".area.d" + str(member.vc_position)
                )

                dv[member.vc_position] = _apply_prefix(processed_member_grid_css)

                modules[member.vc_position] = member.modules.all()
                ports_chassis = process_interfaces(
                    member.interfaces.all(), ports_chassis, member.vc_position
                )
                ports_chassis = process_ports(
                    _console_ports(member),
                    ports_chassis,
                    member.vc_position,
                )
    except ObjectDoesNotExist:
        return None, None, None

    return dv, modules, ports_chassis
