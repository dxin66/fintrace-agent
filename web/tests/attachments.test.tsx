import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { ConfigProvider } from 'antd';
import { AttachmentChoice, AttachmentInput, useAttachments } from '../src/attachments';
import type { Document } from '../src/domain';

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock('../src/api', () => ({ api: mocks.api }));
const notify = vi.fn();
const reload = vi.fn<() => Promise<void>>();
const file = new File(['收入 100 万元'], '收入.txt', { type: 'text/plain' });
const doc: Document = {
  id: 21,
  filename: file.name,
  status: 'READY',
  chunk_count: 1,
  storage_scope: 'TASK',
};

beforeEach(() => {
  notify.mockReset();
  reload.mockReset();
  reload.mockResolvedValue(undefined);
  mocks.api.mockReset();
  mocks.api.mockResolvedValue(doc);
  vi.stubGlobal(
    'matchMedia',
    vi
      .fn()
      .mockImplementation(() => ({ matches: false, addListener: vi.fn(), removeListener: vi.fn() }))
  );
  const original = window.getComputedStyle.bind(window);
  vi.spyOn(window, 'getComputedStyle').mockImplementation((element) => original(element));
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function Harness({ disabled = false }: { disabled?: boolean }): React.JSX.Element {
  const attachments = useAttachments(notify, reload);
  return (
    <ConfigProvider theme={{ token: { motion: false } }}>
      <AttachmentInput attachments={attachments} disabled={disabled} notify={notify}>
        <textarea aria-label="问题" />
      </AttachmentInput>
      <AttachmentChoice attachments={attachments} />
      <span>{attachments.blocked ? '等待索引' : '可以提交'}</span>
    </ConfigProvider>
  );
}

describe('single-task attachments', () => {
  it('asks before upload, uploads TASK scope, and removes the private file', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: /上传文件/ }));
    await user.upload(screen.getByLabelText('选择附件'), file);
    await screen.findByText('是否将这些资料存入文档资料库？');
    expect(mocks.api).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: '仅本次任务使用' }));
    await screen.findByText('仅本次任务 · 可检索');
    const options: unknown = mocks.api.mock.calls[0]?.[2];
    expect(options).toEqual(expect.objectContaining({ body: expect.any(FormData) }));
    if (
      typeof options !== 'object' ||
      options === null ||
      !('body' in options) ||
      !(options.body instanceof FormData)
    )
      throw new Error('Expected multipart body');
    expect(options.body.get('scope')).toBe('TASK');
    mocks.api.mockResolvedValue({ ok: true });
    await user.click(screen.getByRole('button', { name: `移除 ${file.name}` }));
    await waitFor(() => expect(screen.queryByText('仅本次任务 · 可检索')).toBeNull());
    expect(mocks.api).toHaveBeenLastCalledWith('/documents/21', expect.anything(), {
      method: 'DELETE',
    });
  });

  it('accepts drag/drop, allows choosing library storage, and removes only the attachment selection', async () => {
    mocks.api.mockResolvedValue({ ...doc, storage_scope: 'LIBRARY' });
    const user = userEvent.setup();
    render(<Harness />);
    const zone = screen.getByLabelText('聊天框附件区');
    fireEvent.dragOver(zone);
    expect(zone.className).toContain('dragging');
    const leaveInside = new Event('dragleave', { bubbles: true });
    Object.defineProperty(leaveInside, 'relatedTarget', { value: screen.getByLabelText('问题') });
    fireEvent(zone, leaveInside);
    expect(zone.className).toContain('dragging');
    fireEvent.dragLeave(zone);
    expect(zone.className).not.toContain('dragging');
    fireEvent.drop(zone, { dataTransfer: { files: [file] } });
    await user.click(screen.getByRole('button', { name: '存入资料库并使用' }));
    await screen.findByText('已存入资料库 · 可检索');
    await user.click(screen.getByRole('button', { name: `移除 ${file.name}` }));
    expect(mocks.api).toHaveBeenCalledTimes(1);
  });

  it('cancels either way before sending bytes, and ignores dropped files while disabled', async () => {
    const user = userEvent.setup();
    const view = render(<Harness />);
    await user.upload(screen.getByLabelText('选择附件'), file);
    await user.click(screen.getByRole('button', { name: '取消上传' }));
    await user.upload(screen.getByLabelText('选择附件'), file);
    await user.click(screen.getByRole('button', { name: 'Close' }));
    view.rerender(<Harness disabled />);
    fireEvent.dragOver(screen.getByLabelText('聊天框附件区'));
    fireEvent.drop(screen.getByLabelText('聊天框附件区'), { dataTransfer: { files: [file] } });
    expect(mocks.api).not.toHaveBeenCalled();
  });

  it('validates type, empty file, size, and document count without an upload', () => {
    const { result } = renderHook(() => useAttachments(notify, reload));
    const big = new File(['x'], 'large.pdf');
    Object.defineProperty(big, 'size', { value: 36 * 1024 * 1024 });
    act(() =>
      result.current.choose([new File(['x'], 'script.exe'), new File([], 'empty.txt'), big])
    );
    expect(notify).toHaveBeenCalledTimes(3);
    act(() => result.current.choose(Array.from({ length: 21 }, () => file)));
    expect(notify).toHaveBeenLastCalledWith(
      expect.objectContaining({ message: '每次任务最多添加 20 份资料' })
    );
    expect(result.current.pending).toEqual([]);
  });

  it('keeps failed uploads selected, supports retry and reports library refresh failures', async () => {
    const { result } = renderHook(() => useAttachments(notify, reload));
    mocks.api.mockRejectedValueOnce(new Error('上传中断')).mockResolvedValue(doc);
    act(() => result.current.choose([file, new File(['x'], 'b.txt')]));
    await act(() => result.current.upload('TASK'));
    expect(result.current.pending).toEqual([file]);
    expect(result.current.documents).toHaveLength(1);
    reload.mockRejectedValueOnce(new Error('刷新失败'));
    await act(() => result.current.upload('LIBRARY'));
    expect(notify).toHaveBeenLastCalledWith(expect.objectContaining({ message: '刷新失败' }));
    expect(result.current.uploading).toBe(false);
  });

  it('polls until READY, retains other attachments, and disables a failed indexed document', async () => {
    vi.useFakeTimers();
    mocks.api
      .mockResolvedValueOnce({ ...doc, status: 'INDEXING' })
      .mockResolvedValueOnce({ ...doc, id: 22, storage_scope: 'LIBRARY' });
    const { result } = renderHook(() => useAttachments(notify, reload));
    act(() => result.current.choose([file, file]));
    await act(() => result.current.upload('TASK'));
    expect(result.current.blocked).toBe(true);
    mocks.api.mockRejectedValueOnce(new Error('索引查询失败'));
    await act(() => vi.advanceTimersByTimeAsync(1500));
    expect(notify).toHaveBeenCalledWith(expect.objectContaining({ message: '索引查询失败' }));
    mocks.api.mockResolvedValue(doc);
    await act(() => vi.advanceTimersByTimeAsync(1500));
    expect(result.current.blocked).toBe(false);
    expect(result.current.documents).toHaveLength(2);
    await act(() => result.current.clear());
    expect(result.current.documents).toEqual([]);
    act(() => result.current.choose([file]));
    mocks.api.mockResolvedValue({ ...doc, status: 'FAILED', error: '图片没有文字' });
    await act(() => result.current.upload('TASK'));
    expect(result.current.blocked).toBe(true);
    act(() => result.current.consumed());
    expect(result.current.documents).toEqual([]);
  });

  it('does not accept a second selection while uploading and displays upload progress', async () => {
    let finish: ((value: Document) => void) | undefined;
    mocks.api.mockImplementation(
      () =>
        new Promise<Document>((resolve) => {
          finish = resolve;
        })
    );
    const { result } = renderHook(() => useAttachments(notify, reload));
    act(() => result.current.choose([file]));
    let uploading: Promise<void> | undefined;
    act(() => {
      uploading = result.current.upload('TASK');
    });
    act(() => result.current.choose([new File(['x'], 'ignored.txt')]));
    expect(result.current.pending).toEqual([file]);
    const view = render(
      <ConfigProvider theme={{ token: { motion: false } }}>
        <AttachmentChoice attachments={result.current} />
      </ConfigProvider>
    );
    expect(screen.getByText(/正在上传；/)).toBeTruthy();
    await act(async () => {
      finish?.(doc);
      await uploading;
    });
    view.unmount();
  });

  it('shows indexing failures and surfaces failed deletion', async () => {
    const user = userEvent.setup();
    mocks.api.mockResolvedValue({ ...doc, status: 'FAILED', error: '图片没有文字' });
    render(<Harness />);
    await user.upload(screen.getByLabelText('选择附件'), file);
    await user.click(screen.getByRole('button', { name: '仅本次任务使用' }));
    await screen.findByText('图片没有文字');
    mocks.api.mockRejectedValue(new Error('删除失败'));
    await user.click(screen.getByRole('button', { name: `移除 ${file.name}` }));
    await waitFor(() =>
      expect(notify).toHaveBeenCalledWith(expect.objectContaining({ message: '删除失败' }))
    );
    expect(screen.getByText('图片没有文字')).toBeTruthy();
  });
});
