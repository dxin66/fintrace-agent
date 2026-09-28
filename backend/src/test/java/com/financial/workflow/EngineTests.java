package com.financial.workflow;

import static org.junit.jupiter.api.Assertions.*;

import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.*;

class EngineTests {

  @Test
  void decimalCalculationAvoidsBinaryRounding() {
    assertEquals(
      "0.3",
      Calculator.calculate("add", "0.1", "0.2", "亿元").get("result")
    );
  }

  @Test
  void growthUsesPriorYearDenominator() {
    assertEquals(
      "20",
      Calculator.calculate("growth_percent", "120", "100", "%").get("result")
    );
  }

  @Test
  void zeroDenominatorRejected() {
    assertThrows(ArithmeticException.class, () ->
      Calculator.calculate("divide", "2", "0", "倍")
    );
  }

  @Test
  void unknownOperationRejected() {
    assertThrows(RuntimeException.class, () ->
      Calculator.calculate("eval", "2", "2", "元")
    );
  }

  @Test
  void extremeNumberRejected() {
    assertThrows(RuntimeException.class, () ->
      Calculator.calculate("add", "1e100", "2", "元")
    );
  }

  @Test
  void remainingOperations() {
    assertEquals(
      "1",
      Calculator.calculate("subtract", "3", "2", "元").get("result")
    );
    assertEquals(
      "6",
      Calculator.calculate("multiply", "3", "2", "元").get("result")
    );
    assertEquals(
      "1.5",
      Calculator.calculate("divide", "3", "2", "元").get("result")
    );
  }

  @Test
  void finalRequiresActualToolAndNonemptyAnswer() {
    assertThrows(IllegalStateException.class, () ->
      AgentEngine.validateFinal("", true, Map.of(), List.of(1L))
    );
    assertThrows(IllegalStateException.class, () ->
      AgentEngine.validateFinal("证据不足", false, Map.of(), List.of(1L))
    );
  }

  @Test
  void fabricatedCitationAndNoCitationRejected() {
    assertThrows(IllegalStateException.class, () ->
      AgentEngine.validateFinal(
        "收入 100 [E:fake]",
        true,
        Map.of(),
        List.of(1L)
      )
    );
    assertThrows(IllegalStateException.class, () ->
      AgentEngine.validateFinal("收入 100", true, Map.of(), List.of(1L))
    );
  }

  @Test
  void evidenceScopeAndInsufficiency() {
    var evidence = Map.of("real", Support.node("{\"document_id\":1}"));
    AgentEngine.validateFinal("收入 [E:real]", true, evidence, List.of(1L));
    assertThrows(IllegalStateException.class, () ->
      AgentEngine.validateFinal("收入 [E:real]", true, evidence, List.of(2L))
    );
    AgentEngine.validateFinal(
      "证据不足，无法核验",
      true,
      Map.of(),
      List.of(1L)
    );
  }

  @Test
  void childCannotDelegate() {
    assertEquals(3, AgentEngine.definitions(false).size());
    assertEquals(4, AgentEngine.definitions(true).size());
  }

  @Test
  void compactionKeepsCallResultPairs() {
    List<Map<String, Object>> memory = new ArrayList<>();
    memory.add(new HashMap<>(Map.of("role", "system", "content", "system")));
    memory.add(new HashMap<>(Map.of("role", "user", "content", "question")));
    for (int i = 0; i < 3; i++) {
      memory.add(
        new HashMap<>(
          Map.of(
            "role",
            "assistant",
            "tool_calls",
            List.of(Map.of("id", "call" + i))
          )
        )
      );
      memory.add(
        new HashMap<>(
          Map.of(
            "role",
            "tool",
            "tool_call_id",
            "call" + i,
            "content",
            "x".repeat(5000)
          )
        )
      );
    }
    assertTrue(WorkingMemory.compact(memory, 6000));
    assertEquals(4, memory.size());
    assertEquals("call2", memory.get(3).get("tool_call_id"));
    assertFalse(WorkingMemory.compact(memory, 9000));
  }

  @Test
  void oversizedLatestResultIsExplicitlyTruncated() {
    List<Map<String, Object>> m = new ArrayList<>();
    m.add(new HashMap<>(Map.of("role", "system", "content", "s")));
    m.add(new HashMap<>(Map.of("role", "user", "content", "u")));
    m.add(
      new HashMap<>(
        Map.of("role", "assistant", "tool_calls", List.of(Map.of("id", "c")))
      )
    );
    m.add(
      new HashMap<>(
        Map.of(
          "role",
          "tool",
          "tool_call_id",
          "c",
          "content",
          "a".repeat(30000)
        )
      )
    );
    assertTrue(WorkingMemory.compact(m, 10000));
    assertEquals(4, m.size());
    assertTrue(m.get(3).get("content").toString().contains("内容压缩"));
  }

  @Test
  void cancellationInterruptsSubmittedWork() throws Exception {
    var executor = Pools.pool("test", 1, 1);
    var control = new Pools.Control();
    var entered = new CountDownLatch(1);
    var interrupted = new CountDownLatch(1);
    try {
      var future = Pools.async(executor, control, () -> {
        entered.countDown();
        try {
          Thread.sleep(10000);
        } catch (InterruptedException e) {
          interrupted.countDown();
          Thread.currentThread().interrupt();
        }
        return true;
      });
      assertTrue(entered.await(2, TimeUnit.SECONDS));
      var queued = Pools.async(executor, control, () -> true);
      assertEquals(1, executor.getQueue().size());
      control.cancel();
      assertEquals(0, executor.getQueue().size());
      assertThrows(CancellationException.class, queued::join);
      assertTrue(interrupted.await(2, TimeUnit.SECONDS));
      assertThrows(CancellationException.class, future::join);
      assertThrows(CancellationException.class, control::check);
    } finally {
      executor.shutdownNow();
    }
  }

  @Test
  void boundedQueueRejectsAdmission() throws Exception {
    var executor = Pools.pool("test", 1, 1);
    var gate = new CountDownLatch(1);
    var entered = new CountDownLatch(1);
    try {
      executor.execute(() -> {
        entered.countDown();
        try {
          gate.await();
        } catch (InterruptedException e) {
          Thread.currentThread().interrupt();
        }
      });
      assertTrue(entered.await(1, TimeUnit.SECONDS));
      executor.execute(() -> {});
      assertThrows(RejectedExecutionException.class, () ->
        executor.execute(() -> {})
      );
    } finally {
      gate.countDown();
      executor.shutdownNow();
    }
  }

  @Test
  void independentToolsActuallyOverlap() throws Exception {
    var executor = Pools.pool("parallel-test", 2, 2);
    var control = new Pools.Control();
    var both = new CountDownLatch(2);
    try {
      var left = Pools.async(executor, control, () -> awaitPeer(both));
      var right = Pools.async(executor, control, () -> awaitPeer(both));
      assertEquals(
        2,
        left.get(3, TimeUnit.SECONDS) + right.get(3, TimeUnit.SECONDS)
      );
    } finally {
      executor.shutdownNow();
    }
  }

  static int awaitPeer(CountDownLatch both) {
    both.countDown();
    try {
      if (!both.await(1, TimeUnit.SECONDS)) throw new IllegalStateException(
        "did not overlap"
      );
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new RuntimeException(e);
    }
    return 1;
  }
}
