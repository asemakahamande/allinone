from django import template

register = template.Library()


@register.filter
def replace(value, args):
    """
    Replaces all occurrences of the first string with the second string.
    Usage: {{ value|replace:"old,new" }}
    """
    try:
        old, new = args.split(',')
        return value.replace(old, new)
    except Exception:
        return value


@register.filter
def get_item(dictionary, key):
    """
    Safely get a dictionary value by key.
    Usage: {{ my_dict|get_item:key }}
    """
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def attr(obj, attr_name):
    """
    Safely get an attribute from an object.
    Usage: {{ object|attr:"field_name" }}
    """
    try:
        return getattr(obj, attr_name)
    except Exception:
        return ""


@register.filter
def is_exam_component(value):
    """
    Returns True when a component label looks like an exam component.
    Usage: {% if component_name|is_exam_component %}...{% endif %}
    """
    try:
        return "exam" in str(value).strip().lower()
    except Exception:
        return False


