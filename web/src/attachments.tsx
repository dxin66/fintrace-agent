import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Button, Modal, Tag } from 'antd';
import { PaperClipOutlined, CloseOutlined } from '@ant-design/icons';
import { z } from 'zod';
import { api } from './api';
import { documentSchema, statusLabel, type Document } from './domain';

export const attachmentAccept = '.pdf,.html,.htm,.txt,.png,.jpg,.jpeg';

export function useAttachments(notify: (error: unknown) => void, reload: () => Promise<void>) {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [pending, setPending] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  useEffect(() => {
    const indexing = documents.filter((doc) => doc.status === 'INDEXING');
    if (indexing.length === 0) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      void Promise.all(
        indexing.map((doc) =>
          api(`/documents/${doc.id}`, documentSchema, { signal: controller.signal })
        )
      )
        .then((updated) => {
          if (controller.signal.aborted) return;
          setDocuments((current) =>
            current.map((doc) => updated.find((next) => next.id === doc.id) ?? doc)
          );
        })
        .catch((error: unknown) => {
          if (!controller.signal.aborted) notify(error);
        });
    }, 1500);
    return () => {
      controller.abort();
      window.clearInterval(timer);
    };
  }, [documents, notify]);

  function choose(files: File[]): void {
    if (uploading) return;
    if (documents.length + files.length > 20) {
      notify(new Error('每次任务最多添加 20 份资料'));
      return;
    }
    const valid = files.filter((file) => {
      if (
        !/\.(pdf|html?|txt|png|jpe?g)$/i.test(file.name) ||
        file.size === 0 ||
        file.size > 35 * 1024 * 1024
      ) {
        notify(new Error(`${file.name}：请选择非空的 PDF、HTML、TXT、PNG 或 JPG（≤35 MB）`));
        return false;
      }
      return true;
    });
    setPending(valid);
  }

  async function upload(scope: 'TASK' | 'LIBRARY'): Promise<void> {
    setUploading(true);
    const failed: File[] = [];
    try {
      for (const file of pending) {
        try {
          const body = new FormData();
          body.append('file', file);
          body.append('scope', scope);
          const doc = await api('/documents', documentSchema, { method: 'POST', body });
          setDocuments((current) => [...current, doc]);
        } catch (error) {
          failed.push(file);
          notify(error);
        }
      }
      setPending(failed);
      await reload();
    } catch (error) {
      notify(error);
    } finally {
      setUploading(false);
    }
  }

  async function remove(doc: Document): Promise<void> {
    if (doc.storage_scope === 'TASK') {
      await api(`/documents/${doc.id}`, z.object({ ok: z.boolean() }), { method: 'DELETE' });
    }
    setDocuments((current) => current.filter((item) => item.id !== doc.id));
  }

  async function clear(): Promise<void> {
    await Promise.all(documents.map(remove));
    setPending([]);
  }

  return {
    documents,
    pending,
    uploading,
    choose,
    upload,
    remove,
    clear,
    cancel: () => setPending([]),
    consumed: () => setDocuments([]),
    blocked: uploading || pending.length > 0 || documents.some((doc) => doc.status !== 'READY'),
  };
}

type Attachments = ReturnType<typeof useAttachments>;

export function AttachmentInput({
  attachments,
  disabled,
  notify,
  children,
}: {
  attachments: Attachments;
  disabled: boolean;
  notify: (error: unknown) => void;
  children: ReactNode;
}): React.JSX.Element {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  return (
    <div
      className={`attachment-input ${dragging ? 'dragging' : ''}`}
      aria-label="聊天框附件区"
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={(event) => {
        if (
          !event.currentTarget.contains(
            event.relatedTarget instanceof Node ? event.relatedTarget : null
          )
        )
          setDragging(false);
      }}
      onDrop={(event) => {
        event.preventDefault();
        setDragging(false);
        if (!disabled) attachments.choose(Array.from(event.dataTransfer.files));
      }}
    >
      {children}
      {attachments.documents.length > 0 && (
        <div className="attachment-list">
          {attachments.documents.map((doc) => (
            <div className="attachment-item" key={doc.id}>
              <div className="grow">
                <strong>{doc.filename}</strong>
                <small>
                  {doc.storage_scope === 'LIBRARY' ? '已存入资料库' : '仅本次任务'} ·{' '}
                  {statusLabel(doc.status)}
                </small>
                {doc.error && <p className="error-text">{doc.error}</p>}
              </div>
              <Button
                type="text"
                size="small"
                disabled={disabled}
                aria-label={`移除 ${doc.filename}`}
                icon={<CloseOutlined />}
                onClick={() => {
                  void attachments.remove(doc).catch(notify);
                }}
              />
            </div>
          ))}
        </div>
      )}
      <div className="attachment-actions">
        <input
          ref={input}
          type="file"
          hidden
          multiple
          accept={attachmentAccept}
          aria-label="选择附件"
          disabled={disabled}
          onChange={(event) => {
            attachments.choose(Array.from(event.target.files ?? []));
            event.target.value = '';
          }}
        />
        <Button
          icon={<PaperClipOutlined />}
          disabled={disabled}
          loading={attachments.uploading}
          onClick={() => input.current?.click()}
        >
          上传文件 / 图片
        </Button>
        <span>或拖入聊天框 · PDF / HTML / TXT / PNG / JPG · ≤35 MB</span>
      </div>
      <p className="attachment-note">
        图片按文字识别参与检索，数字请核对原图。仅本次任务的附件不进入资料库，随任务保留用于历史追溯。
      </p>
    </div>
  );
}

export function AttachmentChoice({ attachments }: { attachments: Attachments }): React.JSX.Element {
  return (
    <Modal
      title="是否将这些资料存入文档资料库？"
      open={attachments.pending.length > 0}
      closable={!attachments.uploading}
      maskClosable={false}
      keyboard={!attachments.uploading}
      onCancel={attachments.cancel}
      footer={
        <>
          <Button disabled={attachments.uploading} onClick={attachments.cancel}>
            取消上传
          </Button>
          <Button
            disabled={attachments.uploading}
            onClick={() => {
              void attachments.upload('LIBRARY');
            }}
          >
            存入资料库并使用
          </Button>
          <Button
            type="primary"
            loading={attachments.uploading}
            onClick={() => {
              void attachments.upload('TASK');
            }}
          >
            仅本次任务使用
          </Button>
        </>
      }
    >
      <div className="pending-files">
        {attachments.pending.map((file, index) => (
          <Tag key={`${index}-${file.name}`}>{file.name}</Tag>
        ))}
      </div>
      <p>存入资料库：本次可用，后续也可选择复用。</p>
      <p>
        仅本次任务：只能用于这一次核查，不会被后续任务检索。原文件与引用片段随任务保存，供历史追溯。
      </p>
      {attachments.uploading && <p>正在上传；完成后将自动识别文字并建立索引，请稍候。</p>}
    </Modal>
  );
}
