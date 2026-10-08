"""Metadata-only continuation directory over existing project records."""
from urllib.parse import urlencode

from sqlalchemy import func
from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import ResearchTask, Message, Conversation, WikiUpdate, WikiPage
from app.models.review import LibraryReview
from app.workspaces.context import bind_workspace


ACTIVE = ('running', 'queued', 'pending')


def _item(kind, rid, title, status, when, route):
    return {'key': f'{kind}:{rid}', 'kind': kind, 'title': (title or '论文问答')[:300],
            'status': status, 'stamp': str(when) + ':' + status, 'time': str(when),
            'active': status in ACTIVE, 'route': route}


def _task_items(session, limit, include_drafts=False):
    items = []
    for model, kind, params in ((ResearchTask, 'research', lambda rid: {'task': rid}),
                                (LibraryReview, 'review', lambda rid: {'mode': 'review', 'review': rid})):
        query = select(model.id, model.question, model.status, model.updated_at)
        excluded = ['running'] if include_drafts else ['draft', 'running']
        rows = (session.exec(query.where(model.status == 'running')).all() +
                session.exec(query.where(model.status.not_in(excluded))
                             .order_by(model.updated_at.desc(), model.id).limit(limit)).all())
        items.extend(_item(kind, rid, title, status, when, 'research?' + urlencode(params(rid)))
                     for rid, title, status, when in rows)
    return items


def _wiki_events(session, limit):
    query = select(WikiUpdate.id, WikiPage.id, WikiPage.title, WikiUpdate.status, WikiUpdate.updated_at).join(
        WikiPage, WikiPage.id == WikiUpdate.page_id)
    rows = (session.exec(query.where(WikiUpdate.status.in_(['queued', 'running']))).all() +
            session.exec(query.where(WikiUpdate.status.not_in(['queued', 'running']))
                         .order_by(WikiUpdate.updated_at.desc()).limit(limit)).all())
    return [_item('wiki', uid, title, status, when, 'wiki?' + urlencode({'page': pid}))
            for uid, pid, title, status, when in rows]


def _chat_events(session, limit):
    # Notifications keep per-turn IDs so a new answer can become unread.
    query = select(Message.id, Message.conversation_id, Conversation.title, Message.delivery_status,
                   Message.created_at).join(Conversation, Conversation.id == Message.conversation_id).where(Message.role == 'user')
    rows = (session.exec(query.where(Message.delivery_status == 'pending')).all() +
            session.exec(query.where(Message.delivery_status != 'pending')
                         .order_by(Message.id.desc()).limit(limit)).all())
    items = [_item('chat', mid, title, status, when, 'chat?' + urlencode({'conversation': cid}))
             for mid, cid, title, status, when in rows]
    questions = session.exec(select(Message.id, Message.conversation_id, Conversation.title, Message.created_at)
        .join(Conversation, Conversation.id == Message.conversation_id)
        .where(Message.role == 'assistant', func.json_extract(Message.clarification_json, '$.status') == 'pending')).all()
    items.extend(_item('question', mid, title, 'awaiting_user', when, 'chat?' + urlencode({'conversation': cid}))
                 for mid, cid, title, when in questions)
    return items


def recent_work(session, limit=5):
    """One entry per work item in this session's project, including drafts.

    Group messages in SQL before limiting, so a long conversation cannot hide
    the other conversations. No transcripts, document bodies or model calls.
    """
    items = _task_items(session, limit, include_drafts=True)
    latest = (select(Message.conversation_id, func.max(Message.id).label('message_id'))
              .where(Message.role.in_(['user', 'assistant'])).group_by(Message.conversation_id).subquery())
    waiting = func.json_extract(Message.clarification_json, '$.status') == 'pending'
    query = (select(Conversation.id, Conversation.title, Conversation.updated_at, Message.created_at,
                    Message.delivery_status, waiting.label('waiting'))
             .join(latest, latest.c.conversation_id == Conversation.id)
             .join(Message, Message.id == latest.c.message_id))
    # Historical unanswered cards must not override a later turn.
    active = (Message.delivery_status == 'pending') | waiting
    rows = (session.exec(query.where(active)).all() +
            session.exec(query.where(func.coalesce(active, False) == False)
                         .order_by(func.max(Conversation.updated_at, Message.created_at).desc(), Conversation.id.desc())
                         .limit(limit)).all())
    for cid, title, updated, sent, status, awaiting in rows:
        items.append(_item('chat', cid, title, 'awaiting_user' if awaiting else status,
                           max(updated, sent), 'chat?' + urlencode({'conversation': cid})))

    # Wiki pages also have manual edits, without a background update record.
    latest_update = (select(WikiUpdate.id).where(WikiUpdate.page_id == WikiPage.id)
                     .order_by(WikiUpdate.updated_at.desc(), WikiUpdate.id).limit(1).correlate(WikiPage).scalar_subquery())
    query = (select(WikiPage.id, WikiPage.title, WikiPage.updated_at, WikiUpdate.status, WikiUpdate.updated_at)
             .outerjoin(WikiUpdate, WikiUpdate.id == latest_update).where(WikiPage.archived == False))
    rows = (session.exec(query.where(WikiUpdate.status.in_(['running', 'queued']))).all() +
            session.exec(query.where(func.coalesce(WikiUpdate.status, '').not_in(['running', 'queued']))
                         .order_by(func.max(WikiPage.updated_at, func.coalesce(WikiUpdate.updated_at, WikiPage.updated_at)).desc(), WikiPage.id)
                         .limit(limit)).all())
    for pid, title, updated, status, sent in rows:
        items.append(_item('wiki', pid, title, status or 'saved', max(updated, sent or updated),
                           'wiki?' + urlencode({'page': pid})))

    items.sort(key=lambda item: (item['active'] or item['status'] == 'awaiting_user', item['time'], item['key']), reverse=True)
    return {'items': items[:limit]}


def list_activity(registry):
    result = []; unavailable = []
    for workspace in registry.list():
        if not workspace['available']:
            unavailable.append({'id': workspace['id'], 'name': workspace['name']}); continue
        try:
            with bind_workspace(registry.context(workspace['id'])), Session(get_engine()) as session:
                for item in _task_items(session, 30) + _wiki_events(session, 30) + _chat_events(session, 30):
                    route = item.pop('route')
                    result.append({**item, 'key': workspace['id'] + ':' + item['key'],
                                   'workspace_id': workspace['id'], 'workspace_name': workspace['name'],
                                   'url': '?' + urlencode({'workspace': workspace['id']}) + '#' + route})
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Unable to read workspace activity: %s', workspace['id'])
            unavailable.append({'id': workspace['id'], 'name': workspace['name']})
    priority = sorted((r for r in result if r['active'] or r['status'] == 'awaiting_user'), key=lambda r: r['time'])
    recent = sorted((r for r in result if not r['active'] and r['status'] != 'awaiting_user'), key=lambda r: r['time'], reverse=True)[:60]
    return {'items': priority + recent, 'unavailable': unavailable}
