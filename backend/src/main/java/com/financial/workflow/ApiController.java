package com.financial.workflow;

import jakarta.validation.Valid;
import jakarta.validation.constraints.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping("/api")
public class ApiController {

  final DataMapper db;
  final DocumentService documents;
  final TaskService tasks;
  final Pools pools;

  public ApiController(
    DataMapper db,
    DocumentService documents,
    TaskService tasks,
    Pools pools
  ) {
    this.db = db;
    this.documents = documents;
    this.tasks = tasks;
    this.pools = pools;
  }

  @GetMapping("/health")
  public Map<String, String> health() {
    return Map.of("status", "UP");
  }

  @GetMapping("/documents")
  public Object documents(Authentication a) {
    return db.documents(AuthController.owner(a));
  }

  @PostMapping("/documents")
  public Object upload(
    Authentication a,
    @RequestParam("file") MultipartFile file,
    @RequestParam(defaultValue = "LIBRARY") DocumentService.Scope scope
  ) throws Exception {
    return documents.upload(AuthController.owner(a), file, scope);
  }

  @GetMapping("/documents/{id}")
  public Object document(Authentication a, @PathVariable long id) {
    return documents.publicDocument(documents.get(AuthController.owner(a), id));
  }

  @DeleteMapping("/documents/{id}")
  public Object discard(Authentication a, @PathVariable long id)
    throws Exception {
    documents.discard(AuthController.owner(a), id);
    return Map.of("ok", true);
  }

  @PostMapping("/documents/samples")
  public Object samples(Authentication a) throws Exception {
    return documents.samples(AuthController.owner(a));
  }

  @GetMapping("/documents/{id}/source")
  public Object source(Authentication a, @PathVariable long id)
    throws Exception {
    return documents.source(AuthController.owner(a), id);
  }

  record SessionInput(@NotBlank @Size(max = 100) String title) {}

  @PostMapping("/sessions")
  public Object session(
    Authentication a,
    @Valid @RequestBody SessionInput input
  ) {
    var row = new HashMap<String, Object>();
    row.put("owner_id", AuthController.owner(a));
    row.put("title", input.title());
    db.insertSession(row);
    return row;
  }

  @GetMapping("/sessions")
  public Object sessions(Authentication a) {
    return db.sessions(AuthController.owner(a));
  }

  record TaskInput(
    @Positive long session_id,
    @NotEmpty @Size(max = 20) List<@Positive Long> document_ids,
    @NotBlank @Size(max = 4000) String instruction,
    @NotBlank @Size(max = 80) String idempotency_key
  ) {}

  @PostMapping("/tasks")
  public Object submit(Authentication a, @Valid @RequestBody TaskInput input) {
    return tasks.submit(
      AuthController.owner(a),
      input.session_id(),
      input.document_ids(),
      input.instruction(),
      input.idempotency_key()
    );
  }

  @GetMapping("/tasks")
  public Object list(
    Authentication a,
    @RequestParam(defaultValue = "0") int page
  ) {
    if (page < 0 || page > 10000) throw Support.bad("分页参数错误");
    return db.tasks(AuthController.owner(a), page * 30);
  }

  @GetMapping("/tasks/{id}")
  public Object detail(Authentication a, @PathVariable long id) {
    return tasks.detail(AuthController.owner(a), id);
  }

  @PostMapping("/tasks/{id}/cancel")
  public Object cancel(Authentication a, @PathVariable long id) {
    tasks.cancel(AuthController.owner(a), id);
    return Map.of("ok", true);
  }

  record ReviewInput(
    @Min(0) int version,
    @Pattern(regexp = "CONFIRMED|CORRECTED") @NotNull String decision,
    @NotBlank @Size(max = 4000) String note
  ) {}

  @PostMapping("/tasks/{id}/reviews")
  public Object review(
    Authentication a,
    @PathVariable long id,
    @Valid @RequestBody ReviewInput input
  ) {
    tasks.review(
      AuthController.owner(a),
      id,
      input.version(),
      input.decision(),
      input.note()
    );
    return tasks.detail(AuthController.owner(a), id);
  }

  @GetMapping("/tasks/{id}/reviews")
  public Object reviews(Authentication a, @PathVariable long id) {
    Support.require(db.task(id, AuthController.owner(a)));
    return db.reviews(id);
  }

  @GetMapping(value = "/tasks/{id}/events", produces = "text/event-stream")
  public SseEmitter events(
    Authentication a,
    @PathVariable long id,
    @RequestParam(defaultValue = "0") long after,
    @RequestHeader(value = "Last-Event-ID", required = false) String last
  ) {
    long owner = AuthController.owner(a);
    Support.require(db.task(id, owner));
    long cursor = after;
    if (last != null) {
      try {
        cursor = Math.max(cursor, Long.parseLong(last));
      } catch (NumberFormatException e) {
        throw Support.bad("事件序号无效");
      }
    }
    if (cursor < 0) throw Support.bad("事件序号无效");
    var emitter = new SseEmitter(900000L);
    var sequence = new AtomicLong(cursor);
    var future = new AtomicReference<ScheduledFuture<?>>();
    var closed = new AtomicBoolean();
    Runnable cleanup = () -> {
      closed.set(true);
      var f = future.get();
      if (f != null) f.cancel(false);
    };
    emitter.onCompletion(cleanup);
    emitter.onTimeout(cleanup);
    emitter.onError(e -> cleanup.run());
    var scheduled = pools.events.scheduleWithFixedDelay(
      () -> {
        try {
          var batch = db.events(id, sequence.get());
          for (var event : batch) {
            long eventId = Support.id(event);
            emitter.send(
              SseEmitter.event().id(Long.toString(eventId)).data(event)
            );
            sequence.set(eventId);
          }
          var task = Support.require(db.task(id, owner));
          if (
            batch.size() < 200 &&
            Set.of("SUCCEEDED", "FAILED", "CANCELLED").contains(
              task.get("status").toString()
            )
          ) {
            emitter.complete();
            cleanup.run();
          }
        } catch (Exception e) {
          emitter.completeWithError(e);
          cleanup.run();
        }
      },
      0,
      600,
      TimeUnit.MILLISECONDS
    );
    future.set(scheduled);
    if (closed.get()) scheduled.cancel(false);
    return emitter;
  }
}
