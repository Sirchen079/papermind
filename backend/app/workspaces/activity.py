"""Small application-level activity directory; research content stays scoped."""
from urllib.parse import urlencode
from sqlmodel import Session, select
from sqlalchemy import func
from app.db.engine import get_engine
from app.models import ResearchTask, Message, Conversation, WikiUpdate, WikiPage
from app.workspaces.context import bind_workspace


def list_activity(registry):
    result=[]; unavailable=[]
    for workspace in registry.list():
        if not workspace['available']:
            unavailable.append({'id':workspace['id'],'name':workspace['name']});continue
        try:
            with bind_workspace(registry.context(workspace['id'])), Session(get_engine()) as session:
                rows=[]
                # Projected fields avoid loading PDF text, chat histories or model inputs.
                task_query=select(ResearchTask.id,ResearchTask.question,ResearchTask.status,ResearchTask.updated_at)
                tasks=(session.exec(task_query.where(ResearchTask.status=='running')).all()+
                       session.exec(task_query.where(ResearchTask.status.not_in(['draft','running'])).order_by(ResearchTask.updated_at.desc()).limit(30)).all())
                for tid,title,status,when in tasks:
                    rows.append(('research',tid,title,status,str(when),'research?'+urlencode({'task':tid})))
                update_query=select(WikiUpdate.id,WikiPage.id,WikiPage.title,WikiUpdate.status,WikiUpdate.updated_at).join(WikiPage,WikiPage.id==WikiUpdate.page_id)
                updates=(session.exec(update_query.where(WikiUpdate.status.in_(['queued','running']))).all()+
                         session.exec(update_query.where(WikiUpdate.status.not_in(['queued','running'])).order_by(WikiUpdate.updated_at.desc()).limit(30)).all())
                for uid,pid,title,status,when in updates:
                    rows.append(('wiki',uid,title,status,str(when),'wiki?'+urlencode({'page':pid})))
                turn_query=select(Message.id,Message.conversation_id,Conversation.title,Message.delivery_status,Message.created_at).join(Conversation,Conversation.id==Message.conversation_id).where(Message.role=='user')
                turns=(session.exec(turn_query.where(Message.delivery_status=='pending')).all()+
                       session.exec(turn_query.where(Message.delivery_status!='pending').order_by(Message.id.desc()).limit(30)).all())
                for mid,cid,title,status,when in turns:
                    rows.append(('chat',str(mid),title or '论文问答',status,str(when),'chat?'+urlencode({'conversation':cid})))
                questions=session.exec(select(Message.id,Message.conversation_id,Conversation.title,Message.created_at)
                    .join(Conversation,Conversation.id==Message.conversation_id)
                    .where(Message.role=='assistant',func.json_extract(Message.clarification_json,'$.status')=='pending')).all()
                for mid,cid,title,when in questions:
                    rows.append(('question',str(mid),title or '论文问答','awaiting_user',str(when),'chat?'+urlencode({'conversation':cid})))
                for kind,rid,title,status,when,route in rows:
                    result.append({'key':workspace['id']+':'+kind+':'+rid,'workspace_id':workspace['id'],
                                   'workspace_name':workspace['name'],'kind':kind,'title':title[:300],
                                   'status':status,'stamp':when+':'+status,'time':when,
                                   'active':status in ('running','queued','pending'),
                                   'url':'?'+urlencode({'workspace':workspace['id']})+'#'+route})
        except Exception:
            import logging
            logging.getLogger(__name__).exception('Unable to read workspace activity: %s',workspace['id'])
            unavailable.append({'id':workspace['id'],'name':workspace['name']})
    priority=sorted((r for r in result if r['active'] or r['status']=='awaiting_user'),key=lambda r:r['time'])
    recent=sorted((r for r in result if not r['active'] and r['status']!='awaiting_user'),key=lambda r:r['time'],reverse=True)[:60]
    return {'items':priority+recent,'unavailable':unavailable}
