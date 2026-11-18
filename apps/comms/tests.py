from django.test import TestCase
from django.urls import resolve


class NotificationRoutingTests(TestCase):
    def test_notifications_list_resolves_to_notification_viewset(self):
        match = resolve('/api/comms/notifications/')
        self.assertEqual(match.url_name, 'notification-list')

    def test_announcements_list_still_resolves(self):
        match = resolve('/api/comms/')
        self.assertEqual(match.url_name, 'announcement-list')
