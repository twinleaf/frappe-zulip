"""Zulip markdown helpers. Kept free of Frappe imports so they can be tested standalone."""

MAX_TOPIC_LENGTH = 60
# Zulip's default max_message_length.
MAX_CONTENT_LENGTH = 10000


def truncate(text: str, limit: int) -> str:
	"""Shorten `text` to at most `limit` characters, preferring a word boundary."""
	if len(text) <= limit:
		return text
	cut = text[: limit - 1]
	if not text[limit - 1].isspace():
		head, sep, _ = cut.rpartition(" ")
		if sep and len(head) >= limit // 2:
			cut = head
	return cut.rstrip() + "…"


def topic(text: str | None) -> str:
	return truncate(" ".join((text or "").split()), MAX_TOPIC_LENGTH) or "(no topic)"


def content(text: str | None) -> str:
	return truncate((text or "").strip(), MAX_CONTENT_LENGTH)


def link(label: str, url: str) -> str:
	# Brackets in the label would end the link text early.
	label = label.replace("[", "(").replace("]", ")")
	return f"[{label}]({url})"


def mention(full_name: str, user_id: int, silent: bool = False) -> str:
	return f"@{'_' if silent else ''}**{full_name}|{user_id}**"


def quote(text: str) -> str:
	return f"```quote\n{text}\n```"
