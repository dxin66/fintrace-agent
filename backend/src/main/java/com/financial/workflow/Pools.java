package com.financial.workflow;

import jakarta.annotation.PreDestroy;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import java.util.function.Supplier;
import org.springframework.stereotype.Component;

@Component
public class Pools {

  public final ThreadPoolExecutor tasks = pool("task", 2, 16),
    children = pool("child", 4, 8),
    models = pool("model", 6, 12),
    tools = pool("tool", 8, 32),
    index = pool("index", 2, 8);
  public final ScheduledExecutorService events =
    Executors.newScheduledThreadPool(2);

  static ThreadPoolExecutor pool(String name, int size, int queue) {
    AtomicInteger sequence = new AtomicInteger();
    return new ThreadPoolExecutor(
      size,
      size,
      0,
      TimeUnit.SECONDS,
      new ArrayBlockingQueue<>(queue),
      r ->
        new Thread(r, "financial-" + name + "-" + sequence.incrementAndGet()),
      new ThreadPoolExecutor.AbortPolicy()
    );
  }

  public static class Control {

    final long deadline = System.nanoTime() + TimeUnit.MINUTES.toNanos(10);
    final AtomicBoolean cancelled = new AtomicBoolean();
    final Set<Future<?>> pending = ConcurrentHashMap.newKeySet();
    final Semaphore childSlots = new Semaphore(2);

    public void check() {
      if (
        cancelled.get() || Thread.currentThread().isInterrupted()
      ) throw new CancellationException("任务已取消");
      if (System.nanoTime() > deadline) throw new CompletionException(
        new TimeoutException("任务超过 10 分钟限制")
      );
    }

    void track(Future<?> future) {
      pending.add(future);
      if (cancelled.get()) future.cancel(true);
    }

    public void cancel() {
      cancelled.set(true);
      pending.forEach(f -> f.cancel(true));
    }
  }

  public static <T> CompletableFuture<T> async(
    Executor executor,
    Control control,
    Supplier<T> operation
  ) {
    control.check();
    CompletableFuture<T> result = new CompletableFuture<>();
    FutureTask<T> work = new FutureTask<>(() -> {
      control.check();
      return operation.get();
    }) {
      @Override
      protected void done() {
        if (executor instanceof ThreadPoolExecutor pool) pool.remove(this);
        control.pending.remove(this);
        try {
          result.complete(get());
        } catch (CancellationException e) {
          result.cancel(false);
        } catch (Exception e) {
          result.completeExceptionally(e.getCause() == null ? e : e.getCause());
        }
      }
    };
    control.track(work);
    try {
      executor.execute(work);
    } catch (RejectedExecutionException e) {
      work.cancel(false);
      throw e;
    }
    return result;
  }

  @PreDestroy
  public void close() {
    List.of(tasks, children, models, tools, index).forEach(
      ExecutorService::shutdownNow
    );
    events.shutdownNow();
  }
}
