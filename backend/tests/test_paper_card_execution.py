import json
import sys
from pathlib import Path
import pytest
import fitz
from sqlmodel import Session
from app.db.engine import get_engine
from app.models import Paper, PaperNote
from app.skills import paper_card
from app.agent.presentation import public_tool_result


def paper(session, tmp_path, text='Test source\nMethods\nWe compare model predictions with a known reference.\nNo automatic captions are provided in this small source.'):
    from app.config import get_settings
    path = get_settings().data_dir/'pdfs/source.pdf';path.parent.mkdir(exist_ok=True)
    with fitz.open() as document:
        page = document.new_page(); page.insert_text((72,72),text); document.save(path)
    row = Paper(source='pdf',title='Source',pdf_path=str(path))
    session.add(row);session.commit();session.refresh(row)
    return row


def test_original_scripts_execute_and_cache_exact_source(client, tmp_path, monkeypatch):
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        first=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        assert first['ok'] and not first['reused']
        assert first['execution']['script']=='scripts/prepare_paper.py'
        assert first['execution']['exit_code']==0 and first['page_count']==1
        assert first['validation']['warnings']
        monkeypatch.setattr(paper_card,'_execute',lambda *a:pytest.fail('unchanged source reran'))
        second=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        assert second['reused'] and first['run_id']==second['run_id']
        run=paper_card.run_directory(first['run_id'])
        bundle=json.loads((run/'source_bundle.json').read_text(encoding='utf-8'))
        assert bundle['source_sha256']==first['source_sha256']
        assert bundle['pages'][0]['pdf_page']==1
        response=client.get(first['artifacts'][0]['download_url'])
        assert response.status_code==200


def test_source_change_and_tampered_cached_artifact_require_new_run(client,tmp_path):
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        first=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        (paper_card.run_directory(first['run_id'])/'source_bundle.json').write_text('{}')
        second=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        assert first['run_id']!=second['run_id'] and second['ok']
        new=Path(row.pdf_path).parent/'replacement.pdf'
        with fitz.open() as document:
            document.new_page().insert_text((72,72),'A different source with enough readable text to exercise the original source preparation workflow.');document.save(new)
        row.pdf_path=new.name;session.add(row);session.commit()
        third=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        assert second['source_sha256']!=third['source_sha256']
        assert second['run_id']!=third['run_id']


def test_failed_audit_is_a_persisted_diagnostic_not_an_agent_error(client,tmp_path):
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        note=PaperNote(paper_id=row.id,content='An incomplete reading card')
        session.add(note);session.commit();session.refresh(note)
        result=json.loads(paper_card.audit_paper_card(session,row.id,note_id=note.id))
        assert result['ok'] is True and result['audit_pass'] is False
        assert result['execution']['exit_code']==1
        assert result['summary']['errors']>0
        assert result['source_validation']['warnings']
        assert session.get(PaperNote,note.id).content=='An incomplete reading card'
        assert paper_card.artifact_path(result['run_id'],'paper-card.md').read_text()=='An incomplete reading card'
        note.content='Researcher edited later';session.add(note);session.commit()
        assert paper_card.artifact_path(result['run_id'],'paper-card.md').read_text()=='An incomplete reading card'
        receipt=json.loads(public_tool_result('audit_paper_card',json.dumps(result)))
        assert receipt['summary']['errors'] and receipt['run_id']==result['run_id']
        assert 'stderr' not in receipt['execution']
        response=client.get(receipt['receipt_url']);assert response.status_code==200
        assert response.json()['input']['note_id']==note.id


def test_valid_card_pass_does_not_hide_missing_automatic_inventory(client,tmp_path):
    card='\n'.join(['> Source: PDF', '> Extraction: mixed','> Locator mode: page-grounded',
        '> Primary: methods','> Secondary: none','> Context: paper-only','> Completeness: partial'])
    card+='\n\n'+'\n\n'.join(f'## {n:02d} Section\n[Paper: PDF p. 1, Methods]' for n in range(1,17))
    card+='\ninnovation status: unverified\nvalidation: test\nfailure mode: uncertain'
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        result=json.loads(paper_card.audit_paper_card(session,row.id,content=card))
        assert result['audit_pass'] and result['summary']['errors']==0
        assert result['inventory_counts']['figures']==0
        assert result['source_validation']['warnings']
        assert '不证明科学结论正确' in result['summary_md']
        pieces=[];start=0
        while True:
            part=json.loads(paper_card.read_skill_run(session,result['run_id'],'paper-card.md',start,97))
            pieces.append(part['text']);start=part['next_start_char']
            if start is None:break
        assert ''.join(pieces)==card


def test_exact_input_selection_and_workspace_boundary(client,tmp_path,monkeypatch):
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        other=Paper(source='manual',title='Other');session.add(other);session.commit();session.refresh(other)
        note=PaperNote(paper_id=other.id,content='wrong paper');session.add(note);session.commit();session.refresh(note)
        with pytest.raises(LookupError):paper_card.audit_paper_card(session,row.id,note_id=note.id)
        with pytest.raises(ValueError):paper_card.audit_paper_card(session,row.id,note_id=note.id,content='ambiguous')
        run=json.loads(paper_card.prepare_paper_card_sources(session,row.id))
        with pytest.raises(LookupError):paper_card.artifact_path(run['run_id'],'../job.json')
        monkeypatch.setenv('PAPERMIND_DATA_DIR',str(tmp_path/'other-workspace'))
        with pytest.raises(LookupError):paper_card.read_skill_run(session,run['run_id'])


def test_runner_failure_is_reported_without_fake_audit(client,tmp_path,monkeypatch):
    def failed(*args):return {'exit_code':-1,'duration_ms':1,'stdout':'','stderr':'timed out','process_error':'timed out'}
    monkeypatch.setattr(paper_card,'run_bundled_script',failed)
    with Session(get_engine()) as session:
        row=paper(session,tmp_path)
        result=json.loads(paper_card.audit_paper_card(session,row.id,content='draft'))
        assert not result['ok'] and result['audit_not_run']
        assert 'audit_pass' not in result
        assert 'timed out' in result['summary_md']


def test_worker_preserves_original_filename_and_restores_argv(tmp_path):
    from app.skills.worker import run_script
    script=tmp_path/'original.py';out=tmp_path/'outputs';out.mkdir()
    script.write_text('import sys\nprint(__file__)\nprint(sys.argv)\nraise SystemExit(3)',encoding='utf-8')
    previous=sys.argv
    assert run_script(str(script),['--option','值'],str(out))==3
    assert sys.argv is previous
    assert str(script) in (out/'stdout.txt').read_text(encoding='utf-8')
    assert not (tmp_path/'stdout.txt').exists()


def test_script_timeout_returns_a_diagnostic_and_next_execution_works(tmp_path):
    from app.skills.script_runner import run_bundled_script
    script = tmp_path/'slow.py'
    script.write_text('import time\ntime.sleep(30)', encoding='utf-8')
    result = run_bundled_script(script, [], tmp_path/'slow-run', timeout=0.3)
    assert result['exit_code'] == -1 and result['process_error']
    script = tmp_path/'next.py'
    script.write_text('print("next execution works")', encoding='utf-8')
    result = run_bundled_script(script, [], tmp_path/'next-run')
    assert result['exit_code'] == 0 and result['process_error'] is None
    assert 'next execution works' in result['stdout']


def test_frozen_dispatch_uses_original_job_without_opening_desktop(tmp_path,monkeypatch):
    from app import launcher
    script=tmp_path/'original.py';script.write_text('print("original job")')
    job=tmp_path/'job.json';job.write_text(json.dumps({'script':str(script),'args':[]}))
    monkeypatch.setattr(sys,'argv',['PaperMind.exe','--run-bundled-skill',str(job)])
    with pytest.raises(SystemExit) as result:launcher.main()
    assert result.value.code==0 and 'original job' in (tmp_path/'stdout.txt').read_text()
