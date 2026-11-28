from .models import GuardianStudent


def generated_parent(**child):
    """The parent account made along with a child's login, found by any filter on the link."""
    link = (GuardianStudent.objects.filter(guardian__role='parent', **child)
            .exclude(guardian__email__endswith='@parent.clariva.ng')   # old phone-number accounts
            .select_related('guardian').order_by('created_at').first())
    return link.guardian if link else None
