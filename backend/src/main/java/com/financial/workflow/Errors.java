package com.financial.workflow;

import java.util.Map;
import org.slf4j.*;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.*;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MaxUploadSizeExceededException;
import org.springframework.web.server.ResponseStatusException;

@RestControllerAdvice
public class Errors {

  private static final Logger LOG = LoggerFactory.getLogger(Errors.class);

  @ExceptionHandler(ResponseStatusException.class)
  ResponseEntity<?> status(ResponseStatusException e) {
    return ResponseEntity.status(e.getStatusCode()).body(
      Map.of("message", e.getReason() == null ? "请求失败" : e.getReason())
    );
  }

  @ExceptionHandler(DuplicateKeyException.class)
  ResponseEntity<?> conflict() {
    return ResponseEntity.status(409).body(
      Map.of("message", "记录已存在，请勿重复创建")
    );
  }

  @ExceptionHandler(
    {
      MethodArgumentNotValidException.class,
      IllegalArgumentException.class,
      org.springframework.http.converter.HttpMessageNotReadableException.class,
      org.springframework.web.method.annotation
        .MethodArgumentTypeMismatchException.class,
      org.springframework.web.bind
        .MissingServletRequestParameterException.class,
    }
  )
  ResponseEntity<?> invalid() {
    return ResponseEntity.badRequest().body(
      Map.of("message", "请求参数格式不正确")
    );
  }

  @ExceptionHandler(MaxUploadSizeExceededException.class)
  ResponseEntity<?> tooLarge() {
    return ResponseEntity.status(413).body(
      Map.of("message", "单个文件不能超过 35 MB")
    );
  }

  @ExceptionHandler(Exception.class)
  ResponseEntity<?> unknown(Exception e) {
    LOG.error("Request failed: {}", e.getClass().getSimpleName());
    return ResponseEntity.internalServerError().body(
      Map.of("message", "服务处理失败，请查看任务状态或服务日志")
    );
  }
}
