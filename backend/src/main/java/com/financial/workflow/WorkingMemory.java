package com.financial.workflow;

import java.util.*;

public final class WorkingMemory {

  private WorkingMemory() {}

  public static boolean compact(
    List<Map<String, Object>> messages,
    int budget
  ) {
    boolean changed = false;
    while (Support.json(messages).length() > budget && messages.size() > 4) {
      int next = 3;
      while (
        next < messages.size() && "tool".equals(messages.get(next).get("role"))
      ) next++;
      if (next >= messages.size()) break;
      messages.subList(2, next).clear();
      changed = true;
    }
    // The most recent assistant call + all its tool results always remain paired.
    if (Support.json(messages).length() > budget) {
      long count = messages
        .stream()
        .filter(m -> "tool".equals(m.get("role")))
        .count();
      int nonToolLength = Support.json(
        messages
          .stream()
          .filter(m -> !"tool".equals(m.get("role")))
          .toList()
      ).length();
      int allowance = count == 0
        ? 0
        : (budget - nonToolLength) / (int) count - 180;
      if (allowance < 256) throw new IllegalStateException(
        "单轮调用参数超出上下文预算"
      );
      for (int i = 2; i < messages.size(); i++) {
        var message = messages.get(i);
        if (
          "tool".equals(message.get("role")) &&
          message.get("content") instanceof String text &&
          text.length() > allowance
        ) {
          message.put(
            "content",
            text.substring(0, allowance) +
              "\n[内容压缩，完整结果保存在执行记录；可用 read 工具读取指定证据]"
          );
          changed = true;
        }
      }
    }
    if (
      Support.json(messages).length() > budget
    ) throw new IllegalStateException("上下文超过字符预算");
    return changed;
  }
}
