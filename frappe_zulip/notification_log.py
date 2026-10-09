"""Forward in-app notifications (the bell icon) to Zulip as direct messages."""

from frappe.core.utils import html2text
from frappe.utils import get_url, get_url_to_form

from frappe_zulip import formatting
from frappe_zulip.frappe_zulip.doctype.zulip_settings.zulip_settings import get_settings
from frappe_zulip.outbox import queue_direct_message

MAX_EXCERPT_LENGTH = 2000


def forward_to_zulip(doc, method=None):
	settings = get_settings()
	if not settings.enabled or doc.type not in settings.get_dm_types():
		return
	queue_direct_message(
		doc.for_user,
		format_notification(doc),
		reference_doctype=doc.document_type,
		reference_name=doc.document_name,
		source=f"Notification Log: {doc.type}",
	)


def format_notification(doc) -> str:
	title = to_markdown(doc.title or doc.subject)
	parts = [title]

	excerpt = to_markdown(doc.description or doc.email_content)
	if excerpt and excerpt != title:
		parts.append(formatting.quote(formatting.truncate(excerpt, MAX_EXCERPT_LENGTH)))

	if url := get_link(doc):
		label = f"{doc.document_type} {doc.document_name}" if doc.document_name else "Open in ERPNext"
		parts.append(formatting.link(label, url))

	return "\n\n".join(part for part in parts if part)


def get_link(doc) -> str | None:
	if doc.link:
		return doc.link if doc.link.startswith(("http://", "https://")) else get_url(doc.link)
	if doc.document_type and doc.document_name:
		return get_url_to_form(doc.document_type, doc.document_name)
	return None


def to_markdown(html: str | None) -> str:
	# Zulip renders single newlines as line breaks, so don't hard-wrap.
	return html2text(html, wrap=False).strip() if html else ""
