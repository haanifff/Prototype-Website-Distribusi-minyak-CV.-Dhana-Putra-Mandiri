from django import template

register = template.Library()


@register.filter
def rupiah(value):
    return "Rp " + format(int(value or 0), ",").replace(",", ".")


@register.filter
def amount(value):
    return (
        format(value, ",").replace(",", ".")
        if isinstance(value, int) and not isinstance(value, bool)
        else value
    )
