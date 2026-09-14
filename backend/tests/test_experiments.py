"""P13 experiment records: CRUD, state machine, append-only logs, hiding rules."""

from sqlmodel import Session, select

from app.db.engine import get_engine
from app.models import Experiment, ExperimentLog, ExperimentPaperLink, Idea, Paper, Project


def _paper(session: Session, title: str) -> Paper:
    paper = Paper(source="manual", title=title)
    session.add(paper)
    session.commit()
    session.refresh(paper)
    return paper


def _project(client, name: str = "课题A") -> dict:
    res = client.post("/api/thesis/projects", json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()


def _create_experiment(client, **overrides) -> dict:
    project_id = overrides.pop("project_id", None) or _project(client)["id"]
    payload = {"name": "级联缓存消融实验", "project_id": project_id, **overrides}
    res = client.post("/api/experiments", json=payload)
    assert res.status_code == 201, res.text
    return res.json()


def test_experiment_crud_and_soft_delete(client):
    created = _create_experiment(client, hypothesis="两级缓存能把延迟降 30%", status="planned")
    assert created["status"] == "planned"
    assert created["hypothesis"].startswith("两级缓存")
    assert created["log_count"] == 0

    listed = client.get("/api/experiments").json()
    assert [e["id"] for e in listed] == [created["id"]]

    patched = client.patch(
        f"/api/experiments/{created['id']}", json={"hypothesis": "# 假设\n缓存命中率是关键。"}
    ).json()
    assert patched["hypothesis"].startswith("# 假设")

    # name 校验：空名 422；不存在的项目 404；非法枚举 422（合法枚举创建时均允许，便于补录历史实验）。
    assert client.post("/api/experiments", json={"name": "  ", "project_id": created["project_id"]}).status_code == 422
    assert client.post("/api/experiments", json={"name": "x", "project_id": 99999}).status_code == 404
    assert client.post(
        "/api/experiments", json={"name": "x", "project_id": created["project_id"], "status": "bogus"}
    ).status_code == 422

    # 软删：行保留、视图隐藏。
    assert client.delete(f"/api/experiments/{created['id']}").status_code == 204
    assert client.get("/api/experiments").json() == []
    assert client.get(f"/api/experiments/{created['id']}").status_code == 404
    with Session(get_engine()) as session:
        row = session.get(Experiment, created["id"])
        assert row.is_deleted is True


def test_experiment_state_machine_allows_chain_rejects_jumps_with_400(client):
    experiment = _create_experiment(client)

    # 合法链：planned → running → analyzing → done；started/finished 自动写入。
    for status in ("running", "analyzing", "done"):
        res = client.patch(f"/api/experiments/{experiment['id']}", json={"status": status})
        assert res.status_code == 200, res.text
        assert res.json()["status"] == status
    final = res.json()
    assert final["started_at"] is not None
    assert final["finished_at"] is not None

    # 非法跳转 → 结构化 400，detail 指出允许的目标。
    fresh = _create_experiment(client, name="第二个实验")
    res = client.patch(f"/api/experiments/{fresh['id']}", json={"status": "done"})
    assert res.status_code == 400
    assert "running" in res.json()["detail"]

    res = client.patch(f"/api/experiments/{fresh['id']}", json={"status": "analyzing"})
    assert res.status_code == 400

    # analyzing → abandoned 合法（另一条终点）。
    third = _create_experiment(client, name="第三个实验")
    for status in ("running", "analyzing", "abandoned"):
        assert (
            client.patch(f"/api/experiments/{third['id']}", json={"status": status}).status_code == 200
        )

    # 终点后无出边。
    assert (
        client.patch(f"/api/experiments/{third['id']}", json={"status": "running"}).status_code == 400
    )
    # 非法枚举 422。
    assert (
        client.patch(f"/api/experiments/{fresh['id']}", json={"status": "bogus"}).status_code == 422
    )


def test_experiment_project_required_and_delete_block(client):
    project = _project(client)
    experiment = _create_experiment(client, project_id=project["id"])

    # 项目删除被实验阻塞（与 chapters/links 同模式），实验永不悬空。
    res = client.delete(f"/api/thesis/projects/{project['id']}")
    assert res.status_code == 422
    assert "experiment" in res.json()["detail"]

    # 删除实验后项目可删。
    assert client.delete(f"/api/experiments/{experiment['id']}").status_code == 204
    assert client.delete(f"/api/thesis/projects/{project['id']}").status_code == 204


def test_experiment_idea_link_and_hide_on_idea_soft_delete(client):
    project = _project(client)
    idea_res = client.post("/api/ideas", json={"title": "用缓存加速检索"})
    assert idea_res.status_code == 201
    idea_id = idea_res.json()["id"]

    experiment = _create_experiment(client, project_id=project["id"], idea_id=idea_id)
    assert experiment["idea_id"] == idea_id

    # 挂不存在的 idea → 404。
    assert (
        client.post(
            "/api/experiments", json={"name": "x", "project_id": project["id"], "idea_id": 99999}
        ).status_code == 404
    )

    # idea 软删后：实验行保留，默认视图隐藏，include_hidden 可见。
    assert client.delete(f"/api/ideas/{idea_id}").status_code == 204
    assert client.get("/api/experiments").json() == []
    hidden = client.get("/api/experiments", params={"include_hidden": "true"}).json()
    assert [e["id"] for e in hidden] == [experiment["id"]]
    # 单个获取仍可达（数据未丢）。
    assert client.get(f"/api/experiments/{experiment['id']}").json()["id"] == experiment["id"]
    # 过滤参数仍能定位到该实验。
    assert (
        client.get("/api/experiments", params={"project_id": str(project["id"])}).json() == []
    )
    assert len(
        client.get(
            "/api/experiments", params={"idea_id": str(idea_id), "include_hidden": "true"}
        ).json()
    ) == 1


def test_experiment_logs_append_only_and_deletable(client):
    experiment = _create_experiment(client)

    first = client.post(
        f"/api/experiments/{experiment['id']}/logs", json={"content": "跑通基线，acc=71.2"}
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/experiments/{experiment['id']}/logs", json={"content": "加入两级缓存，acc=74.8"}
    ).json()
    # 追加为空内容 → 422。
    assert (
        client.post(f"/api/experiments/{experiment['id']}/logs", json={"content": "   "}).status_code
        == 422
    )

    logs = client.get(f"/api/experiments/{experiment['id']}/logs").json()
    assert [log["id"] for log in logs] == [first.json()["id"], second["id"]]  # 时间线正序
    assert logs[0]["content"].startswith("跑通基线")

    # 追加式：没有 PATCH/PUT 编辑路由（405），只有删除。
    assert (
        client.patch(
            f"/api/experiments/{experiment['id']}/logs/{first.json()['id']}", json={"content": "篡改"}
        ).status_code
        == 405
    )
    assert (
        client.delete(
            f"/api/experiments/{experiment['id']}/logs/{first.json()['id']}"
        ).status_code
        == 204
    )
    logs = client.get(f"/api/experiments/{experiment['id']}/logs").json()
    assert [log["id"] for log in logs] == [second["id"]]

    # 未知日志/未知实验 → 404。
    assert (
        client.delete(f"/api/experiments/{experiment['id']}/logs/99999").status_code == 404
    )
    assert client.get("/api/experiments/99999/logs").status_code == 404

    with Session(get_engine()) as session:
        assert session.get(ExperimentLog, first.json()["id"]) is None


def test_experiment_paper_links_multi_role_idempotent(client):
    with Session(get_engine()) as session:
        paper = _paper(session, "Baseline Transformer")

    experiment = _create_experiment(
        client, papers=[{"paper_id": paper.id, "role": "baseline"}]
    )
    assert experiment["papers"] == [
        {"paper_id": paper.id, "title": "Baseline Transformer", "role": "baseline", "note": None}
    ]

    # 同论文另一角色允许；同 (paper, role) 重复 → 幂等。
    assert (
        client.post(
            f"/api/experiments/{experiment['id']}/papers",
            json={"paper_id": paper.id, "role": "method"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/experiments/{experiment['id']}/papers",
            json={"paper_id": paper.id, "role": "method"},
        ).status_code
        == 201
    )
    with Session(get_engine()) as session:
        rows = session.exec(
            select(ExperimentPaperLink).where(
                ExperimentPaperLink.experiment_id == experiment["id"]
            )
        ).all()
        assert len(rows) == 2

    # 非法角色 422、缺失论文 404。
    assert (
        client.post(
            f"/api/experiments/{experiment['id']}/papers",
            json={"paper_id": paper.id, "role": "golden"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/experiments/{experiment['id']}/papers",
            json={"paper_id": 99999, "role": "dataset"},
        ).status_code
        == 404
    )

    # 解除一个角色，另一个保留。
    assert (
        client.delete(
            f"/api/experiments/{experiment['id']}/papers/{paper.id}/baseline"
        ).status_code
        == 204
    )
    detail = client.get(f"/api/experiments/{experiment['id']}").json()
    assert [p["role"] for p in detail["papers"]] == ["method"]


def test_experiment_filters_by_status_and_project(client):
    p1 = _project(client, "项目一")
    p2 = _project(client, "项目二")
    e1 = _create_experiment(client, project_id=p1["id"], name="A")
    e2 = _create_experiment(client, project_id=p2["id"], name="B")
    client.patch(f"/api/experiments/{e2['id']}", json={"status": "running"})

    assert [e["id"] for e in client.get("/api/experiments", params={"status": "planned"}).json()] == [e1["id"]]
    assert [e["id"] for e in client.get("/api/experiments", params={"project_id": str(p2["id"])}).json()] == [e2["id"]]
    assert len(client.get("/api/experiments").json()) == 2
    assert client.get("/api/experiments", params={"status": "weird"}).status_code == 422


def test_export_json_includes_experiments_logs_and_links(client):
    """P13.4 归档导出：实验/日志/论文关联进 JSON 导出，软删实验不出现。"""
    from app.archive.service import export_json

    project = _project(client)
    with Session(get_engine()) as session:
        paper = _paper(session, "Baseline ResNet")

    experiment = _create_experiment(
        client,
        project_id=project["id"],
        name="被导出的实验",
        papers=[{"paper_id": paper.id, "role": "baseline"}],
    )
    client.post(f"/api/experiments/{experiment['id']}/logs", json={"content": "第一天：跑基线"})

    deleted = _create_experiment(client, project_id=project["id"], name="被软删的实验")
    assert client.delete(f"/api/experiments/{deleted['id']}").status_code == 204

    with Session(get_engine()) as session:
        exported = export_json(session)

    assert [e["name"] for e in exported["experiments"]] == ["被导出的实验"]
    assert len(exported["experiment_logs"]) == 1
    assert exported["experiment_logs"][0]["content"] == "第一天：跑基线"
    links = exported["experiment_paper_links"]
    assert len(links) == 1
    assert (links[0]["experiment_id"], links[0]["paper_id"], links[0]["role"]) == (
        experiment["id"],
        paper.id,
        "baseline",
    )


def test_acceptance_experiment_lifecycle_end_to_end(client):
    """P13 验收演示（代码级）：项目下建实验 → 挂 baseline 论文 → 追加 3 条日志
    → 流转到 done；idea 软删后实验保留但列表隐藏。"""
    project = _project(client)
    with Session(get_engine()) as session:
        paper = _paper(session, "Baseline ViT")

    experiment = _create_experiment(
        client,
        project_id=project["id"],
        name="Patch 大小消融",
        hypothesis="patch=4 优于 patch=16",
        papers=[{"paper_id": paper.id, "role": "baseline"}],
    )
    for content in ("初始化环境", "跑通 patch=16 基线", "patch=4 训练中"):
        assert (
            client.post(
                f"/api/experiments/{experiment['id']}/logs", json={"content": content}
            ).status_code
            == 201
        )
    for status in ("running", "analyzing", "done"):
        assert (
            client.patch(f"/api/experiments/{experiment['id']}", json={"status": status}).status_code
            == 200
        )

    final = client.get(f"/api/experiments/{experiment['id']}").json()
    assert final["status"] == "done"
    assert final["started_at"] is not None
    assert final["finished_at"] is not None
    assert final["log_count"] == 3
    assert final["papers"][0]["role"] == "baseline"

    # 非法跳转保持结构化 400。
    assert (
        client.patch(f"/api/experiments/{experiment['id']}", json={"status": "running"}).status_code
        == 400
    )

    # 挂到 idea 再软删 idea：实验行保留、默认列表隐藏。
    idea_id = client.post("/api/ideas", json={"title": "小 patch 更好"}).json()["id"]
    client.patch(f"/api/experiments/{experiment['id']}", json={"idea_id": idea_id})
    assert client.delete(f"/api/ideas/{idea_id}").status_code == 204
    assert client.get("/api/experiments").json() == []
    assert len(client.get("/api/experiments", params={"include_hidden": "true"}).json()) == 1
