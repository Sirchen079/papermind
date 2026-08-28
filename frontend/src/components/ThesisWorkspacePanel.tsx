import { useEffect, useMemo, useState } from "react";
import { useToast } from "./ui/Toast";
import { useConfirm } from "./ui/ConfirmDialog";
import { api, Paper, ThesisChapter, ThesisProject, ThesisWorkspace } from "../api";
import {
  buildThesisMarkdownExportTarget,
  chapterDeleteBlockReason,
  collectLinkedThesisTargetIds,
  projectDeleteBlockReason,
  type ThesisMarkdownExportScope,
} from "../pages/thesisWorkspaceModel";

type TargetType = "project" | "chapter";

const PROJECT_KIND_LABELS: Record<string, string> = {
  direction: "方向",
  topic: "主题",
  experiment: "实验",
  writing: "写作",
  other: "其他",
};

const PROJECT_STATUS_LABELS: Record<string, string> = {
  active: "进行中",
  paused: "暂停",
  done: "完成",
  archived: "已归档",
};

const CHAPTER_STATUS_LABELS: Record<string, string> = {
  draft: "草稿",
  in_progress: "进行中",
  review: "待审",
  done: "完成",
};

const LINK_ROLE_LABELS: Record<string, string> = {
  background: "背景",
  method: "方法",
  comparison: "对比",
  evidence: "证据",
  limitation: "局限",
  inspiration: "启发",
  related: "相关",
  to_read: "待读",
};

const TARGET_TYPE_LABELS: Record<TargetType, string> = {
  project: "项目",
  chapter: "章节",
};

interface Props {
  papers: Paper[];
  workspace: ThesisWorkspace | null;
  loading: boolean;
  onRefresh: () => Promise<void>;
  onOpenPaper: (paperId: number) => void;
}

function paperLabel(paper: { title: string | null; year: number | null; authors: string[] }) {
  return `${paper.title ?? "无标题"}${paper.year ? ` · ${paper.year}` : ""}`;
}

function labelFor(map: Record<string, string>, value: string | null | undefined) {
  if (!value) return "";
  return map[value] ?? value;
}

function findProject(projects: ThesisProject[], id: number): ThesisProject | null {
  for (const project of projects) {
    if (project.id === id) return project;
    const nested = findProject(project.children, id);
    if (nested) return nested;
  }
  return null;
}

function findChapter(chapters: ThesisChapter[], id: number): ThesisChapter | null {
  for (const chapter of chapters) {
    if (chapter.id === id) return chapter;
    const nested = findChapter(chapter.children, id);
    if (nested) return nested;
  }
  return null;
}

function treeIndex(workspace: ThesisWorkspace | null) {
  const projectLabels = new Map<number, string>();
  const chapterLabels = new Map<number, string>();
  const projectOptions: { id: number; label: string }[] = [];
  const chapterOptionsByProject = new Map<number, { id: number; label: string }[]>();
  const projectDescendants = new Map<number, Set<number>>();
  const chapterDescendants = new Map<number, Set<number>>();

  function walkChapters(projectId: number, chapters: ThesisChapter[], prefix: string[]) {
    const options: { id: number; label: string }[] = [];
    const visit = (list: ThesisChapter[], path: string[]): Set<number> => {
      const ids = new Set<number>();
      for (const chapter of list) {
        const nextPath = [...path, chapter.title];
        const descendants = visit(chapter.children, nextPath);
        chapterLabels.set(chapter.id, nextPath.join(" / "));
        options.push({ id: chapter.id, label: nextPath.join(" / ") });
        chapterDescendants.set(chapter.id, descendants);
        ids.add(chapter.id);
        descendants.forEach((id) => ids.add(id));
      }
      return ids;
    };
    visit(chapters, prefix);
    chapterOptionsByProject.set(projectId, options);
  }

  function walkProjects(projects: ThesisProject[], prefix: string[]): Set<number> {
    const ids = new Set<number>();
    for (const project of projects) {
      const nextPath = [...prefix, project.name];
      const childIds = walkProjects(project.children, nextPath);
      projectLabels.set(project.id, nextPath.join(" / "));
      projectOptions.push({ id: project.id, label: nextPath.join(" / ") });
      walkChapters(project.id, project.chapters, nextPath);
      projectDescendants.set(project.id, childIds);
      ids.add(project.id);
      childIds.forEach((id) => ids.add(id));
    }
    return ids;
  }

  walkProjects(workspace?.projects ?? [], []);
  return { projectLabels, chapterLabels, projectOptions, chapterOptionsByProject, projectDescendants, chapterDescendants };
}

function ProjectTreeNode({
  project,
  selectedProjectId,
  selectedChapterId,
  onSelectProject,
  onSelectChapter,
}: {
  project: ThesisProject;
  selectedProjectId: number | null;
  selectedChapterId: number | null;
  onSelectProject: (projectId: number) => void;
  onSelectChapter: (projectId: number, chapterId: number) => void;
}) {
  const active = selectedProjectId === project.id;
  return (
    <div className={`space-y-2 ${project.status === "archived" ? "opacity-60" : ""}`}>
      <button
        type="button"
        onClick={() => onSelectProject(project.id)}
        className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left"
        style={
          active
            ? { borderColor: "var(--accent)", backgroundColor: "var(--accent-soft)" }
            : { borderColor: "var(--border)", backgroundColor: "var(--surface)" }
        }
      >
        <span className="flex-1 min-w-0">
          <span className="block truncate font-medium">{project.name}</span>
          <span className="block text-[11px] text-faint">
            {labelFor(PROJECT_KIND_LABELS, project.kind)} · {labelFor(PROJECT_STATUS_LABELS, project.status)}
          </span>
        </span>
        <span className="chip">{project.chapters.length} 章</span>
      </button>

      <div className="ml-4 space-y-1 border-l pl-3 border-[var(--border)]">
        {project.chapters.map((chapter) => (
          <ChapterTreeNode
            key={chapter.id}
            projectId={project.id}
            chapter={chapter}
            selectedProjectId={selectedProjectId}
            selectedChapterId={selectedChapterId}
            onSelectChapter={onSelectChapter}
          />
        ))}
        {project.children.map((child) => (
          <ProjectTreeNode
            key={child.id}
            project={child}
            selectedProjectId={selectedProjectId}
            selectedChapterId={selectedChapterId}
            onSelectProject={onSelectProject}
            onSelectChapter={onSelectChapter}
          />
        ))}
      </div>
    </div>
  );
}

function ChapterTreeNode({
  projectId,
  chapter,
  selectedProjectId,
  selectedChapterId,
  onSelectChapter,
}: {
  projectId: number;
  chapter: ThesisChapter;
  selectedProjectId: number | null;
  selectedChapterId: number | null;
  onSelectChapter: (projectId: number, chapterId: number) => void;
}) {
  const active = selectedProjectId === projectId && selectedChapterId === chapter.id;
  return (
    <div className={`space-y-1 ${chapter.status === "done" ? "opacity-75" : ""}`}>
      <button
        type="button"
        onClick={() => onSelectChapter(projectId, chapter.id)}
        className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left"
        style={
          active
            ? { borderColor: "var(--accent)", backgroundColor: "var(--accent-soft)" }
            : { borderColor: "var(--border)", backgroundColor: "var(--surface)" }
        }
      >
        <span className="flex-1 min-w-0">
          <span className="block truncate text-sm font-medium">{chapter.title}</span>
          <span className="block text-[11px] text-faint">
            {labelFor(CHAPTER_STATUS_LABELS, chapter.status)}
          </span>
        </span>
        <span className="chip">章节</span>
      </button>
      <div className="ml-4 space-y-1 border-l pl-3 border-[var(--border)]">
        {chapter.children.map((child) => (
          <ChapterTreeNode
            key={child.id}
            projectId={projectId}
            chapter={child}
            selectedProjectId={selectedProjectId}
            selectedChapterId={selectedChapterId}
            onSelectChapter={onSelectChapter}
          />
        ))}
      </div>
    </div>
  );
}

export default function ThesisWorkspacePanel({ papers, workspace, loading, onRefresh, onOpenPaper }: Props) {
  const data = workspace ?? { projects: [], papers: [] };
  const indexes = useMemo(() => treeIndex(workspace), [workspace]);
  const linkedTargetIds = useMemo(() => collectLinkedThesisTargetIds(data.papers), [data.papers]);
  const [busy, setBusy] = useState<string | null>(null);
  const toast = useToast();
  const confirm = useConfirm();
  const [selectedProjectId, setSelectedProjectId] = useState<number | null>(null);
  const [selectedChapterId, setSelectedChapterId] = useState<number | null>(null);
  const [paperQuery, setPaperQuery] = useState("");
  const [projectForm, setProjectForm] = useState({
    name: "",
    kind: "topic",
    description: "",
    status: "active",
    parent_project_id: "",
  });
  const [chapterForm, setChapterForm] = useState({
    project_id: "",
    title: "",
    outline: "",
    status: "draft",
    parent_chapter_id: "",
  });
  const [linkForm, setLinkForm] = useState({
    paper_id: "",
    target_type: "project" as TargetType,
    project_id: "",
    chapter_id: "",
    role: "related",
    note: "",
  });
  const [projectEdit, setProjectEdit] = useState({
    name: "",
    kind: "topic",
    description: "",
    status: "active",
    parent_project_id: "",
    sort_order: "0",
  });
  const [chapterEdit, setChapterEdit] = useState({
    title: "",
    outline: "",
    status: "draft",
    parent_chapter_id: "",
    sort_order: "0",
  });
  const [linkDrafts, setLinkDrafts] = useState<Record<number, { role: string; note: string }>>({});

  useEffect(() => {
    const next: Record<number, { role: string; note: string }> = {};
    data.papers.forEach((paper) => {
      paper.links.forEach((link) => {
        next[link.id] = { role: link.role, note: link.note ?? "" };
      });
    });
    setLinkDrafts(next);
  }, [data.papers]);

  useEffect(() => {
    if (data.projects.length === 0) {
      setSelectedProjectId(null);
      setSelectedChapterId(null);
      return;
    }
    if (selectedProjectId != null && indexes.projectLabels.has(selectedProjectId)) return;
    setSelectedProjectId(data.projects[0].id);
    setSelectedChapterId(null);
  }, [data.projects, indexes.projectLabels, selectedProjectId]);

  useEffect(() => {
    if (selectedProjectId == null) return;
    if (!chapterForm.project_id) setChapterForm((prev) => ({ ...prev, project_id: String(selectedProjectId) }));
    if (!linkForm.project_id) setLinkForm((prev) => ({ ...prev, project_id: String(selectedProjectId) }));
  }, [selectedProjectId, chapterForm.project_id, linkForm.project_id]);

  useEffect(() => {
    if (data.papers.length === 0) return;
    if (!linkForm.paper_id) setLinkForm((prev) => ({ ...prev, paper_id: String(data.papers[0].id) }));
  }, [data.papers, linkForm.paper_id]);

  const selectedProject = selectedProjectId != null ? findProject(data.projects, selectedProjectId) : null;
  const selectedChapter = selectedProject && selectedChapterId != null ? findChapter(selectedProject.chapters, selectedChapterId) : null;
  const projectDeleteReason = selectedProject ? projectDeleteBlockReason(selectedProject, linkedTargetIds.projectIds) : null;
  const chapterDeleteReason = selectedChapter ? chapterDeleteBlockReason(selectedChapter, linkedTargetIds.chapterIds) : null;
  const chapterOptions = linkForm.project_id ? indexes.chapterOptionsByProject.get(Number(linkForm.project_id)) ?? [] : [];
  const validProjectParentOptions = selectedProject
    ? indexes.projectOptions.filter((option) => option.id !== selectedProject.id && !(indexes.projectDescendants.get(selectedProject.id)?.has(option.id)))
    : indexes.projectOptions;
  const validChapterParentOptions =
    selectedProject && selectedChapter
      ? (indexes.chapterOptionsByProject.get(selectedProject.id) ?? []).filter(
          (option) => option.id !== selectedChapter.id && !(indexes.chapterDescendants.get(selectedChapter.id)?.has(option.id)),
        )
      : selectedProject
        ? indexes.chapterOptionsByProject.get(selectedProject.id) ?? []
        : [];
  const selectedPaper = linkForm.paper_id ? data.papers.find((paper) => paper.id === Number(linkForm.paper_id)) ?? null : null;
  const filteredPapers = useMemo(() => {
    const q = paperQuery.trim().toLowerCase();
    if (!q) return papers;
    return papers.filter((paper) => {
      const hay = `${paper.title ?? ""} ${paper.authors.join(" ")} ${paper.year ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [papers, paperQuery]);
  const projectExportTarget = buildThesisMarkdownExportTarget("project", selectedProjectId, selectedChapterId);
  const chapterExportTarget = buildThesisMarkdownExportTarget("chapter", selectedProjectId, selectedChapterId);

  useEffect(() => {
    if (!selectedProject) return;
    setProjectEdit({
      name: selectedProject.name,
      kind: selectedProject.kind,
      description: selectedProject.description ?? "",
      status: selectedProject.status,
      parent_project_id: selectedProject.parent_project_id == null ? "" : String(selectedProject.parent_project_id),
      sort_order: String(selectedProject.sort_order),
    });
  }, [selectedProject?.id, selectedProject?.updated_at]);

  useEffect(() => {
    if (!selectedChapter) return;
    setChapterEdit({
      title: selectedChapter.title,
      outline: selectedChapter.outline ?? "",
      status: selectedChapter.status,
      parent_chapter_id: selectedChapter.parent_chapter_id == null ? "" : String(selectedChapter.parent_chapter_id),
      sort_order: String(selectedChapter.sort_order),
    });
  }, [selectedChapter?.id, selectedChapter?.updated_at]);

  async function run(action: string, fn: () => Promise<void>) {
    if (busy) return;
    setBusy(action);
    try {
      await fn();
      await onRefresh();
    } catch (err: any) {
      toast.error(err.message);
    } finally {
      setBusy(null);
    }
  }

  async function createProject() {
    if (!projectForm.name.trim()) return;
    await run("create-project", async () => {
      const body: Record<string, unknown> = {
        name: projectForm.name.trim(),
        kind: projectForm.kind,
        status: projectForm.status,
      };
      if (projectForm.description.trim()) body.description = projectForm.description.trim();
      if (projectForm.parent_project_id) body.parent_project_id = Number(projectForm.parent_project_id);
      const created = await api.createThesisProject(body);
      toast.success(`已创建项目：${created.name}`);
      setProjectForm((prev) => ({ ...prev, name: "", description: "" }));
      setSelectedProjectId(created.id);
      setSelectedChapterId(null);
    });
  }

  async function createChapter() {
    if (!chapterForm.project_id || !chapterForm.title.trim()) return;
    await run("create-chapter", async () => {
      const body: Record<string, unknown> = {
        title: chapterForm.title.trim(),
        status: chapterForm.status,
      };
      if (chapterForm.outline.trim()) body.outline = chapterForm.outline.trim();
      if (chapterForm.parent_chapter_id) body.parent_chapter_id = Number(chapterForm.parent_chapter_id);
      const created = await api.createThesisChapter(Number(chapterForm.project_id), body);
      toast.success(`已创建章节：${created.title}`);
      setChapterForm((prev) => ({ ...prev, title: "", outline: "", parent_chapter_id: String(created.id) }));
      setSelectedProjectId(Number(chapterForm.project_id));
      setSelectedChapterId(created.id);
    });
  }

  async function addLink() {
    if (!linkForm.paper_id) return;
    const body: Record<string, unknown> = { role: linkForm.role };
    if (linkForm.note.trim()) body.note = linkForm.note.trim();
    if (linkForm.target_type === "chapter") {
      if (!linkForm.chapter_id) return;
      body.chapter_id = Number(linkForm.chapter_id);
    } else {
      if (!linkForm.project_id) return;
      body.project_id = Number(linkForm.project_id);
    }
    await run("add-link", async () => {
      await api.linkThesisPaper(Number(linkForm.paper_id), body);
      toast.success("已关联论文");
      setLinkForm((prev) => ({ ...prev, note: "" }));
    });
  }

  async function deleteLink(paperId: number, linkId: number) {
    const ok = await confirm({
      title: "删除链接？",
      message: "将删除这条论文规划链接，此操作不可撤销。",
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    await run(`delete-link-${linkId}`, async () => {
      await api.deleteThesisLink(paperId, linkId);
      toast.success("已删除链接");
    });
  }

  async function saveProject() {
    if (!selectedProject || !projectEdit.name.trim()) return;
    await run(`save-project-${selectedProject.id}`, async () => {
      await api.patchThesisProject(selectedProject.id, {
        name: projectEdit.name.trim(),
        kind: projectEdit.kind,
        status: projectEdit.status,
        description: projectEdit.description.trim() || null,
        parent_project_id: projectEdit.parent_project_id ? Number(projectEdit.parent_project_id) : null,
        sort_order: Number(projectEdit.sort_order || 0),
      });
      toast.success("项目已更新");
    });
  }

  async function archiveProject() {
    if (!selectedProject) return;
    await run(`archive-project-${selectedProject.id}`, async () => {
      await api.patchThesisProject(selectedProject.id, { status: "archived" });
      toast.success("项目已归档");
    });
  }

  async function deleteProject() {
    if (!selectedProject || projectDeleteReason) return;
    const ok = await confirm({
      title: "删除项目？",
      message: `将删除空项目「${selectedProject.name}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    await run(`delete-project-${selectedProject.id}`, async () => {
      await api.deleteThesisProject(selectedProject.id);
      setSelectedProjectId(null);
      setSelectedChapterId(null);
      toast.success("项目已删除");
    });
  }

  async function nudgeProject(delta: number) {
    if (!selectedProject) return;
    await run(`sort-project-${selectedProject.id}`, async () => {
      await api.patchThesisProject(selectedProject.id, { sort_order: selectedProject.sort_order + delta });
      toast.success("项目顺序已更新");
    });
  }

  async function saveChapter() {
    if (!selectedChapter || !chapterEdit.title.trim()) return;
    await run(`save-chapter-${selectedChapter.id}`, async () => {
      await api.patchThesisChapter(selectedChapter.id, {
        title: chapterEdit.title.trim(),
        status: chapterEdit.status,
        outline: chapterEdit.outline.trim() || null,
        parent_chapter_id: chapterEdit.parent_chapter_id ? Number(chapterEdit.parent_chapter_id) : null,
        sort_order: Number(chapterEdit.sort_order || 0),
      });
      toast.success("章节已更新");
    });
  }

  async function nudgeChapter(delta: number) {
    if (!selectedChapter) return;
    await run(`sort-chapter-${selectedChapter.id}`, async () => {
      await api.patchThesisChapter(selectedChapter.id, { sort_order: selectedChapter.sort_order + delta });
      toast.success("章节顺序已更新");
    });
  }

  async function deleteChapter() {
    if (!selectedChapter || chapterDeleteReason) return;
    const ok = await confirm({
      title: "删除章节？",
      message: `将删除空章节「${selectedChapter.title}」，此操作不可撤销。`,
      variant: "danger",
      confirmText: "删除",
    });
    if (!ok) return;
    await run(`delete-chapter-${selectedChapter.id}`, async () => {
      await api.deleteThesisChapter(selectedChapter.id);
      setSelectedChapterId(null);
      toast.success("章节已删除");
    });
  }

  async function saveLink(paperId: number, linkId: number) {
    const draft = linkDrafts[linkId];
    if (!draft) return;
    await run(`save-link-${linkId}`, async () => {
      await api.patchThesisLink(paperId, linkId, { role: draft.role, note: draft.note.trim() || null });
      toast.success("链接已更新");
    });
  }

  function downloadMarkdown(scope: ThesisMarkdownExportScope) {
    const target = buildThesisMarkdownExportTarget(scope, selectedProjectId, selectedChapterId);
    if (!target) return;
    window.location.href = api.exportThesisMarkdownUrl(target);
  }

  function selectProject(projectId: number) {
    setSelectedProjectId(projectId);
    setSelectedChapterId(null);
    setChapterForm((prev) => ({ ...prev, project_id: String(projectId), parent_chapter_id: "" }));
    setLinkForm((prev) => ({ ...prev, target_type: "project", project_id: String(projectId), chapter_id: "" }));
  }

  function selectChapter(projectId: number, chapterId: number) {
    setSelectedProjectId(projectId);
    setSelectedChapterId(chapterId);
    setChapterForm((prev) => ({ ...prev, project_id: String(projectId), parent_chapter_id: String(chapterId) }));
    setLinkForm((prev) => ({
      ...prev,
      target_type: "chapter",
      project_id: String(projectId),
      chapter_id: String(chapterId),
    }));
  }

  return (
    <div className="space-y-4">
      {loading && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{ borderColor: "var(--border)", color: "var(--muted)" }}>
          正在加载论文规划工作区…
        </div>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={() => onRefresh()} className="btn-ghost py-1 text-xs" disabled={!!busy}>
          {busy ? "处理中…" : "刷新"}
        </button>
        <button
          onClick={() => downloadMarkdown("project")}
          className="btn-ghost py-1 text-xs"
          disabled={!!busy || !projectExportTarget}
        >
          导出项目素材
        </button>
        <button
          onClick={() => downloadMarkdown("chapter")}
          className="btn-ghost py-1 text-xs"
          disabled={!!busy || !chapterExportTarget}
        >
          导出章节素材
        </button>
        <span className="chip">项目 {data.projects.length}</span>
        <span className="chip">章节 {indexes.chapterLabels.size}</span>
        <span className="chip">论文 {data.papers.length}</span>
        <span className="chip">链接 {data.papers.reduce((sum, paper) => sum + paper.links.length, 0)}</span>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <div className="space-y-4">
          <section className="space-y-3 rounded-lg border p-3 border-[var(--border)]">
            <h4 className="font-semibold">新建项目 / 章节</h4>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              <div className="space-y-2">
                <div className="label">项目</div>
                <input
                  className="input"
                  placeholder="名称"
                  value={projectForm.name}
                  onChange={(e) => setProjectForm({ ...projectForm, name: e.target.value })}
                />
                <select
                  className="input"
                  value={projectForm.kind}
                  onChange={(e) => setProjectForm({ ...projectForm, kind: e.target.value })}
                >
                  {["direction", "topic", "experiment", "writing", "other"].map((kind) => (
                    <option key={kind} value={kind}>
                      {labelFor(PROJECT_KIND_LABELS, kind)}
                    </option>
                  ))}
                </select>
                <select
                  className="input"
                  value={projectForm.parent_project_id}
                  onChange={(e) => setProjectForm({ ...projectForm, parent_project_id: e.target.value })}
                >
                  <option value="">根项目</option>
                  {indexes.projectOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <textarea
                  className="input min-h-20 resize-y"
                  placeholder="说明"
                  value={projectForm.description}
                  onChange={(e) => setProjectForm({ ...projectForm, description: e.target.value })}
                />
                <button onClick={createProject} className="btn-primary w-full" disabled={!!busy}>
                  新建项目
                </button>
              </div>

              <div className="space-y-2">
                <div className="label">章节</div>
                <select
                  className="input"
                  value={chapterForm.project_id}
                  onChange={(e) => setChapterForm({ ...chapterForm, project_id: e.target.value })}
                >
                  <option value="">选择项目</option>
                  {indexes.projectOptions.map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <input
                  className="input"
                  placeholder="标题"
                  value={chapterForm.title}
                  onChange={(e) => setChapterForm({ ...chapterForm, title: e.target.value })}
                />
                <select
                  className="input"
                  value={chapterForm.parent_chapter_id}
                  onChange={(e) => setChapterForm({ ...chapterForm, parent_chapter_id: e.target.value })}
                  disabled={!chapterForm.project_id}
                >
                  <option value="">顶层章节</option>
                  {chapterForm.project_id &&
                    (indexes.chapterOptionsByProject.get(Number(chapterForm.project_id)) ?? []).map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                </select>
                <select
                  className="input"
                  value={chapterForm.status}
                  onChange={(e) => setChapterForm({ ...chapterForm, status: e.target.value })}
                >
                  {["draft", "in_progress", "review", "done"].map((status) => (
                    <option key={status} value={status}>
                      {labelFor(CHAPTER_STATUS_LABELS, status)}
                    </option>
                  ))}
                </select>
                <textarea
                  className="input min-h-20 resize-y"
                  placeholder="大纲"
                  value={chapterForm.outline}
                  onChange={(e) => setChapterForm({ ...chapterForm, outline: e.target.value })}
                />
                <button onClick={createChapter} className="btn-primary w-full" disabled={!!busy || !chapterForm.project_id}>
                  新建章节
                </button>
              </div>
            </div>
          </section>

          <section className="space-y-3 rounded-lg border p-3 border-[var(--border)]">
            <div className="flex items-center justify-between gap-3">
              <h4 className="font-semibold">当前选中</h4>
              <span className="text-xs text-faint">
                {selectedChapter ? "章节" : selectedProject ? "项目" : "无"}
              </span>
            </div>

            {selectedProject ? (
              <div className="space-y-2">
                <div className="label">项目详情</div>
                <input
                  className="input"
                  value={projectEdit.name}
                  onChange={(e) => setProjectEdit({ ...projectEdit, name: e.target.value })}
                />
                <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
                  <select
                    className="input"
                    value={projectEdit.kind}
                    onChange={(e) => setProjectEdit({ ...projectEdit, kind: e.target.value })}
                  >
                    {["direction", "topic", "experiment", "writing", "other"].map((kind) => (
                      <option key={kind} value={kind}>
                        {labelFor(PROJECT_KIND_LABELS, kind)}
                      </option>
                    ))}
                  </select>
                  <select
                    className="input"
                    value={projectEdit.status}
                    onChange={(e) => setProjectEdit({ ...projectEdit, status: e.target.value })}
                  >
                    {["active", "paused", "done", "archived"].map((status) => (
                      <option key={status} value={status}>
                        {labelFor(PROJECT_STATUS_LABELS, status)}
                      </option>
                    ))}
                  </select>
                  <input
                    className="input"
                    type="number"
                    value={projectEdit.sort_order}
                    onChange={(e) => setProjectEdit({ ...projectEdit, sort_order: e.target.value })}
                  />
                </div>
                <select
                  className="input"
                  value={projectEdit.parent_project_id}
                  onChange={(e) => setProjectEdit({ ...projectEdit, parent_project_id: e.target.value })}
                >
                  <option value="">根项目</option>
                  {validProjectParentOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                </select>
                <textarea
                  className="input min-h-20 resize-y"
                  value={projectEdit.description}
                  onChange={(e) => setProjectEdit({ ...projectEdit, description: e.target.value })}
                />
                <div className="flex flex-wrap gap-2">
                  <button onClick={saveProject} className="btn-primary py-1 text-xs" disabled={!!busy}>
                    保存项目
                  </button>
                  <button onClick={() => nudgeProject(-1)} className="btn-ghost py-1 text-xs" disabled={!!busy}>
                    上移
                  </button>
                  <button onClick={() => nudgeProject(1)} className="btn-ghost py-1 text-xs" disabled={!!busy}>
                    下移
                  </button>
                  <button onClick={archiveProject} className="btn-ghost py-1 text-xs text-[var(--danger)]" disabled={!!busy} >
                    归档
                  </button>
                  <button
                    onClick={deleteProject}
                    className="btn-ghost py-1 text-xs"
                    disabled={!!busy || !!projectDeleteReason}
                    title={projectDeleteReason ?? "删除空项目"}
                    style={{ color: projectDeleteReason ? "var(--faint)" : "var(--danger)" }}
                  >
                    删除空项目
                  </button>
                </div>
                {projectDeleteReason && (
                  <p className="text-xs text-faint">
                    不能删除：{projectDeleteReason}。请先移动、删除或解除相关内容。
                  </p>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted">
                请从左侧树中选择项目或章节。
              </p>
            )}

            {selectedChapter && (
              <div className="space-y-2 border-t pt-3 border-[var(--border)]">
                <div className="label">章节详情</div>
                <input
                  className="input"
                  value={chapterEdit.title}
                  onChange={(e) => setChapterEdit({ ...chapterEdit, title: e.target.value })}
                />
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                <select
                  className="input"
                  value={chapterEdit.status}
                  onChange={(e) => setChapterEdit({ ...chapterEdit, status: e.target.value })}
                >
                  {["draft", "in_progress", "review", "done"].map((status) => (
                    <option key={status} value={status}>
                      {labelFor(CHAPTER_STATUS_LABELS, status)}
                    </option>
                  ))}
                </select>
                  <input
                    className="input"
                    type="number"
                    value={chapterEdit.sort_order}
                    onChange={(e) => setChapterEdit({ ...chapterEdit, sort_order: e.target.value })}
                  />
                </div>
                <select
                  className="input"
                  value={chapterEdit.parent_chapter_id}
                  onChange={(e) => setChapterEdit({ ...chapterEdit, parent_chapter_id: e.target.value })}
                >
                  <option value="">顶层章节</option>
                  {validChapterParentOptions.map((option) => (
                      <option key={option.id} value={option.id}>
                        {option.label}
                      </option>
                    ))}
                </select>
                <textarea
                  className="input min-h-20 resize-y"
                  value={chapterEdit.outline}
                  onChange={(e) => setChapterEdit({ ...chapterEdit, outline: e.target.value })}
                />
                <div className="flex flex-wrap gap-2">
                  <button onClick={saveChapter} className="btn-primary py-1 text-xs" disabled={!!busy}>
                    保存章节
                  </button>
                  <button onClick={() => nudgeChapter(-1)} className="btn-ghost py-1 text-xs" disabled={!!busy}>
                    上移
                  </button>
                  <button onClick={() => nudgeChapter(1)} className="btn-ghost py-1 text-xs" disabled={!!busy}>
                    下移
                  </button>
                  <button
                    onClick={deleteChapter}
                    className="btn-ghost py-1 text-xs"
                    disabled={!!busy || !!chapterDeleteReason}
                    title={chapterDeleteReason ?? "删除空章节"}
                    style={{ color: chapterDeleteReason ? "var(--faint)" : "var(--danger)" }}
                  >
                    删除空章节
                  </button>
                </div>
                {chapterDeleteReason && (
                  <p className="text-xs text-faint">
                    不能删除：{chapterDeleteReason}。请先移动、删除或解除相关内容。
                  </p>
                )}
              </div>
            )}
          </section>

          <section className="space-y-2 rounded-lg border p-3 border-[var(--border)]">
            <div className="flex items-center justify-between gap-3">
              <h4 className="font-semibold">项目树</h4>
              <span className="text-xs text-faint">
                {selectedProject ? indexes.projectLabels.get(selectedProject.id) ?? selectedProject.name : "未选择"}
              </span>
            </div>
            {data.projects.length === 0 ? (
              <p className="text-sm text-muted">
                还没有项目。
              </p>
            ) : (
              <div className="space-y-2">
                {data.projects.map((project) => (
                  <ProjectTreeNode
                    key={project.id}
                    project={project}
                    selectedProjectId={selectedProjectId}
                    selectedChapterId={selectedChapterId}
                    onSelectProject={selectProject}
                    onSelectChapter={selectChapter}
                  />
                ))}
              </div>
            )}
          </section>
        </div>

        <div className="space-y-4">
          <section className="space-y-3 rounded-lg border p-3 border-[var(--border)]">
            <h4 className="font-semibold">关联论文</h4>
            <input
              className="input"
              placeholder="搜索论文"
              value={paperQuery}
              onChange={(e) => setPaperQuery(e.target.value)}
            />
            <div className="max-h-44 space-y-1 overflow-auto">
              {filteredPapers.length === 0 ? (
                <p className="text-sm text-muted">
                  没有匹配的论文。
                </p>
              ) : (
                filteredPapers.map((paper) => {
                  const active = Number(linkForm.paper_id) === paper.id;
                  const attached = data.papers.find((item) => item.id === paper.id)?.links.length ?? 0;
                  return (
                    <button
                      key={paper.id}
                      type="button"
                      onClick={() => setLinkForm({ ...linkForm, paper_id: String(paper.id) })}
                      className="flex w-full items-center gap-2 rounded-lg border px-3 py-2 text-left"
                      style={
                        active
                          ? { borderColor: "var(--accent)", backgroundColor: "var(--accent-soft)" }
                          : { borderColor: "var(--border)", backgroundColor: "var(--surface)" }
                      }
                    >
                      <span className="flex-1 min-w-0">
                        <span className="block truncate font-medium">{paperLabel(paper)}</span>
                        <span className="block text-[11px] text-faint">
                          {paper.authors.slice(0, 3).join(", ")}
                          {paper.authors.length > 3 ? " 等" : ""}
                        </span>
                      </span>
                      {attached > 0 && <span className="chip">{attached} 条链接</span>}
                    </button>
                  );
                })
              )}
            </div>

            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <select
                className="input"
                value={linkForm.target_type}
                onChange={(e) =>
                  setLinkForm({
                    ...linkForm,
                    target_type: e.target.value as TargetType,
                    chapter_id: e.target.value === "chapter" ? linkForm.chapter_id : "",
                  })
                }
              >
                <option value="project">项目</option>
                <option value="chapter">章节</option>
              </select>
              <select className="input" value={linkForm.role} onChange={(e) => setLinkForm({ ...linkForm, role: e.target.value })}>
                {["background", "method", "comparison", "evidence", "limitation", "inspiration", "related", "to_read"].map((role) => (
                  <option key={role} value={role}>
                    {labelFor(LINK_ROLE_LABELS, role)}
                  </option>
                ))}
              </select>
              <select
                className="input"
                value={linkForm.project_id}
                onChange={(e) =>
                  setLinkForm({
                    ...linkForm,
                    project_id: e.target.value,
                    chapter_id: linkForm.target_type === "chapter" ? "" : linkForm.chapter_id,
                  })
                }
              >
                <option value="">选择项目</option>
                {indexes.projectOptions.map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <select
                className="input"
                value={linkForm.chapter_id}
                onChange={(e) => setLinkForm({ ...linkForm, chapter_id: e.target.value })}
                disabled={linkForm.target_type !== "chapter" || !linkForm.project_id}
              >
                <option value="">选择章节</option>
                {(linkForm.project_id ? indexes.chapterOptionsByProject.get(Number(linkForm.project_id)) ?? [] : []).map((option) => (
                  <option key={option.id} value={option.id}>
                    {option.label}
                  </option>
                ))}
              </select>
              <textarea
                className="input min-h-20 resize-y md:col-span-2"
                placeholder="备注"
                value={linkForm.note}
                onChange={(e) => setLinkForm({ ...linkForm, note: e.target.value })}
              />
            </div>

            {selectedPaper && (
              <p className="text-xs text-muted">
                当前选择：{paperLabel(selectedPaper)}
              </p>
            )}
            <button onClick={addLink} className="btn-primary w-full" disabled={!!busy || !linkForm.paper_id}>
              添加链接
            </button>
          </section>

          <section className="space-y-2 rounded-lg border p-3 border-[var(--border)]">
            <h4 className="font-semibold">已关联论文</h4>
            {data.papers.length === 0 ? (
              <p className="text-sm text-muted">
                还没有关联论文。
              </p>
            ) : (
              <div className="space-y-2">
                {data.papers.map((paper) => (
                  <div key={paper.id} className="space-y-2 rounded-lg border p-3 border-[var(--border)]">
                    <div className="flex items-start justify-between gap-3">
                      <button type="button" onClick={() => onOpenPaper(paper.id)} className="text-left font-medium hover:underline">
                        {paperLabel(paper)}
                      </button>
                      <span className="chip">{paper.links.length} 条链接</span>
                    </div>
                    {paper.links.map((link) => {
                      const target =
                        link.chapter_id != null
                          ? indexes.chapterLabels.get(link.chapter_id) ?? `章节 #${link.chapter_id}`
                          : link.project_id != null
                            ? indexes.projectLabels.get(link.project_id) ?? `项目 #${link.project_id}`
                            : "未知";
                      return (
                        <div key={link.id} className="flex flex-col gap-2 rounded-lg border px-3 py-2 text-sm md:flex-row md:items-start border-[var(--border)]">
                          <div className="flex-1 min-w-0">
                            <div className="font-medium">{target}</div>
                            <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-[10rem_1fr]">
                              <select
                                className="input py-1 text-xs"
                                value={linkDrafts[link.id]?.role ?? link.role}
                                onChange={(e) =>
                                  setLinkDrafts((prev) => ({
                                    ...prev,
                                    [link.id]: { role: e.target.value, note: prev[link.id]?.note ?? link.note ?? "" },
                                  }))
                                }
                              >
                                {["background", "method", "comparison", "evidence", "limitation", "inspiration", "related", "to_read"].map((role) => (
                                  <option key={role} value={role}>
                                    {labelFor(LINK_ROLE_LABELS, role)}
                                  </option>
                                ))}
                              </select>
                              <input
                                className="input py-1 text-xs"
                                value={linkDrafts[link.id]?.note ?? link.note ?? ""}
                                placeholder="链接备注"
                                onChange={(e) =>
                                  setLinkDrafts((prev) => ({
                                    ...prev,
                                    [link.id]: { role: prev[link.id]?.role ?? link.role, note: e.target.value },
                                  }))
                                }
                              />
                            </div>
                            <div className="hidden">
                              {labelFor(LINK_ROLE_LABELS, link.role)}
                              {link.note ? ` · ${link.note}` : ""}
                            </div>
                          </div>
                          <button onClick={() => saveLink(paper.id, link.id)} className="btn-ghost py-1 text-xs" disabled={!!busy}>
                            保存
                          </button>
                          <button onClick={() => deleteLink(paper.id, link.id)} className="btn-ghost py-1 text-xs text-[var(--danger)]">
                            删除
                          </button>
                        </div>
                      );
                    })}
                  </div>
                ))}
              </div>
            )}
          </section>
        </div>
      </div>
    </div>
  );
}
