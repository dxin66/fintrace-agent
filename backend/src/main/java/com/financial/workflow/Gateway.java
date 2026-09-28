package com.financial.workflow;

import com.fasterxml.jackson.databind.JsonNode;
import java.net.*;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import org.springframework.stereotype.Component;

@Component
public class Gateway {

  private final HttpClient http = HttpClient.newBuilder()
    .connectTimeout(Duration.ofSeconds(10))
    .build();

  public JsonNode rag(String path, Object payload) {
    return post(
      "http://127.0.0.1:8081" + path,
      payload,
      Map.of("X-Internal-Token", System.getenv("INTERNAL_TOKEN")),
      path.equals("/index") ? 540 : 75
    );
  }

  public JsonNode chat(
    List<Map<String, Object>> messages,
    List<Map<String, Object>> tools
  ) {
    var payload = new HashMap<String, Object>();
    payload.put("model", System.getenv("LLM_MODEL"));
    payload.put("messages", messages);
    payload.put("temperature", 0.1);
    payload.put("max_tokens", 2400);
    payload.put("enable_thinking", false);
    if (!tools.isEmpty()) payload.put("tools", tools);
    return post(
      System.getenv("LLM_BASE_URL") + "/chat/completions",
      payload,
      Map.of("Authorization", "Bearer " + System.getenv("LLM_API_KEY")),
      90
    );
  }

  private JsonNode post(
    String url,
    Object payload,
    Map<String, String> headers,
    int timeout
  ) {
    try {
      var builder = HttpRequest.newBuilder(URI.create(url))
        .timeout(Duration.ofSeconds(timeout))
        .header("Content-Type", "application/json")
        .POST(HttpRequest.BodyPublishers.ofString(Support.json(payload)));
      headers.forEach(builder::header);
      var response = http.send(
        builder.build(),
        HttpResponse.BodyHandlers.ofString()
      );
      if (response.statusCode() / 100 != 2) throw new IllegalStateException(
        (url.startsWith("http://127.0.0.1") ? "文档检索服务" : "模型服务") +
          "返回 HTTP " +
          response.statusCode()
      );
      return Support.node(response.body());
    } catch (InterruptedException e) {
      Thread.currentThread().interrupt();
      throw new java.util.concurrent.CancellationException("调用已取消");
    } catch (java.io.IOException e) {
      throw new IllegalStateException("外部调用失败或超时", e);
    }
  }
}
