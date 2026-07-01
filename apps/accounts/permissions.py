from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin


def user_role(user):
    return getattr(user, 'role', None)


def is_platform_admin(user):
    return bool(
        getattr(user, 'is_superuser', False)
        or user_role(user) in {'platform_admin', 'admin'}
    )


def is_firm_admin(user):
    return bool(
        is_platform_admin(user)
        or user_role(user) in {'firm_admin', 'principal'}
    )


def can_prepare_trust_records(user):
    return bool(
        is_platform_admin(user)
        or user_role(user) in {
            'firm_admin',
            'principal',
            'authorised_trust_user',
            'accountant',
            'solicitor',
        }
    )


def can_view_trust_records(user):
    return bool(
        can_prepare_trust_records(user)
        or user_role(user) in {'external_examiner'}
    )


def is_staff_user(user):
    return bool(
        is_platform_admin(user)
        or user_role(user) in {
            'firm_admin',
            'principal',
            'authorised_trust_user',
            'accountant',
            'staff',
            'solicitor',
        }
    )


class AdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_platform_admin(self.request.user)


class FirmAdminRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_firm_admin(self.request.user)


class AdminOrAccountantMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Legacy name retained.

    In Phase 22 this means a user who can prepare trust records:
    platform admin, firm admin, principal, authorised trust user,
    accountant, or legacy solicitor/admin.
    """
    def test_func(self):
        return can_prepare_trust_records(self.request.user)


class TrustRecordViewMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Read access for trust records, including external examiner read-only role.
    """
    def test_func(self):
        return can_view_trust_records(self.request.user)


class StaffRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        return is_staff_user(self.request.user)
