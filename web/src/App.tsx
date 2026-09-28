import { useCallback, useEffect, useState } from 'react';
import {
  App as AntApp,
  Button,
  Checkbox,
  Collapse,
  Empty,
  Input,
  Modal,
  Select,
  Spin,
  Tag,
  Upload,
} from 'antd';
import {
  ArrowRightOutlined,
  BookOutlined,
  CheckCircleOutlined,
  FileTextOutlined,
  HistoryOutlined,
  LogoutOutlined,
  PlusOutlined,
  SearchOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import { z } from 'zod';
import { api, errorMessage, refreshCsrf } from './api';
import { AttachmentChoice, AttachmentInput, attachmentAccept, useAttachments } from './attachments';
import {
  citedSegments,
  detailSchema,
  documentSchema,
  isTerminal,
  sessionSchema,
  sourceUrl,
  statusLabel,
  taskSchema,
  type Detail,
  type Document,
  type Evidence,
  type Task,
} from './domain';
const ok = z.object({ ok: z.boolean() });
export function App(): React.JSX.Element {
  const { message } = AntApp.useApp();
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [username, setUsername] = useState('demo');
  const [password, setPassword] = useState('');
  const [register, setRegister] = useState(false);
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState('workbench');
  const [documents, setDocuments] = useState<Document[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [sessions, setSessions] = useState<z.infer<typeof sessionSchema>[]>([]);
  const [session, setSession] = useState<number>();
  const [selected, setSelected] = useState<number[]>([]);
  const [instruction, setInstruction] = useState('');
  const [activeId, setActiveId] = useState<number>();
  const [detail, setDetail] = useState<Detail>();
  const [evidence, setEvidence] = useState<Evidence>();
  const [reviewOpen, setReviewOpen] = useState(false);
  const [decision, setDecision] = useState('CONFIRMED');
  const [note, setNote] = useState('');
  const [page, setPage] = useState(0);
  const [connection, setConnection] = useState('');
  const notify = useCallback(
    (e: unknown): void => {
      void message.error(errorMessage(e));
    },
    [message]
  );
  const load = useCallback(async (): Promise<void> => {
    const [docs, history, conversations] = await Promise.all([
      api('/documents', z.array(documentSchema)),
      api(`/tasks?page=${page}`, z.array(taskSchema)),
      api('/sessions', z.array(sessionSchema)),
    ]);
    setDocuments(docs);
    setTasks(history);
    setSessions(conversations);
  }, [page]);
  const attachments = useAttachments(notify, load);
  const taskDocuments = [...new Set([...selected, ...attachments.documents.map((doc) => doc.id)])];
  const refreshDetail = useCallback(async (id: number): Promise<Detail> => {
    const current = await api(`/tasks/${id}`, detailSchema);
    setDetail(current);
    return current;
  }, []);
  useEffect(() => {
    void api('/auth/me', z.object({ id: z.number() }))
      .then(() => setAuthenticated(true))
      .catch(() => setAuthenticated(false));
  }, []);
  useEffect(() => {
    if (!authenticated) return;
    void load().catch(notify);
    const timer = setInterval(() => {
      void load().catch(notify);
    }, 5000);
    return () => clearInterval(timer);
  }, [authenticated, load, notify]);
  useEffect(() => {
    if (activeId === undefined || !authenticated) return;
    let closed = false;
    let stream: EventSource | undefined;
    void refreshDetail(activeId)
      .then((current) => {
        if (closed || isTerminal(current.status)) return;
        stream = new EventSource(`/api/tasks/${activeId}/events`);
        setConnection('实时连接');
        stream.onmessage = () => {
          void refreshDetail(activeId)
            .then((updated) => {
              if (isTerminal(updated.status)) {
                stream?.close();
                setConnection('执行结束');
                void load().catch(notify);
              }
            })
            .catch(notify);
        };
        stream.onerror = () => {
          if (!closed) setConnection('连接中断，正在重连');
        };
      })
      .catch(notify);
    return () => {
      closed = true;
      stream?.close();
    };
  }, [activeId, authenticated, refreshDetail, load, notify]);
  async function login(): Promise<void> {
    setBusy(true);
    try {
      await refreshCsrf();
      if (register)
        await api('/auth/register', z.object({ id: z.number() }), {
          method: 'POST',
          body: JSON.stringify({ username, password }),
        });
      await api('/auth/login', z.object({ id: z.number() }), {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      await refreshCsrf();
      setAuthenticated(true);
      setPassword('');
    } catch (e) {
      notify(e);
    } finally {
      setBusy(false);
    }
  }
  async function upload(file: File): Promise<void> {
    const form = new FormData();
    form.append('file', file);
    await api('/documents', documentSchema, { method: 'POST', body: form });
    await load();
    void message.success('文档已上传，正在构建检索索引');
  }
  async function submit(): Promise<void> {
    setBusy(true);
    try {
      let sessionId = session;
      if (sessionId === undefined) {
        const created = await api('/sessions', z.object({ id: z.number() }), {
          method: 'POST',
          body: JSON.stringify({ title: instruction.slice(0, 45) }),
        });
        sessionId = created.id;
        setSession(sessionId);
      }
      const task = await api('/tasks', taskSchema, {
        method: 'POST',
        body: JSON.stringify({
          session_id: sessionId,
          document_ids: taskDocuments,
          instruction,
          idempotency_key: crypto.randomUUID(),
        }),
      });
      attachments.consumed();
      setActiveId(task.id);
      setEvidence(undefined);
      await load();
    } catch (e) {
      notify(e);
    } finally {
      setBusy(false);
    }
  }
  async function review(): Promise<void> {
    if (!detail) return;
    setBusy(true);
    try {
      const updated = await api(`/tasks/${detail.id}/reviews`, detailSchema, {
        method: 'POST',
        body: JSON.stringify({ version: detail.version, decision, note }),
      });
      setDetail(updated);
      setReviewOpen(false);
      setNote('');
      await load();
    } catch (e) {
      notify(e);
    } finally {
      setBusy(false);
    }
  }
  function chooseTask(id: number): void {
    setActiveId(id);
    setEvidence(undefined);
    setView('workbench');
  }
  const ready = documents.filter((doc) => doc.status === 'READY');
  if (authenticated === null)
    return (
      <div className="loading">
        <Spin size="large" />
      </div>
    );
  if (!authenticated)
    return (
      <div className="login-shell">
        <section className="login-story">
          <div className="brand">
            <span className="brand-symbol">F</span> FINANCIAL RESEARCH
          </div>
          <div>
            <span className="eyebrow">DOCUMENT INTELLIGENCE</span>
            <h1>
              让每一个结论，
              <br />
              都有据可查。
            </h1>
            <p>
              连接金融文档、分析过程与原始证据。
              <br />
              从一次提问，走向可追溯的研究结论。
            </p>
            <div className="login-tags">
              <span>多 Agent 协作</span>
              <span>混合检索</span>
              <span>人工审阅</span>
            </div>
          </div>
          <small>金融文档核查与证据追溯平台</small>
        </section>
        <section className="login-panel">
          <div className="login-box">
            <span className="eyebrow">YOUR RESEARCH WORKSPACE</span>
            <h2>{register ? '创建研究账号' : '欢迎回来'}</h2>
            <p className="muted">登录后管理你的文档与核查记录</p>
            <label>
              账号
              <Input
                aria-label="账号"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="3–40 位字母、数字或下划线"
              />
            </label>
            <label>
              密码
              <Input.Password
                aria-label="密码"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onPressEnter={() => void login()}
                placeholder="至少 8 位字符"
              />
            </label>
            <Button type="primary" size="large" block loading={busy} onClick={() => void login()}>
              {register ? '注册并进入工作台' : '进入工作台'} <ArrowRightOutlined />
            </Button>
            <button className="text-button" onClick={() => setRegister(!register)}>
              {register ? '已有账号，返回登录' : '没有账号？创建账号'}
            </button>
            <div className="login-note">
              本地应用 · 账号数据隔离
              <br />
              模型与向量生成使用云端 API，请仅上传获准处理的资料。
            </div>
          </div>
        </section>
      </div>
    );
  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-symbol">F</span>
          <div>
            金融研究台<small>FINANCIAL WORKSPACE</small>
          </div>
        </div>
        <div className="nav-label">研究空间</div>
        <nav>
          <button
            className={view === 'workbench' ? 'active' : ''}
            onClick={() => setView('workbench')}
          >
            <SearchOutlined />
            核查工作台
          </button>
          <button
            className={view === 'documents' ? 'active' : ''}
            onClick={() => setView('documents')}
          >
            <BookOutlined />
            文档资料库<span>{documents.length}</span>
          </button>
          <button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>
            <HistoryOutlined />
            历史与审阅
          </button>
        </nav>
        <div className="side-note">
          <span className="live-dot" /> 本地工作空间
          <p>
            MySQL 持久化
            <br />
            Qdrant 本地向量存储
            <br />
            Qwen 模型服务
          </p>
        </div>
        <button
          className="logout"
          disabled={busy || attachments.uploading}
          onClick={() => {
            void attachments
              .clear()
              .then(() => api('/auth/logout', ok, { method: 'POST' }))
              .then(() => {
                setAuthenticated(false);
                setRegister(false);
                setActiveId(undefined);
                setDetail(undefined);
                setSelected([]);
                setSession(undefined);
              })
              .catch(notify);
          }}
        >
          <LogoutOutlined />
          退出登录
        </button>
      </aside>
      <main className="main">
        <header>
          <div>
            <span className="eyebrow">FINANCIAL AGENTIC WORKFLOW</span>
            <h1>
              {view === 'documents'
                ? '文档资料库'
                : view === 'history'
                  ? '历史与审阅'
                  : '金融文档核查与证据追溯'}
            </h1>
          </div>
          <span className="workspace-badge">
            <span className="live-dot" />
            本地运行
          </span>
        </header>
        {view === 'documents' ? (
          <>
            <div className="page-intro">
              <div>
                <h2>先建立你的证据来源</h2>
                <p>上传年报与监管文件，保留页码和段落，构建可回溯的检索索引。</p>
              </div>
              <div className="actions">
                <Button
                  loading={busy}
                  onClick={() => {
                    setBusy(true);
                    void api('/documents/samples', z.array(documentSchema), { method: 'POST' })
                      .then(load)
                      .catch(notify)
                      .finally(() => setBusy(false));
                  }}
                >
                  导入真实样例
                </Button>
                <Upload
                  accept={attachmentAccept}
                  showUploadList={false}
                  beforeUpload={(file) => {
                    void upload(file).catch(notify);
                    return false;
                  }}
                >
                  <Button type="primary" icon={<UploadOutlined />}>
                    上传文档
                  </Button>
                </Upload>
              </div>
            </div>
            <div className="stat-row">
              <Stat label="全部文档" value={documents.length} />
              <Stat label="可检索文档" value={ready.length} />
              <Stat
                label="已建立片段"
                value={documents.reduce((total, doc) => total + doc.chunk_count, 0)}
              />
            </div>
            <div className="card document-list">
              <div className="card-title">
                文档目录<span>PDF / HTML / TXT / PNG / JPG · 单文件 ≤ 35 MB</span>
              </div>
              {documents.length === 0 ? (
                <Empty description="还没有文档，上传资料或导入真实样例" />
              ) : (
                documents.map((doc) => (
                  <div className="document-row" key={doc.id}>
                    <span className="file-icon">
                      <FileTextOutlined />
                    </span>
                    <div className="grow">
                      <strong>{doc.filename}</strong>
                      <p>
                        {doc.chunk_count} 个片段{' '}
                        {doc.error && <span className="error-text">· {doc.error}</span>}
                      </p>
                    </div>
                    <Status status={doc.status} />
                    <a href={`/api/documents/${doc.id}/source`} target="_blank" rel="noreferrer">
                      查看原文 ↗
                    </a>
                  </div>
                ))
              )}
            </div>
            <p className="footnote">
              PNG / JPG 支持本机文字识别，数字与表格请核对原图；扫描版 PDF 暂不支持 OCR。
            </p>
          </>
        ) : view === 'history' ? (
          <>
            <div className="page-intro">
              <div>
                <h2>保留每一次核查的上下文</h2>
                <p>查阅机器结论、原始引用，以及后续人工确认与修正。</p>
              </div>
            </div>
            <div className="card history-list">
              {tasks.length === 0 ? (
                <Empty description="暂无核查记录" />
              ) : (
                tasks.map((task) => (
                  <button className="history-row" key={task.id} onClick={() => chooseTask(task.id)}>
                    <span className="file-icon">
                      <HistoryOutlined />
                    </span>
                    <div className="grow">
                      <strong>{task.instruction}</strong>
                      <p>
                        任务 #{task.id} · 会话 #{task.session_id}
                      </p>
                    </div>
                    <Status status={task.review_status} />
                    <Status status={task.status} />
                    <ArrowRightOutlined />
                  </button>
                ))
              )}
            </div>
            <div className="pagination">
              <Button disabled={page === 0} onClick={() => setPage(page - 1)}>
                上一页
              </Button>
              <span>第 {page + 1} 页</span>
              <Button disabled={tasks.length < 30} onClick={() => setPage(page + 1)}>
                下一页
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="workbench-intro">
              <p>检索原文、交叉核查、精确计算。把分析过程与证据留在一起。</p>
              <Button
                icon={<PlusOutlined />}
                disabled={busy || attachments.uploading}
                onClick={() => {
                  setBusy(true);
                  void attachments
                    .clear()
                    .then(() => {
                      setActiveId(undefined);
                      setDetail(undefined);
                      setEvidence(undefined);
                      setInstruction('');
                      setSession(undefined);
                    })
                    .catch(notify)
                    .finally(() => setBusy(false));
                }}
              >
                新建核查
              </Button>
            </div>
            <div className="work-grid">
              <section className="card task-panel">
                <div className="card-title">
                  核查任务<span>{tasks.length}</span>
                </div>
                <div className="task-list">
                  {tasks.length === 0 ? (
                    <div className="small-empty">
                      还没有任务
                      <br />
                      从右侧发起一次核查
                    </div>
                  ) : (
                    tasks.map((task) => (
                      <button
                        className={`task-item ${activeId === task.id ? 'selected' : ''}`}
                        key={task.id}
                        onClick={() => chooseTask(task.id)}
                      >
                        <small>
                          #{task.id} <Status status={task.status} />
                        </small>
                        <strong>{task.instruction}</strong>
                      </button>
                    ))
                  )}
                </div>
                <div className="task-footer">执行记录自动保存</div>
              </section>
              <section className="analysis-column">
                <div className="card composer">
                  <div className="card-title">
                    <span className="section-number">01</span>定义核查问题
                  </div>
                  <label className="field-label">
                    选择资料 <span>仅已完成索引的文档可用</span>
                  </label>
                  {ready.length === 0 ? (
                    <div className="upload-reminder">
                      文档库还没有可检索资料。
                      <button className="text-button" onClick={() => setView('documents')}>
                        前往上传 →
                      </button>
                    </div>
                  ) : (
                    <Checkbox.Group
                      value={selected}
                      onChange={(values) =>
                        setSelected(
                          values.filter((value): value is number => typeof value === 'number')
                        )
                      }
                    >
                      {ready.map((doc) => (
                        <Checkbox value={doc.id} key={doc.id}>
                          {doc.filename}
                        </Checkbox>
                      ))}
                    </Checkbox.Group>
                  )}
                  <Select
                    aria-label="选择会话"
                    className="session-select"
                    value={session}
                    allowClear
                    placeholder="新会话（自动创建）"
                    onChange={setSession}
                    options={sessions.map((item) => ({ label: item.title, value: item.id }))}
                  />
                  <AttachmentInput
                    attachments={attachments}
                    disabled={busy || attachments.uploading}
                    notify={notify}
                  >
                    <Input.TextArea
                      aria-label="核查问题"
                      disabled={busy || attachments.uploading}
                      value={instruction}
                      onChange={(e) => setInstruction(e.target.value)}
                      autoSize={{ minRows: 3, maxRows: 7 }}
                      maxLength={4000}
                      placeholder="例如：比较宁德时代两份年报中的营业收入，核对同比增幅，注明年份、单位和来源页码。"
                    />
                  </AttachmentInput>
                  <div className="composer-bottom">
                    <span>
                      {taskDocuments.length > 20
                        ? '资料超过 20 份，请移除部分附件或取消勾选'
                        : '自主选工具 · 多轮核查 · 原文引用'}
                    </span>
                    <Button
                      type="primary"
                      loading={busy}
                      disabled={
                        taskDocuments.length === 0 ||
                        taskDocuments.length > 20 ||
                        attachments.blocked ||
                        instruction.trim().length === 0
                      }
                      onClick={() => void submit()}
                    >
                      开始核查 <ArrowRightOutlined />
                    </Button>
                  </div>
                </div>
                {detail ? (
                  <>
                    <div className="card execution">
                      <div className="card-title">
                        <span className="section-number">02</span>执行过程
                        <div className="grow" />
                        <Status status={detail.status} />
                      </div>
                      <div className="execution-meta">
                        <span>
                          {detail.agents.length} 个 Agent · {detail.tools.length} 次工具调用
                        </span>
                        <span>{connection}</span>
                      </div>
                      {detail.agents.map((agent) => (
                        <div
                          className={`agent-card ${agent.parent_id ? 'child' : ''}`}
                          key={agent.id}
                        >
                          <div>
                            <span className="agent-dot" />
                            <strong>{agent.name}</strong>
                            <Status status={agent.status} />
                          </div>
                          <small>
                            {agent.parent_id ? '独立子任务' : '主任务'} · {agent.steps} 步 ·{' '}
                            {agent.prompt_tokens + agent.completion_tokens} tokens
                          </small>
                          <Collapse
                            ghost
                            size="small"
                            items={detail.tools
                              .filter((tool) => tool.agent_id === agent.id)
                              .map((tool) => ({
                                key: tool.id,
                                label: (
                                  <span className="tool-label">
                                    {tool.name}
                                    <Status status={tool.status} />
                                    <small>{(tool.duration_ms / 1000).toFixed(1)}s</small>
                                  </span>
                                ),
                                children: (
                                  <>
                                    <div className="code-label">输入参数</div>
                                    <pre>{tool.arguments}</pre>
                                    <div className="code-label">工具结果</div>
                                    <pre>{tool.result ?? '等待工具返回'}</pre>
                                  </>
                                ),
                              }))}
                          />
                        </div>
                      ))}
                      {detail.error && <div className="error-banner">{detail.error}</div>}
                      {!isTerminal(detail.status) && (
                        <Button
                          danger
                          onClick={() => {
                            void api(`/tasks/${detail.id}/cancel`, ok, { method: 'POST' })
                              .then(() => refreshDetail(detail.id))
                              .catch(notify);
                          }}
                        >
                          取消任务
                        </Button>
                      )}
                    </div>
                    {detail.result && (
                      <div className="card result">
                        <div className="card-title">
                          <span className="section-number">03</span>核查报告
                          <div className="grow" />
                          <Status status={detail.review_status} />
                        </div>
                        <div className="report-text">
                          {citedSegments(detail.result).map((segment, index) =>
                            segment.citation ? (
                              <button
                                className="citation"
                                key={index}
                                onClick={() => {
                                  const found = detail.evidence.find(
                                    (item) => item.citation_id === segment.text.slice(3, -1)
                                  );
                                  if (found) setEvidence(found);
                                }}
                              >
                                证据{' '}
                                {detail.evidence.findIndex(
                                  (item) => item.citation_id === segment.text.slice(3, -1)
                                ) + 1}{' '}
                                ↗
                              </button>
                            ) : (
                              <span key={index}>{segment.text}</span>
                            )
                          )}
                        </div>
                        <div className="review-bar">
                          <span>
                            <CheckCircleOutlined /> 保留机器原始结论，人工审阅单独记录
                          </span>
                          <Button
                            disabled={detail.status !== 'SUCCEEDED'}
                            onClick={() => setReviewOpen(true)}
                          >
                            人工审阅
                          </Button>
                        </div>
                        {detail.reviews.map((item) => (
                          <div className="review-note" key={item.id}>
                            <Status status={item.decision} />
                            <span>{item.note}</span>
                            <small>{item.created_at}</small>
                          </div>
                        ))}
                      </div>
                    )}
                  </>
                ) : (
                  <div className="empty-analysis">
                    <div className="empty-orbit">
                      <SearchOutlined />
                    </div>
                    <h3>分析，从一个好问题开始</h3>
                    <p>
                      主 Agent 会根据文档与问题选择工具，
                      <br />
                      在需要时委派子 Agent 独立查证。
                    </p>
                    <div className="flow-labels">
                      <span>检索证据</span>
                      <i>→</i>
                      <span>核查计算</span>
                      <i>→</i>
                      <span>引用溯源</span>
                    </div>
                  </div>
                )}
              </section>
              <aside className="card evidence-panel">
                <div className="card-title">
                  证据与原文<span>{detail?.evidence.length ?? 0}</span>
                </div>
                {evidence ? (
                  <div className="evidence-detail">
                    <Button size="small" type="text" onClick={() => setEvidence(undefined)}>
                      ← 全部证据
                    </Button>
                    <h3>{evidence.filename}</h3>
                    <Tag>{evidence.anchor}</Tag>
                    <p className="source-text">{evidence.text}</p>
                    <a
                      className="source-link"
                      href={sourceUrl(evidence)}
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开原始文档 ↗
                    </a>
                  </div>
                ) : detail && detail.evidence.length > 0 ? (
                  <div className="evidence-list">
                    {detail.evidence.map((item, index) => (
                      <button key={item.id} onClick={() => setEvidence(item)}>
                        <span className="evidence-index">{String(index + 1).padStart(2, '0')}</span>
                        <strong>{item.filename}</strong>
                        <small>{item.anchor}</small>
                        <p>{item.text.slice(0, 140)}…</p>
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="small-empty">
                    <FileTextOutlined />
                    <h4>原文是结论的起点</h4>
                    <p>
                      执行检索后，证据片段会出现在这里。
                      <br />
                      点击报告引用即可定位来源。
                    </p>
                  </div>
                )}
              </aside>
            </div>
          </>
        )}
        <footer>
          金融文档核查与证据追溯平台<span>分析结果需结合原文及人工审阅使用</span>
        </footer>
      </main>
      <AttachmentChoice attachments={attachments} />
      <Modal
        title="人工审阅"
        open={reviewOpen}
        confirmLoading={busy}
        onCancel={() => setReviewOpen(false)}
        onOk={() => void review()}
        okButtonProps={{ disabled: note.trim().length === 0 }}
        okText="保存审阅"
      >
        <p>机器原始结论不会被覆盖。修正内容及审阅状态将同时保存。</p>
        <Select
          aria-label="审阅决定"
          value={decision}
          onChange={setDecision}
          options={[
            { value: 'CONFIRMED', label: '确认结论' },
            { value: 'CORRECTED', label: '修正结论' },
          ]}
        />
        <Input.TextArea
          aria-label="审阅意见"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={5}
          maxLength={4000}
          placeholder="写下确认依据或具体修正内容"
        />
      </Modal>
    </div>
  );
}
function Status({ status }: { status: string }): React.JSX.Element {
  return (
    <Tag
      color={
        ['READY', 'SUCCEEDED', 'CONFIRMED'].includes(status)
          ? 'green'
          : status === 'FAILED'
            ? 'red'
            : status === 'RUNNING' || status === 'INDEXING'
              ? 'blue'
              : 'default'
      }
    >
      {statusLabel(status)}
    </Tag>
  );
}
function Stat({ label, value }: { label: string; value: number }): React.JSX.Element {
  return (
    <div className="card stat">
      <span>{label}</span>
      <strong>{value.toLocaleString()}</strong>
    </div>
  );
}
