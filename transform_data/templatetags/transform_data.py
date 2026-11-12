from data_core.loading import display_value
from django import template

register = template.Library()


@register.filter
def cell(row: dict, key: str) -> str:
    """A preview cell as the user should read it (dates dd-mm-yyyy, Yes / No, blanks empty)."""
    return display_value(row.get(key))


@register.filter
def has(values, item) -> bool:
    """{% if form_values|has:name %} — `item` is in the list (as text)."""
    return str(item) in [str(value) for value in (values or [])]
