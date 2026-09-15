"""P14.1 weekly aggregation — deterministic counts from fixture data, zero LLM."""

from datetime import datetime, timedelta

from sqlmodel import Session

from app.db.engine import get_engine
from app.models import (
    Experiment,
    ExperimentLog,
    Idea,
    Paper,
    PaperExcerpt,
    PaperNote,
    PaperReadingState,
    Suggestion,
)
from app.reports.aggregation import parse_window, render_aggregate_text, weekly_aggregate

UNTIL = "2026-06-10"
INSIDE = datetime(2026, 6, 8, 12, 0, 0)  # within [2026-06-04, 2026-06-11)
OUTSIDE = datetime(2026, 5, 1, 12, 0, 0)  # before the window


def _seed(session: Session) -> None:
    inside_paper = Paper(source="manual", title="窗内论文A", created_at=INSIDE)
    outside_paper = Paper(source="manual", title="窗外论文B", created_at=OUTSIDE)
    session.add(inside_paper)
    session.add(outside_paper)
    session.commit()
    session.refresh(inside_paper)
    session.refresh(outside_paper)

    session.add(PaperReadingState(paper_id=inside_paper.id, status="read", finished_at=INSIDE))
    session.add(PaperReadingState(paper_id=outside_paper.id, status="unread"))  # never finished
    session.add(PaperNote(paper_id=inside_paper.id, content="窗内笔记", created_at=INSIDE))
    session.add(PaperNote(paper_id=inside_paper.id, content="窗外笔记", created_at=OUTSIDE))
    session.add(PaperExcerpt(paper_id=inside_paper.id, quote="窗内摘录", created_at=INSIDE))
    session.add(PaperExcerpt(paper_id=inside_paper.id, quote="窗外摘录", created_at=OUTSIDE))

    idea_new = Idea(title="窗内新建 Idea", status="testing", created_at=INSIDE, updated_at=INSIDE)
    idea_moved = Idea(
        title="窗内推进 Idea",
        status="refining",
        created_at=OUTSIDE,
        updated_at=INSIDE,
    )
    idea_closed = Idea(
        title="窗内完结 Idea",
        status="dropped",
        created_at=OUTSIDE,
        updated_at=INSIDE,
        closed_at=INSIDE,
    )
    idea_stale = Idea(title="窗外 Idea", status="proposed", created_at=OUTSIDE, updated_at=OUTSIDE)
    session.add(idea_new)
    session.add(idea_moved)
    session.add(idea_closed)
    session.add(idea_stale)

    from app.models import Project

    project = Project(name="聚合项目")
    session.add(project)
    session.commit()
    session.refresh(project)
    experiment_new = Experiment(
        name="窗内新建实验", project_id=project.id, status="running", created_at=INSIDE
    )
    experiment_finished = Experiment(
        name="窗内完结实验",
        project_id=project.id,
        status="done",
        created_at=OUTSIDE,
        finished_at=INSIDE,
    )
    experiment_deleted = Experiment(
        name="已软删实验",
        project_id=project.id,
        status="planned",
        created_at=INSIDE,
        is_deleted=True,
    )
    session.add(experiment_new)
    session.add(experiment_finished)
    session.add(experiment_deleted)
    session.commit()
    session.refresh(experiment_new)
    session.refresh(experiment_finished)

    session.add(ExperimentLog(experiment_id=experiment_new.id, content="窗内日志", created_at=INSIDE))
    session.add(
        ExperimentLog(experiment_id=experiment_new.id, content="窗外日志", created_at=OUTSIDE)
    )
    # Log under a soft-deleted experiment must not count.
    session.add(
        ExperimentLog(experiment_id=experiment_deleted.id, content="软删实验日志", created_at=INSIDE)
    )

    session.add(
        Suggestion(
            kind="radar",
            title="雷达高相关论文",
            detail_json='{"grade": "high"}',
            created_at=INSIDE,
        )
    )
    session.add(
        Suggestion(
            kind="radar",
            title="雷达低相关论文",
            detail_json='{"grade": "medium"}',
            created_at=INSIDE,
        )
    )
    session.add(
        Suggestion(kind="method_conflict", title="方法冲突", detail_json="{}", created_at=INSIDE)
    )
    session.add(Suggestion(kind="combination", title="结合点", detail_json="{}", created_at=OUTSIDE))
    session.commit()


def test_parse_window_defaults_and_validation():
    start, end, since_date, until_date = parse_window(None, UNTIL)
    assert (since_date.isoformat(), until_date.isoformat()) == ("2026-06-04", UNTIL)
    assert start == datetime(2026, 6, 4)
    assert end == datetime(2026, 6, 11)  # inclusive of the whole until day
    assert start < end

    # The entire until day counts: 23:59 on 06-10 is inside.
    from app.reports.aggregation import _in_window

    assert _in_window(datetime(2026, 6, 10, 23, 59), start, end)

    for bad in (("garbage", None), (None, "2026/06/10"), ("2026-06-10", "2026-06-01")):
        try:
            parse_window(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"expected ValueError for {bad}")


def test_weekly_aggregate_counts_window_rows_only(client):
    with Session(get_engine()) as session:
        _seed(session)
        data = weekly_aggregate(session, since="2026-06-04", until=UNTIL)

    assert data["since"] == "2026-06-04"
    assert data["until"] == UNTIL
    assert data["papers_new"]["count"] == 1
    assert data["papers_new"]["items"] == [{"id": data["papers_new"]["items"][0]["id"], "title": "窗内论文A"}]
    assert data["papers_read"]["count"] == 1
    assert data["notes_new"]["count"] == 1
    assert data["excerpts_new"]["count"] == 1

    ideas = data["ideas"]
    assert ideas["created"]["count"] == 1
    assert ideas["created"]["items"][0]["title"] == "窗内新建 Idea"
    assert ideas["updated"]["count"] == 3  # new + moved + closed all have updated_at inside
    assert ideas["updated"]["by_status"] == {"testing": 1, "refining": 1, "dropped": 1}
    assert ideas["closed"]["count"] == 1

    experiments = data["experiments"]
    assert experiments["created"]["count"] == 1
    assert experiments["created"]["items"][0]["name"] == "窗内新建实验"
    assert experiments["logs_added"]["count"] == 1  # soft-deleted experiment's log excluded
    assert experiments["finished"]["count"] == 1
    # Current status distribution counts all live experiments (created in and out of window).
    assert experiments["status_counts"] == {"running": 1, "done": 1}

    assert data["radar_high"]["count"] == 1
    assert data["radar_high"]["items"][0]["title"] == "雷达高相关论文"
    assert data["suggestions_ai"] == {"count": 1, "by_kind": {"method_conflict": 1}}


def test_weekly_aggregate_deterministic_and_default_window(client):
    with Session(get_engine()) as session:
        _seed(session)
        first = weekly_aggregate(session, since="2026-06-04", until=UNTIL)
        second = weekly_aggregate(session, since="2026-06-04", until=UNTIL)
    assert first == second  # pure function of DB state — no clock/LLM in the result body

    # Default window (until=today) simply must not blow up and must be parseable.
    with Session(get_engine()) as session:
        default = weekly_aggregate(session)
    assert default["until"] >= default["since"]


def test_render_aggregate_text_contains_problems_block(client):
    with Session(get_engine()) as session:
        _seed(session)
        data = weekly_aggregate(session, since="2026-06-04", until=UNTIL)
    text = render_aggregate_text(data, problems="基线复现失败，求助显存不足怎么办")
    assert "2026-06-04" in text and UNTIL in text
    assert "窗内论文A" in text
    assert "本周遇到的问题" in text
    assert "显存不足" in text

    plain = render_aggregate_text(data)
    assert "本周遇到的问题" not in plain


def test_weekly_aggregate_api_validation(client):
    assert client.get("/api/reports/weekly", params={"since": "junk"}).status_code == 422
    res = client.get("/api/reports/weekly", params={"since": UNTIL, "until": "2026-06-01"})
    assert res.status_code == 422
    assert "since" in res.json()["detail"]
    res = client.get("/api/reports/weekly")
    assert res.status_code == 200
    assert "papers_new" in res.json()
