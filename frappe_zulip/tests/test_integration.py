"""Bench tests: bench --site <test-site> run-tests --app frappe_zulip"""

from unittest.mock import MagicMock, patch

import frappe
from frappe.desk.doctype.notification_settings.notification_settings import create_notification_settings
from frappe.email.doctype.notification.notification import clear_notification_cache, evaluate_alert
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, add_to_date, get_url_to_form, now_datetime, nowdate

from frappe_zulip.frappe_zulip.doctype.zulip_message.zulip_message import MAX_ATTEMPTS, ZulipMessage
from frappe_zulip.outbox import deliver, queue_channel_message, queue_direct_message, retry_pending
from frappe_zulip.users import sync_users
from frappe_zulip.zulip import ZulipClient, ZulipError

USER = "zulip-test@example.com"


class TestZulipIntegration(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("User", USER):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": USER,
					"first_name": "Zulip",
					"last_name": "Tester",
					"send_welcome_email": 0,
					"roles": [{"role": "System Manager"}],
				}
			).insert(ignore_permissions=True)
		create_notification_settings(USER)
		frappe.db.commit()

	def setUp(self):
		super().setUp()
		# Cleanups run last-in first-out: roll back, then drop caches that outlived the rollback.
		self.addCleanup(clear_notification_cache)
		self.addCleanup(frappe.clear_document_cache, "Zulip Settings", "Zulip Settings")
		self.addCleanup(frappe.db.rollback)

		settings = frappe.get_single("Zulip Settings")
		settings.update(
			{
				"enabled": 1,
				"dry_run": 0,
				"server_url": "https://zulip.example.com",
				"bot_email": "erp-bot@zulip.example.com",
				"api_key": "secret",
				"default_channel": "ERPNext",
				"default_topic": "Notifications",
			}
		)
		settings.set("dm_notification_types", [{"notification_type": "Assignment"}])
		settings.save()
		frappe.db.set_value("User", USER, "zulip_user_id", 42)

		# Delivery is driven by calling deliver() directly.
		self.enqueue = patch("frappe.enqueue").start()
		self.send_channel = patch.object(ZulipClient, "send_channel_message", return_value=101).start()
		self.send_direct = patch.object(ZulipClient, "send_direct_message", return_value=102).start()
		self.addCleanup(patch.stopall)

	def set_settings(self, **values):
		settings = frappe.get_single("Zulip Settings")
		settings.update(values)
		settings.save()

	def test_channel_option_installed(self):
		options = frappe.get_meta("Notification").get_field("channel").options.split("\n")
		self.assertIn("Zulip", options)

	def test_channel_message_sent(self):
		name = queue_channel_message("#erp-test", "TASK-1", "hi")
		deliver(name)
		self.send_channel.assert_called_once_with("erp-test", "TASK-1", "hi")
		message = frappe.get_doc("Zulip Message", name)
		self.assertEqual(message.status, "Sent")
		self.assertEqual(message.zulip_message_id, 101)
		self.assertIsNone(message.next_attempt)

	def test_direct_message_uses_zulip_user_id(self):
		deliver(queue_direct_message(USER, "hi"))
		self.send_direct.assert_called_once_with([42], "hi")

	def test_direct_message_error_suggests_sync(self):
		frappe.db.set_value("User", USER, "zulip_user_id", 0)
		self.send_direct.side_effect = ZulipError("Invalid user", status=400)
		name = queue_direct_message(USER, "hi")
		deliver(name)
		self.send_direct.assert_called_once_with([USER], "hi")
		message = frappe.get_doc("Zulip Message", name)
		self.assertEqual(message.status, "Failed")
		self.assertIn("Sync Users", message.error)

	def test_user_opt_out(self):
		frappe.db.set_value("Notification Settings", USER, "enable_zulip_notifications", 0)
		self.assertIsNone(queue_direct_message(USER, "hi"))

	def test_disabled_does_not_queue(self):
		self.set_settings(enabled=0)
		self.assertIsNone(queue_channel_message("erp-test", "t", "hi"))

	def test_dry_run_records_without_sending(self):
		self.set_settings(dry_run=1)
		name = queue_channel_message("erp-test", "t", "hi")
		deliver(name)
		self.send_channel.assert_not_called()
		self.assertEqual(frappe.db.get_value("Zulip Message", name, "status"), "Skipped")

	def test_transient_error_is_retried(self):
		self.send_channel.side_effect = ZulipError("Service unavailable", status=503)
		name = queue_channel_message("erp-test", "t", "hi")
		deliver(name)
		message = frappe.get_doc("Zulip Message", name)
		self.assertEqual((message.status, message.attempts), ("Queued", 1))
		self.assertGreater(message.next_attempt, now_datetime())

		deliver(name)  # Backoff hasn't elapsed.
		self.assertEqual(self.send_channel.call_count, 1)

		self.send_channel.side_effect = None
		frappe.db.set_value("Zulip Message", name, "next_attempt", add_to_date(now_datetime(), minutes=-1))
		with patch("frappe.db.commit"):
			retry_pending()
		message.reload()
		self.assertEqual((message.status, message.attempts), ("Sent", 2))

	def test_gives_up_after_max_attempts(self):
		self.send_channel.side_effect = ZulipError("Service unavailable", status=503)
		name = queue_channel_message("erp-test", "t", "hi")
		frappe.db.set_value(
			"Zulip Message",
			name,
			{"attempts": MAX_ATTEMPTS - 1, "next_attempt": add_to_date(now_datetime(), minutes=-1)},
		)
		deliver(name)
		message = frappe.get_doc("Zulip Message", name)
		self.assertEqual((message.status, message.error), ("Failed", "Service unavailable"))

	def test_permanent_error_fails(self):
		self.send_channel.side_effect = ZulipError("Channel 'nope' does not exist", status=400)
		name = queue_channel_message("nope", "t", "hi")
		deliver(name)
		self.assertEqual(frappe.db.get_value("Zulip Message", name, "status"), "Failed")

	def test_manual_retry(self):
		self.send_channel.side_effect = ZulipError("Channel 'nope' does not exist", status=400)
		name = queue_channel_message("nope", "t", "hi")
		deliver(name)
		self.enqueue.reset_mock()

		message = frappe.get_doc("Zulip Message", name)
		message.retry()
		self.assertEqual((message.status, message.attempts), ("Queued", 0))
		self.assertEqual(self.enqueue.call_args.kwargs["name"], name)

	def test_clear_old_logs_keeps_queued(self):
		sent = queue_channel_message("erp-test", "t", "sent")
		deliver(sent)
		queued = queue_channel_message("erp-test", "t", "queued")
		for name in (sent, queued):
			frappe.db.set_value(
				"Zulip Message", name, "modified", add_days(now_datetime(), -60), update_modified=False
			)
		ZulipMessage.clear_old_logs(30)
		self.assertFalse(frappe.db.exists("Zulip Message", sent))
		self.assertTrue(frappe.db.exists("Zulip Message", queued))

	def make_notification(self, **values):
		return frappe.get_doc(
			{
				"doctype": "Notification",
				"name": f"Zulip Test {frappe.generate_hash(length=6)}",
				"channel": "Zulip",
				"document_type": "ToDo",
				"event": "New",
				"message": "New to-do: {{ doc.description }} for {{ zulip.mention(doc.allocated_to) }}",
				"recipients": [{"receiver_by_document_field": "allocated_to"}],
				**values,
			}
		)

	def get_messages(self, notification):
		return frappe.get_all(
			"Zulip Message",
			filters={"source": f"Notification: {notification.name}"},
			fields=["message_type", "channel", "topic", "user", "content", "reference_name"],
		)

	def test_notification_needs_a_destination(self):
		notification = self.make_notification(zulip_post_to_channel=0, zulip_dm_recipients=0)
		self.assertRaises(frappe.ValidationError, notification.insert)

	def test_notification_posts_and_sends_dms(self):
		notification = self.make_notification(zulip_dm_recipients=1, zulip_mention_recipients=1).insert()
		todo = frappe.get_doc({"doctype": "ToDo", "description": "Calibrate", "allocated_to": USER}).insert()

		messages = self.get_messages(notification)
		by_type = {message.message_type: message for message in messages}
		self.assertEqual(len(messages), 2)

		post, dm = by_type["Channel"], by_type["Direct"]
		self.assertEqual((post.channel, post.topic), ("ERPNext", "Notifications"))
		self.assertTrue(post.content.startswith("@**Zulip Tester|42**\n\n"))
		self.assertEqual(dm.user, USER)
		self.assertIn("New to-do: Calibrate for @**Zulip Tester|42**", dm.content)
		self.assertIn(get_url_to_form("ToDo", todo.name), dm.content)
		self.assertEqual(dm.reference_name, todo.name)

	def test_notification_channel_and_topic_overrides(self):
		notification = self.make_notification(
			zulip_stream="erp-test", zulip_topic="{{ zulip.topic(doc.doctype, doc.name) }}"
		).insert()
		todo = frappe.get_doc({"doctype": "ToDo", "description": "Calibrate", "allocated_to": USER}).insert()

		[post] = self.get_messages(notification)
		self.assertEqual((post.channel, post.topic), ("erp-test", f"{todo.name}: Calibrate"))

	def make_todo(self, days_from_today, **values):
		return frappe.get_doc(
			{
				"doctype": "ToDo",
				"description": "Calibrate",
				"allocated_to": USER,
				"date": add_days(nowdate(), days_from_today),
				**values,
			}
		).insert()

	def test_overdue_repeats(self):
		todos = {days_late: self.make_todo(-days_late).name for days_late in (0, 1, 2, 3, 4, 7, 8)}
		closed = self.make_todo(-4, status="Closed").name
		notification = self.make_notification(
			event="Days After",
			date_changed="date",
			days_in_advance=1,
			condition='doc.status == "Open"',
			zulip_repeat_days=3,
		).insert()

		def matches():
			found = {doc.name for doc in notification.get_documents_for_today()}
			return sorted(days for days, name in todos.items() if name in found), closed in found

		# First reminder a day late, then every 3 days.
		self.assertEqual(matches(), ([1, 4, 7], False))

		notification.zulip_repeat_days = 0
		self.assertEqual(matches(), ([1], False))

	def test_todo_due_tomorrow_rule(self):
		notification = frappe.get_doc("Notification", "Zulip: ToDo Due Tomorrow")
		todo = self.make_todo(
			1, description="<p>Calibrate &amp; ship</p>", reference_type="User", reference_name=USER
		)
		self.assertIn(todo.name, {doc.name for doc in notification.get_documents_for_today()})

		evaluate_alert(todo, notification, notification.event)
		[dm] = self.get_messages(notification)
		self.assertEqual(dm.user, USER)
		self.assertTrue(dm.content.startswith(":calendar: **Due tomorrow:** Calibrate & ship"))
		self.assertIn(f"[User {USER}]({get_url_to_form('User', USER)})", dm.content)

	def test_notification_log_forwarded(self):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"type": "Assignment",
				"for_user": USER,
				"from_user": "Administrator",
				"subject": "<b>Administrator</b> assigned you a new task",
				"email_content": "<p>Please calibrate</p>",
				"document_type": "ToDo",
				"document_name": "TODO-TEST",
			}
		).insert(ignore_permissions=True)

		message = frappe.get_last_doc("Zulip Message", filters={"source": "Notification Log: Assignment"})
		self.assertEqual(message.user, USER)
		self.assertTrue(message.content.startswith("**Administrator** assigned you a new task"))
		self.assertIn("```quote\nPlease calibrate\n```", message.content)
		self.assertIn(get_url_to_form("ToDo", "TODO-TEST"), message.content)

		# The referenced ToDo doesn't exist, which mustn't block delivery.
		deliver(message.name)
		self.assertEqual(frappe.db.get_value("Zulip Message", message.name, "status"), "Sent")

	def test_notification_log_type_not_forwarded(self):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"type": "Mention",
				"for_user": USER,
				"from_user": "Administrator",
				"subject": "Administrator mentioned you",
			}
		).insert(ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Zulip Message", {"source": "Notification Log: Mention"}))

	def test_sync_users(self):
		frappe.db.set_value("User", USER, "zulip_user_id", 0)
		client = MagicMock()
		client.get_users.return_value = [
			{"user_id": 99, "email": USER, "is_bot": True, "is_active": True},
			{
				"user_id": 77,
				"email": "user77@zulip.example.com",
				"delivery_email": USER.upper(),
				"is_bot": False,
				"is_active": True,
			},
		]
		result = sync_users(client)
		self.assertEqual(frappe.db.get_value("User", USER, "zulip_user_id"), 77)
		self.assertEqual(result["zulip_users"], 1)
		self.assertNotIn(USER, result["unmatched"])
