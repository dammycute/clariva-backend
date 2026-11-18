from rest_framework import permissions

ADMIN_ROLES = ('super_admin', 'school_admin', 'admin_officer', 'principal')
STAFF_WRITE_ROLES = ADMIN_ROLES + ('teacher',)


class RoleWritePermission(permissions.BasePermission):
    """Role gate for school-scoped ViewSets.

    Reads need an authenticated user (or a role in `read_roles` if the view sets
    it). Writes need a role in the view's `write_roles` (default: ADMIN_ROLES).
    """

    def has_permission(self, request, view):
        user = request.user
        if not (user and user.is_authenticated):
            return False
        role = getattr(user, 'role', None)
        read_roles = getattr(view, 'read_roles', None)
        if request.method in permissions.SAFE_METHODS:
            return read_roles is None or role in read_roles
        return role in getattr(view, 'write_roles', ADMIN_ROLES)
