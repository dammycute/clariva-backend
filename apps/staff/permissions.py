from rest_framework import permissions

ADMIN_ROLES = ('super_admin', 'school_admin', 'principal', 'admin_officer')


class IsSchoolAdminRole(permissions.IsAuthenticated):
    """Allow only school admin/principal-level roles. Requires IsAuthenticated first."""
    def has_permission(self, request, view):
        return super().has_permission(request, view) and \
            getattr(request.user, 'role', None) in ADMIN_ROLES
