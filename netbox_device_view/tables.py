import django_tables2 as tables

from netbox.tables import NetBoxTable, ChoiceFieldColumn
from .grid_css import describe_grid_css
from .models import DeviceView


class DeviceViewTable(NetBoxTable):
    id = tables.Column(
        linkify={
            "viewname": "plugins:netbox_device_view:deviceview_edit",
            "args": [tables.A("pk")]
        }
    )
    name = tables.Column(linkify=True)
    device_types = tables.TemplateColumn(
        template_code="""
        {% with types=record.device_types.all %}
            {% for dt in types|slice:":3" %}
                <a href="{% url 'dcim:devicetype' pk=dt.pk %}">{{ dt.model }}</a>{% if not forloop.last %}, {% endif %}
            {% endfor %}
            {% if types|length > 3 %}
                <span class="text-muted" title="{% for dt in types %}{{ dt.model }}{% if not forloop.last %}, {% endif %}{% endfor %}">+{{ types|length|add:"-3" }} more</span>
            {% endif %}
        {% endwith %}
        """,
        verbose_name="Device Types",
        orderable=False,
    )
    layout = tables.Column(
        accessor="grid_template_area",
        verbose_name="Layout",
        orderable=False,
    )
    grid_template_area = tables.TemplateColumn(
        template_code="""
        <code class="text-truncate d-inline-block align-middle" style="max-width: 24rem;" title="{{ value }}">{{ value|truncatechars:60 }}</code>
        """,
        verbose_name="Grid Template Area",
    )

    class Meta(NetBoxTable.Meta):
        model = DeviceView
        fields = ("pk", "id", "name", "device_types", "layout", "grid_template_area")
        default_columns = ("id", "name", "device_types", "layout")

    def render_layout(self, value):
        return describe_grid_css(value)
