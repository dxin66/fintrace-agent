import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { App as AntApp, ConfigProvider } from 'antd';
import { App } from '../src/App';
import type { Detail, Document, Task } from '../src/domain';
const mocks = vi.hoisted(() => ({ api: vi.fn(), refresh: vi.fn() }));
vi.mock('../src/api', () => ({
  api: mocks.api,
  refreshCsrf: mocks.refresh,
  errorMessage: (error: unknown) => (error instanceof Error ? error.message : 'unknown'),
}));
const evidence = {
  id: 'e1',
  citation_id: 'e1',
  document_id: 1,
  filename: '年报.pdf',
  page: 7,
  anchor: '第 7 页',
  text: '营业收入为100万元。',
};
let attachmentRows: Document[];
let authenticated: boolean, documents: Document[], tasks: Task[], current: Detail, failPath: string;
class FakeEvents {
  static instances: FakeEvents[] = [];
  onmessage: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close = vi.fn();
  constructor() {
    FakeEvents.instances.push(this);
  }
}
function mount(): ReturnType<typeof render> {
  return render(
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AntApp>
        <App />
      </AntApp>
    </ConfigProvider>
  );
}
beforeEach(() => {
  vi.stubGlobal(
    'matchMedia',
    vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }))
  );
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {}
      unobserve(): void {}
      disconnect(): void {}
    }
  );
  vi.stubGlobal('EventSource', FakeEvents);
  FakeEvents.instances = [];
  const computedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => computedStyle(element));
  authenticated = true;
  failPath = '';
  attachmentRows = [];
  documents = [
    { id: 1, filename: '年报.pdf', status: 'READY', chunk_count: 3, storage_scope: 'LIBRARY' },
    {
      id: 2,
      filename: '监管.txt',
      status: 'INDEXING',
      chunk_count: 0,
      storage_scope: 'LIBRARY',
      error: '索引中',
    },
  ];
  current = {
    id: 1,
    instruction: '核查收入',
    session_id: 1,
    status: 'SUCCEEDED',
    version: 0,
    review_status: 'PENDING',
    result: '收入100万元[E:e1]。',
    agents: [
      {
        id: 'a1',
        name: '主 Agent',
        status: 'SUCCEEDED',
        steps: 2,
        prompt_tokens: 100,
        completion_tokens: 20,
      },
      {
        id: 'a2',
        parent_id: 'a1',
        name: '子 Agent',
        status: 'SUCCEEDED',
        steps: 1,
        prompt_tokens: 50,
        completion_tokens: 10,
      },
    ],
    tools: [
      {
        id: 't1',
        agent_id: 'a1',
        name: 'search',
        arguments: '{"query":"收入"}',
        result: '找到收入',
        status: 'SUCCEEDED',
        duration_ms: 123,
      },
      {
        id: 't2',
        agent_id: 'a2',
        name: 'read',
        arguments: '{}',
        status: 'FAILED',
        duration_ms: 100,
      },
    ],
    evidence: [evidence],
    reviews: [],
  };
  tasks = [current];
  mocks.api.mockReset();
  mocks.refresh.mockReset();
  mocks.refresh.mockResolvedValue(undefined);
  mocks.api.mockImplementation(
    async (path: string, _schema: unknown, options?: RequestInit): Promise<unknown> => {
      if (path === failPath) throw new Error('测试请求失败');
      if (path === '/auth/me') {
        if (!authenticated) throw new Error('请先登录');
        return { id: 1 };
      }
      if (path === '/auth/login' || path === '/auth/register') {
        const computedStyle = window.getComputedStyle.bind(window);
        vi.spyOn(window, 'getComputedStyle').mockImplementation((element) =>
          computedStyle(element)
        );
        authenticated = true;
        return { id: 1 };
      }
      if (path === '/auth/logout') return { ok: true };
      if (path === '/documents/samples') {
        documents = [
          ...documents,
          {
            id: 3,
            filename: '样例.html',
            status: 'READY',
            chunk_count: 1,
            storage_scope: 'LIBRARY',
          },
        ];
        return documents;
      }
      if (path === '/documents' && options?.method === 'POST') {
        const form = options.body;
        if (form instanceof FormData && form.has('scope')) {
          const item = {
            id: 21 + attachmentRows.length,
            filename: '附件.txt',
            status: 'INDEXING',
            chunk_count: 0,
            storage_scope: form.get('scope') === 'TASK' ? 'TASK' : 'LIBRARY',
          } satisfies Document;
          attachmentRows.push(item);
          return item;
        }
        return documents[0];
      }
      if (path.startsWith('/documents/')) {
        if (options?.method === 'DELETE') return { ok: true };
        const item = attachmentRows.find((item) => '/documents/' + item.id === path);
        if (item) return { ...item, status: 'READY', chunk_count: 1 };
      }
      if (path === '/documents') return documents;
      if (path === '/sessions' && options?.method === 'POST') return { id: 2 };
      if (path === '/sessions') return [{ id: 1, title: '我的会话' }];
      if (path === '/tasks' && options?.method === 'POST') {
        tasks = [current];
        return current;
      }
      if (path.startsWith('/tasks?page=')) return tasks;
      if (path.endsWith('/cancel')) {
        current = { ...current, status: 'CANCELLED' };
        return { ok: true };
      }
      if (path.endsWith('/reviews')) {
        current = {
          ...current,
          version: 1,
          review_status: 'CONFIRMED',
          reviews: [{ id: 1, decision: 'CONFIRMED', note: '已核对原文', created_at: '2026-09-03' }],
        };
        return current;
      }
      if (path === '/tasks/1') return current;
      throw new Error('Unexpected path: ' + path);
    }
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
describe('research workspace', () => {
  it('offers login, registration, reports failure, and signs in', async () => {
    authenticated = false;
    const user = userEvent.setup();
    mount();
    await screen.findByText('欢迎回来');
    await user.type(screen.getByLabelText('密码'), 'password123');
    failPath = '/auth/login';
    await user.type(screen.getByLabelText('密码'), '{Enter}');
    await screen.findByText('测试请求失败');
    failPath = '';
    await user.click(screen.getByText('没有账号？创建账号'));
    await screen.findByText('创建研究账号');
    await user.clear(screen.getByLabelText('账号'));
    await user.type(screen.getByLabelText('账号'), 'tester');
    await user.click(screen.getByText('已有账号，返回登录'));
    await user.click(screen.getByText('没有账号？创建账号'));
    await user.click(screen.getByRole('button', { name: /注册并进入工作台/ }));
    await screen.findByText('金融文档核查与证据追溯');
    expect(mocks.api).toHaveBeenCalledWith('/auth/register', expect.anything(), expect.anything());
  });
  it('submits with a new session and renders agents, citations and source', async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByRole('checkbox', { name: '年报.pdf' }));
    await user.type(screen.getByLabelText('核查问题'), '核查收入');
    await user.click(screen.getByRole('button', { name: /开始核查/ }));
    await screen.findByText('核查报告');
    expect(screen.getByText('主 Agent')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /search 已完成/ }));
    await screen.findByText('找到收入');
    await user.click(screen.getByRole('button', { name: /read/ }));
    await screen.findByText('等待工具返回');
    await user.click(screen.getByRole('button', { name: '证据 1 ↗' }));
    expect(screen.getByText('打开原始文档 ↗').getAttribute('href')).toBe(
      '/api/documents/1/source#page=7'
    );
    await user.click(screen.getByText('← 全部证据'));
    await user.click(screen.getByRole('button', { name: /01 年报.pdf/ }));
    await screen.findByText('打开原始文档 ↗');
    await user.click(screen.getByRole('button', { name: /新建核查/ }));
    await screen.findByText('分析，从一个好问题开始');
  });
  it('loads history, saves review atomically and logs out', async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByRole('button', { name: /历史与审阅/ }));
    await screen.findByText('保留每一次核查的上下文');
    await user.click(screen.getByRole('button', { name: /核查收入.*任务/ }));
    await screen.findByText('核查报告');
    await user.click(screen.getByRole('button', { name: '人工审阅' }));
    await user.type(screen.getByLabelText('审阅意见'), '已核对原文');
    await user.click(screen.getByRole('button', { name: '保存审阅' }));
    await screen.findByText('已核对原文', { selector: 'span' });
    await user.click(screen.getByRole('button', { name: '人工审阅' }));
    await user.click(screen.getByRole('button', { name: 'Cancel' }));
    await user.click(screen.getByRole('button', { name: /退出登录/ }));
    await screen.findByText('欢迎回来');
  });
  it('opens documents, imports samples and uploads a file', async () => {
    const user = userEvent.setup();
    const rendered = mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByRole('button', { name: /文档资料库/ }));
    await screen.findByText('先建立你的证据来源');
    await user.click(screen.getByRole('button', { name: '导入真实样例' }));
    await screen.findByText('样例.html');
    const upload = rendered.container.querySelector('input[type=file]');
    if (!(upload instanceof HTMLInputElement)) throw new Error('Upload input missing');
    await user.upload(upload, new File(['收入100万元'], 'upload.txt', { type: 'text/plain' }));
    await screen.findByText('文档已上传，正在构建检索索引');
    expect(mocks.api).toHaveBeenCalledWith(
      '/documents',
      expect.anything(),
      expect.objectContaining({ body: expect.any(FormData) })
    );
  });
  it('handles an empty workspace and routes to upload', async () => {
    const user = userEvent.setup();
    documents = [];
    tasks = [];
    mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByText('前往上传 →'));
    await screen.findByText('还没有文档，上传资料或导入真实样例');
    await user.click(screen.getByRole('button', { name: /历史与审阅/ }));
    await screen.findByText('暂无核查记录');
    await user.click(screen.getByRole('button', { name: /核查工作台/ }));
    expect(screen.getByRole('button', { name: /开始核查/ }).hasAttribute('disabled')).toBe(true);
  });
  it('shows progress, SSE reconnect, cancels and rejects late updates', async () => {
    const user = userEvent.setup();
    current = {
      ...current,
      status: 'RUNNING',
      result: null,
      error: '上一次工具返回错误',
      evidence: [],
      tools: [],
      agents: [],
    };
    tasks = [current];
    mount();
    await screen.findByText('定义核查问题');
    await user.click(await screen.findByRole('button', { name: /#1.*核查收入/ }));
    await screen.findByText('取消任务');
    await waitFor(() => expect(FakeEvents.instances.length).toBe(1));
    await act(async () => {
      FakeEvents.instances[0]?.onerror?.();
    });
    await screen.findByText('连接中断，正在重连');
    await act(async () => {
      FakeEvents.instances[0]?.onmessage?.();
    });
    await user.click(screen.getByRole('button', { name: '取消任务' }));
    await waitFor(() => expect(screen.queryByText('取消任务')).toBeNull());
    await act(async () => {
      FakeEvents.instances[0]?.onmessage?.();
    });
    await waitFor(() => expect(FakeEvents.instances[0]?.close).toHaveBeenCalled());
  });
  it('supports selecting an existing session and submission failures', async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByRole('checkbox', { name: '年报.pdf' }));
    await user.type(screen.getByLabelText('核查问题'), '核查收入');
    fireEvent.mouseDown(screen.getByRole('combobox', { name: '选择会话' }));
    await user.click(await screen.findByText('我的会话'));
    failPath = '/tasks';
    await user.click(screen.getByRole('button', { name: /开始核查/ }));
    await screen.findByText('测试请求失败');
    expect(
      mocks.api.mock.calls.some(
        (call) => call[0] === '/sessions' && (call[2] as RequestInit | undefined)?.method === 'POST'
      )
    ).toBe(false);
  });
  it('paginates stored history', async () => {
    const user = userEvent.setup();
    tasks = Array.from({ length: 30 }, (_, index) => ({ ...current, id: index + 1 }));
    mount();
    await screen.findByText('定义核查问题');
    await user.click(screen.getByRole('button', { name: /历史与审阅/ }));
    await user.click(screen.getByRole('button', { name: '下一页' }));
    await screen.findByText('第 2 页');
    await user.click(screen.getByRole('button', { name: '上一页' }));
    await screen.findByText('第 1 页');
  });
  it('submits a workbench attachment without library documents and clears single-task selection', async () => {
    const user = userEvent.setup();
    documents = [];
    mount();
    await screen.findByText('定义核查问题');
    await user.upload(screen.getByLabelText('选择附件'), new File(['收入 100 万元'], '附件.txt'));
    await user.click(screen.getByRole('button', { name: '仅本次任务使用' }));
    await screen.findByText('仅本次任务 · 索引中');
    await user.type(screen.getByLabelText('核查问题'), '核查本次附件');
    await waitFor(
      () =>
        expect(screen.getByRole('button', { name: /开始核查/ }).hasAttribute('disabled')).toBe(
          false
        ),
      { timeout: 5000 }
    );
    await user.click(screen.getByRole('button', { name: /开始核查/ }));
    await screen.findByText('核查报告');
    const request = mocks.api.mock.calls.find(
      (call) => call[0] === '/tasks' && (call[2] as RequestInit | undefined)?.method === 'POST'
    );
    expect(request?.[2]).toEqual(
      expect.objectContaining({ body: expect.stringContaining('"document_ids":[21]') })
    );
    expect(screen.queryByText('仅本次任务 · 可检索')).toBeNull();
    expect(screen.getByRole('button', { name: /开始核查/ }).hasAttribute('disabled')).toBe(true);
  });
  it('discards unsubmitted attachments on new task and retains input if discard fails', async () => {
    const user = userEvent.setup();
    mount();
    await screen.findByText('定义核查问题');
    await user.upload(screen.getByLabelText('选择附件'), new File(['收入'], '附件.txt'));
    await user.click(screen.getByRole('button', { name: '仅本次任务使用' }));
    await screen.findByText('仅本次任务 · 索引中');
    failPath = '/documents/21';
    await user.click(screen.getByRole('button', { name: /新建核查/ }));
    await screen.findByText('测试请求失败');
    expect(screen.getByRole('button', { name: '移除 附件.txt' })).toBeTruthy();
    failPath = '';
    await user.click(screen.getByRole('button', { name: /新建核查/ }));
    await waitFor(() => expect(screen.queryByRole('button', { name: '移除 附件.txt' })).toBeNull());
  });
});
