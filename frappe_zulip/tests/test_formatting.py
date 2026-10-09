import unittest

from frappe_zulip import formatting


class TestFormatting(unittest.TestCase):
	def test_truncate_leaves_short_text(self):
		self.assertEqual(formatting.truncate("short", 10), "short")

	def test_truncate_prefers_word_boundary(self):
		self.assertEqual(formatting.truncate("the quick brown fox jumps", 20), "the quick brown fox…")
		self.assertEqual(formatting.truncate("the quick brown foxes jump", 20), "the quick brown…")

	def test_truncate_cuts_long_words(self):
		result = formatting.truncate("a" * 30, 10)
		self.assertEqual(result, "a" * 9 + "…")

	def test_topic(self):
		self.assertEqual(formatting.topic("  TASK-1:\n  Calibrate  "), "TASK-1: Calibrate")
		self.assertEqual(formatting.topic(""), "(no topic)")
		self.assertEqual(formatting.topic(None), "(no topic)")
		self.assertLessEqual(len(formatting.topic("word " * 40)), formatting.MAX_TOPIC_LENGTH)

	def test_content(self):
		self.assertEqual(formatting.content("  hi \n"), "hi")
		self.assertEqual(len(formatting.content("x" * 20000)), formatting.MAX_CONTENT_LENGTH)

	def test_link_escapes_brackets(self):
		self.assertEqual(
			formatting.link("Task [draft]", "https://e.com/t"), "[Task (draft)](https://e.com/t)"
		)

	def test_mention(self):
		self.assertEqual(formatting.mention("Ada Lovelace", 7), "@**Ada Lovelace|7**")
		self.assertEqual(formatting.mention("Ada Lovelace", 7, silent=True), "@_**Ada Lovelace|7**")

	def test_quote(self):
		self.assertEqual(formatting.quote("hi"), "```quote\nhi\n```")
