package com.financial.workflow;

import jakarta.annotation.PostConstruct;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class TaskService {

  final org.springframework.transaction.support.TransactionTemplate transaction;
  final DataMapper db;
  final AgentEngine engine;
  final Pools pools;
  final BCryptPasswordEncoder encoder;
  final ConcurrentMap<Long, Pools.Control> active = new ConcurrentHashMap<>();

  public TaskService(
    DataMapper db,
    AgentEngine engine,
    Pools pools,
    BCryptPasswordEncoder encoder,
    org.springframework.transaction.PlatformTransactionManager manager
  ) {
    this.transaction =
      new org.springframework.transaction.support.TransactionTemplate(manager);
    this.db = db;
    this.engine = engine;
    this.pools = pools;
    this.encoder = encoder;
  }

  @PostConstruct
  public void recover() {
    db.interruptTasks();
    db.interruptRuns();
    db.interruptTools();
    db.interruptDocuments();
    if (db.user("demo") == null) {
      var row = new HashMap<String, Object>();
      row.put("username", "demo");
      row.put("password_hash", encoder.encode(System.getenv("DEMO_PASSWORD")));
      db.insertUser(row);
    }
  }

  public Map<String, Object> submit(
    long owner,
    long session,
    List<Long> docs,
    String instruction,
    String key
  ) {
    Support.require(db.session(session, owner));
    docs = docs.stream().distinct().sorted().toList();
    String hash;
    try {
      hash = HexFormat.of().formatHex(
        MessageDigest.getInstance("SHA-256").digest(
          Support.json(List.of(session, docs, instruction)).getBytes(
            StandardCharsets.UTF_8
          )
        )
      );
    } catch (Exception e) {
      throw new IllegalStateException(e);
    }
    var documents = docs;
    record Submission(Map<String, Object> task, boolean created) {}
    Submission submission;
    try {
      submission = transaction.execute(tx -> {
        var prior = db.idempotent(owner, key);
        if (prior != null) return new Submission(same(prior, hash), false);
        var row = new HashMap<String, Object>();
        row.put("owner_id", owner);
        row.put("session_id", session);
        row.put("instruction", instruction);
        row.put("document_ids", Support.json(documents));
        row.put("idempotency_key", key);
        row.put("request_hash", hash);
        db.insertTask(row);
        long id = Support.id(row);
        // Claim single-task attachments in the same transaction as task creation.
        // Sorted IDs give concurrent submissions a consistent lock order.
        for (long doc : documents) {
          var document = Support.require(db.document(doc, owner));
          if (
            !"READY".equals(document.get("status"))
          ) throw new ResponseStatusException(
            HttpStatus.CONFLICT,
            "所选文档尚未完成索引或已移除"
          );
          if (
            "TASK".equals(document.get("storage_scope")) &&
            db.claimDocument(doc, owner, id) != 1
          ) throw new ResponseStatusException(
            HttpStatus.CONFLICT,
            "该附件已绑定其他任务，请重新上传"
          );
        }
        return new Submission(row, true);
      });
    } catch (DuplicateKeyException e) {
      return same(Support.require(db.idempotent(owner, key)), hash);
    }
    Objects.requireNonNull(submission);
    if (!submission.created()) return submission.task();
    long id = Support.id(submission.task());
    var control = new Pools.Control();
    active.put(id, control);
    db.event(id, "queued", Support.json(Map.of("status", "QUEUED")));
    var timeout = pools.events.schedule(
      () -> {
        if (db.transition(id, "FAILED", null, "任务超过 10 分钟限制") > 0) {
          control.cancel();
          active.remove(id);
          db.event(
            id,
            "failed",
            Support.json(Map.of("status", "FAILED", "error", "任务超时"))
          );
        }
      },
      10,
      TimeUnit.MINUTES
    );
    try {
      Pools.async(pools.tasks, control, () -> {
        try {
          if (db.startTask(id) == 0) return false;
          db.event(id, "started", Support.json(Map.of("status", "RUNNING")));
          String answer = engine.execute(
            id,
            owner,
            documents,
            instruction,
            control
          );
          control.check();
          if (db.transition(id, "SUCCEEDED", answer, null) > 0) db.event(
            id,
            "completed",
            Support.json(Map.of("status", "SUCCEEDED"))
          );
        } catch (Exception e) {
          String status = control.cancelled.get() ? "CANCELLED" : "FAILED";
          if (db.transition(id, status, null, Support.error(e)) > 0) db.event(
            id,
            "failed",
            Support.json(Map.of("status", status, "error", Support.error(e)))
          );
          control.cancel();
        } finally {
          timeout.cancel(false);
          active.remove(id);
        }
        return true;
      });
    } catch (RejectedExecutionException e) {
      timeout.cancel(false);
      active.remove(id);
      db.transition(id, "FAILED", null, "任务队列已满，未调用模型");
      // The task and its attachment binding already exist. Return their terminal
      // record so the caller consumes the selection and can inspect the failure.
      db.event(
        id,
        "failed",
        Support.json(
          Map.of("status", "FAILED", "error", "任务队列已满，未调用模型")
        )
      );
    }
    return Support.require(db.task(id, owner));
  }

  private Map<String, Object> same(Map<String, Object> row, String hash) {
    if (
      !hash.equals(row.get("request_hash"))
    ) throw new ResponseStatusException(
      HttpStatus.CONFLICT,
      "同一幂等键不能用于不同的请求内容"
    );
    return row;
  }

  public void cancel(long owner, long task) {
    Support.require(db.task(task, owner));
    if (db.transition(task, "CANCELLED", null, "用户取消") > 0) {
      var control = active.remove(task);
      if (control != null) control.cancel();
      db.event(task, "cancelled", Support.json(Map.of("status", "CANCELLED")));
    }
  }

  @Transactional
  public void review(
    long owner,
    long task,
    int version,
    String decision,
    String note
  ) {
    Support.require(db.task(task, owner));
    if (
      db.reviewState(task, owner, version, decision) == 0
    ) throw new ResponseStatusException(
      HttpStatus.CONFLICT,
      "任务尚未完成或审阅版本已变化，请刷新后重试"
    );
    db.insertReview(task, owner, decision, note);
  }

  public Map<String, Object> detail(long owner, long id) {
    var result = new HashMap<>(Support.require(db.task(id, owner)));
    result.put("agents", db.runs(id));
    result.put("tools", db.tools(id));
    result.put(
      "evidence",
      db
        .evidenceList(id)
        .stream()
        .map(e -> Support.node(e.get("payload").toString()))
        .toList()
    );
    result.put("reviews", db.reviews(id));
    return result;
  }
}
