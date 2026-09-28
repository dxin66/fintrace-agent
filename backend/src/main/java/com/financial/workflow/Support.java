package com.financial.workflow;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.*;
import java.util.*;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

public final class Support {

  public static final ObjectMapper JSON =
    new ObjectMapper().findAndRegisterModules();

  private Support() {}

  public static String json(Object value) {
    try {
      return JSON.writeValueAsString(value);
    } catch (Exception e) {
      throw new IllegalStateException("JSON serialization failed", e);
    }
  }

  public static JsonNode node(String value) {
    try {
      return JSON.readTree(value);
    } catch (Exception e) {
      throw bad("Invalid JSON");
    }
  }

  public static Map<String, Object> map(String value) {
    try {
      return JSON.readValue(value, new TypeReference<>() {});
    } catch (Exception e) {
      throw bad("Invalid JSON object");
    }
  }

  public static long id(Map<String, Object> row) {
    return ((Number) row.get("id")).longValue();
  }

  public static ResponseStatusException bad(String message) {
    return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
  }

  public static Map<String, Object> require(Map<String, Object> row) {
    if (row == null) throw new ResponseStatusException(
      HttpStatus.NOT_FOUND,
      "资源不存在或无权访问"
    );
    return row;
  }

  public static String error(Throwable e) {
    while (
      e.getCause() != null &&
      (e instanceof java.util.concurrent.ExecutionException ||
        e instanceof java.util.concurrent.CompletionException)
    ) e = e.getCause();
    return e.getMessage() == null
      ? e.getClass().getSimpleName()
      : e.getMessage();
  }
}
