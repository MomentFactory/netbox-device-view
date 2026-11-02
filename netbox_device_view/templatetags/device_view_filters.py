from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def css_safe(css):
    """
    Mark DeviceView CSS safe for a <style> block.  Models already reject "<",
    this backstop covers rows saved before that validation existed.
    """
    return mark_safe(str(css or "").replace("<", ""))
