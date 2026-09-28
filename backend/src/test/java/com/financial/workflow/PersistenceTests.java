package com.financial.workflow;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import java.util.*;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.server.ResponseStatusException;

@SpringBootTest
@AutoConfigureMockMvc
class PersistenceTests {

  @Autowired
  DataMapper db;

  @Autowired
  TaskService tasks;

  @Autowired
  Pools pools;

  @Autowired
  MockMvc mvc;

  @MockitoBean
  AgentEngine engine;

  private long document, session, owner;

  @BeforeEach
  void setup() {
    owner = Support.id(db.user("demo"));
    var doc = new HashMap<String, Object>();
    doc.put("owner_id", owner);
    doc.put("storage_scope", "LIBRARY");
    doc.put("filename", "integration.txt");
    doc.put("path", "/test-only/not-served.txt");
    doc.put("mime_type", "text/plain");
    db.insertDocument(doc);
    document = Support.id(doc);
    db.indexStatus(document, "READY", 1, null);
    var s = new HashMap<String, Object>();
    s.put("owner_id", owner);
    s.put("title", "Integration");
    db.insertSession(s);
    session = Support.id(s);
    when(
      engine.execute(anyLong(), anyLong(), anyList(), anyString(), any())
    ).thenReturn("证据不足，测试模型替身");
  }

  Map<String, Object> submit() {
    return tasks.submit(
      owner,
      session,
      List.of(document),
      "核查收入",
      UUID.randomUUID().toString()
    );
  }

  long finishTask() throws Exception {
    long id = Support.id(submit());
    for (int i = 0; i < 200; i++) {
      if ("SUCCEEDED".equals(db.task(id, owner).get("status"))) return id;
      Thread.sleep(10);
    }
    throw new AssertionError("Task did not finish");
  }

  @Test
  void idempotencyCreatesOneTaskAndOneExecution() throws Exception {
    String key = UUID.randomUUID().toString();
    long first = Support.id(
      tasks.submit(owner, session, List.of(document), "核查收入", key)
    );
    long second = Support.id(
      tasks.submit(owner, session, List.of(document), "核查收入", key)
    );
    assertEquals(first, second);
    for (
      int i = 0;
      i < 200 && !"SUCCEEDED".equals(db.task(first, owner).get("status"));
      i++
    ) Thread.sleep(10);
    verify(engine, times(1)).execute(
      eq(first),
      eq(owner),
      anyList(),
      anyString(),
      any()
    );
    assertThrows(ResponseStatusException.class, () ->
      tasks.submit(owner, session, List.of(document), "不同问题", key)
    );
  }

  @Test
  void databaseUniqueConstraintRejectsDuplicateKey() {
    String key = UUID.randomUUID().toString();
    var row = new HashMap<String, Object>();
    row.put("owner_id", owner);
    row.put("session_id", session);
    row.put("instruction", "q");
    row.put("document_ids", "[" + document + "]");
    row.put("idempotency_key", key);
    row.put("request_hash", "0".repeat(64));
    db.insertTask(row);
    assertThrows(org.springframework.dao.DuplicateKeyException.class, () ->
      db.insertTask(row)
    );
  }

  @Test
  void reviewAndAuditAreAtomic() throws Exception {
    long task = finishTask();
    assertThrows(
      org.springframework.dao.DataIntegrityViolationException.class,
      () -> tasks.review(owner, task, 0, "CORRECTED", null)
    );
    assertEquals("PENDING", db.task(task, owner).get("review_status"));
    assertEquals(0, db.reviews(task).size());
  }

  @Test
  void reviewVersionConflictDoesNotOverwrite() throws Exception {
    long task = finishTask();
    String original = db.task(task, owner).get("result").toString();
    tasks.review(owner, task, 0, "CONFIRMED", "核对原文后确认");
    assertThrows(ResponseStatusException.class, () ->
      tasks.review(owner, task, 0, "CORRECTED", "过期审阅")
    );
    assertEquals(1, db.reviews(task).size());
    assertEquals(original, db.task(task, owner).get("result"));
  }

  @Test
  void crossUserDocumentTaskEvidenceAndStreamDenied() throws Exception {
    long task = finishTask();
    for (String path : List.of(
      "/api/documents/" + document + "/source",
      "/api/tasks/" + task,
      "/api/tasks/" + task + "/events",
      "/api/tasks/" + task + "/reviews"
    )) {
      mvc
        .perform(get(path).with(user("999999")))
        .andExpect(status().isNotFound());
    }
    mvc
      .perform(
        post("/api/tasks/" + task + "/reviews")
          .with(user("999999"))
          .with(csrf())
          .contentType("application/json")
          .content("{\"version\":0,\"decision\":\"CONFIRMED\",\"note\":\"x\"}")
      )
      .andExpect(status().isNotFound());
  }

  @Test
  void csrfRequiredAndAnonymousDenied() throws Exception {
    mvc
      .perform(
        post("/api/sessions")
          .with(user(Long.toString(owner)))
          .contentType("application/json")
          .content("{\"title\":\"x\"}")
      )
      .andExpect(status().isForbidden());
    mvc.perform(get("/api/documents")).andExpect(status().isUnauthorized());
  }

  @Test
  void unreadyOrUnauthorizedDocumentsRejected() {
    db.indexStatus(document, "FAILED", 0, "error");
    assertThrows(ResponseStatusException.class, () ->
      tasks.submit(owner, session, List.of(document), "q", "unready")
    );
    assertThrows(ResponseStatusException.class, () ->
      tasks.submit(owner, session, List.of(999999L), "q", "foreign")
    );
  }

  @Test
  void terminalStateCannotBeOverwritten() throws Exception {
    long task = finishTask();
    assertEquals(0, db.transition(task, "FAILED", null, "late error"));
    assertEquals("SUCCEEDED", db.task(task, owner).get("status"));
    tasks.cancel(owner, task);
    assertEquals("SUCCEEDED", db.task(task, owner).get("status"));
  }

  @Test
  void eventReplayUsesExclusiveCursor() throws Exception {
    long task = finishTask();
    db.event(task, "test", "{}");
    var events = db.events(task, 0);
    long last = Support.id(events.get(events.size() - 1));
    assertTrue(db.events(task, last).isEmpty());
    db.event(task, "next", "{}");
    assertEquals(1, db.events(task, last).size());
  }

  long attachment() {
    var doc = new HashMap<String, Object>();
    doc.put("owner_id", owner);
    doc.put("storage_scope", "TASK");
    doc.put("filename", "private-task.txt");
    doc.put("path", "/test-only/private.txt");
    doc.put("mime_type", "text/plain");
    db.insertDocument(doc);
    long id = Support.id(doc);
    db.indexStatus(id, "READY", 1, null);
    return id;
  }

  @Test
  void attachmentHiddenFromLibraryAndBoundToExactlyOneTask() {
    long id = attachment();
    assertTrue(
      db
        .documents(owner)
        .stream()
        .noneMatch(doc -> Support.id(doc) == id)
    );
    String key = UUID.randomUUID().toString();
    long task = Support.id(
      tasks.submit(owner, session, List.of(id), "仅本次", key)
    );
    assertEquals(
      task,
      ((Number) db.document(id, owner).get("task_id")).longValue()
    );
    assertEquals(
      task,
      Support.id(tasks.submit(owner, session, List.of(id), "仅本次", key))
    );
    String rejected = UUID.randomUUID().toString();
    var error = assertThrows(ResponseStatusException.class, () ->
      tasks.submit(owner, session, List.of(id), "复用", rejected)
    );
    assertEquals(409, error.getStatusCode().value());
    assertNull(db.idempotent(owner, rejected));
    assertEquals(0, db.discardDocument(id, owner));
  }

  @Test
  void concurrentSubmissionsCannotShareSingleTaskAttachment() throws Exception {
    long id = attachment();
    var start = new java.util.concurrent.CountDownLatch(1);
    try (var executor = java.util.concurrent.Executors.newFixedThreadPool(2)) {
      var results = new ArrayList<java.util.concurrent.Future<Boolean>>();
      for (int i = 0; i < 2; i++) results.add(
        executor.submit(() -> {
          start.await();
          try {
            tasks.submit(
              owner,
              session,
              List.of(id),
              "并发核查",
              UUID.randomUUID().toString()
            );
            return true;
          } catch (ResponseStatusException error) {
            assertEquals(409, error.getStatusCode().value());
            return false;
          }
        })
      );
      start.countDown();
      int successes = 0;
      for (var result : results)
        if (result.get(5, java.util.concurrent.TimeUnit.SECONDS)) successes++;
      assertEquals(1, successes);
    }
  }

  @Test
  void invalidSecondDocumentRollsBackTaskAndEarlierClaim() {
    long id = attachment();
    String key = UUID.randomUUID().toString();
    assertThrows(ResponseStatusException.class, () ->
      tasks.submit(owner, session, List.of(id, Long.MAX_VALUE), "回滚", key)
    );
    assertNull(db.document(id, owner).get("task_id"));
    assertNull(db.idempotent(owner, key));
  }

  @Test
  void removedAttachmentCannotBeIndexedBackOrSubmitted() throws Exception {
    long id = attachment();
    assertEquals(1, db.discardDocument(id, owner));
    db.indexStatus(id, "READY", 12, null);
    assertEquals("DISCARDED", db.document(id, owner).get("status"));
    assertThrows(ResponseStatusException.class, () ->
      tasks.submit(
        owner,
        session,
        List.of(id),
        "不能使用",
        UUID.randomUUID().toString()
      )
    );
    for (String path : List.of(
      "/api/documents/" + id,
      "/api/documents/" + id + "/source"
    ))
      mvc
        .perform(get(path).with(user(Long.toString(owner))))
        .andExpect(status().isNotFound());
  }

  @Test
  void attachmentMetadataAndDeletionRequireOwnerAndCsrf() throws Exception {
    long id = attachment();
    mvc
      .perform(get("/api/documents/" + id).with(user("999999")))
      .andExpect(status().isNotFound());
    mvc
      .perform(delete("/api/documents/" + id).with(user("999999")).with(csrf()))
      .andExpect(status().isNotFound());
    mvc
      .perform(delete("/api/documents/" + id).with(user(Long.toString(owner))))
      .andExpect(status().isForbidden());
    mvc
      .perform(get("/api/documents/" + id).with(user(Long.toString(owner))))
      .andExpect(status().isOk())
      .andExpect(jsonPath("$.storage_scope").value("TASK"))
      .andExpect(jsonPath("$.path").doesNotExist())
      .andExpect(jsonPath("$.owner_id").doesNotExist());
    mvc
      .perform(
        multipart("/api/documents")
          .file(
            new org.springframework.mock.web.MockMultipartFile(
              "file",
              "a.txt",
              "text/plain",
              new byte[] { 1 }
            )
          )
          .param("scope", "GLOBAL")
          .with(user(Long.toString(owner)))
          .with(csrf())
      )
      .andExpect(status().isBadRequest());
  }

  @Test
  void rejectedExecutionReturnsFailedTaskWithoutStrandingAttachment()
    throws Exception {
    var started = new java.util.concurrent.CountDownLatch(2);
    var release = new java.util.concurrent.CountDownLatch(1);
    Runnable block = () -> {
      started.countDown();
      try {
        release.await();
      } catch (InterruptedException e) {
        Thread.currentThread().interrupt();
      }
    };
    try {
      pools.tasks.execute(block);
      pools.tasks.execute(block);
      assertTrue(started.await(5, java.util.concurrent.TimeUnit.SECONDS));
      for (int i = 0; i < 16; i++) pools.tasks.execute(block);
      long attachment = attachment();
      var result = tasks.submit(
        owner,
        session,
        List.of(attachment),
        "队列验收",
        UUID.randomUUID().toString()
      );
      assertEquals("FAILED", result.get("status"));
      assertTrue(result.get("error").toString().contains("队列已满"));
      assertEquals(
        Support.id(result),
        ((Number) db.document(attachment, owner).get("task_id")).longValue()
      );
      verify(engine, never()).execute(
        eq(Support.id(result)),
        anyLong(),
        anyList(),
        anyString(),
        any()
      );
    } finally {
      release.countDown();
    }
  }

  @Test
  void uploadIndexesChosenScopeAndServesImageWithCorrectType()
    throws Exception {
    var gateway = mock(Gateway.class);
    when(gateway.rag(eq("/index"), any())).thenReturn(
      Support.node("{\"chunks\":1}")
    );
    var service = new DocumentService(db, gateway, pools);
    byte[] bytes = Base64.getDecoder().decode(
      "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg=="
    );
    var file = new org.springframework.mock.web.MockMultipartFile(
      "file",
      "statement.png",
      "image/png",
      bytes
    );
    var row = service.upload(owner, file, DocumentService.Scope.TASK);
    long id = Support.id(row);
    for (
      int i = 0;
      i < 100 && "INDEXING".equals(db.document(id, owner).get("status"));
      i++
    ) Thread.sleep(10);
    try {
      assertEquals("READY", db.document(id, owner).get("status"));
      assertEquals("TASK", row.get("storage_scope"));
      assertFalse(row.containsKey("path"));
      assertEquals(
        "image/png",
        service.source(owner, id).getHeaders().getContentType().toString()
      );
      assertThrows(ResponseStatusException.class, () ->
        service.upload(
          owner,
          new org.springframework.mock.web.MockMultipartFile(
            "file",
            "script.svg",
            "image/svg+xml",
            new byte[] { 1 }
          ),
          DocumentService.Scope.TASK
        )
      );
    } finally {
      service.discard(owner, id);
    }
  }

  @Test
  void discardingDuringIndexAlsoCleansLateResult() throws Exception {
    var gateway = mock(Gateway.class);
    var entered = new java.util.concurrent.CountDownLatch(1);
    var release = new java.util.concurrent.CountDownLatch(1);
    when(gateway.rag(eq("/index"), any())).thenAnswer(invocation -> {
      entered.countDown();
      assertTrue(release.await(5, java.util.concurrent.TimeUnit.SECONDS));
      return Support.node("{\"chunks\":1}");
    });
    var service = new DocumentService(db, gateway, pools);
    var row = service.upload(
      owner,
      new org.springframework.mock.web.MockMultipartFile(
        "file",
        "discard.txt",
        "text/plain",
        "revenue".getBytes()
      ),
      DocumentService.Scope.TASK
    );
    long id = Support.id(row);
    try {
      assertTrue(entered.await(5, java.util.concurrent.TimeUnit.SECONDS));
      service.discard(owner, id);
    } finally {
      release.countDown();
    }
    verify(gateway, timeout(5000).times(2)).rag(eq("/delete"), any());
    assertEquals("DISCARDED", db.document(id, owner).get("status"));
    assertFalse(
      java.nio.file.Files.exists(
        java.nio.file.Path.of(db.document(id, owner).get("path").toString())
      )
    );
  }
}
