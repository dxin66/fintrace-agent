package com.financial.workflow;

import java.io.*;
import java.nio.file.*;
import java.util.*;
import org.springframework.core.io.*;
import org.springframework.http.*;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@Service
public class DocumentService {

  public enum Scope {
    LIBRARY,
    TASK,
  }

  final DataMapper db;
  final Gateway gateway;
  final Pools pools;
  final Path root = Path.of(System.getenv("APP_ROOT"));

  public DocumentService(DataMapper db, Gateway gateway, Pools pools) {
    this.db = db;
    this.gateway = gateway;
    this.pools = pools;
  }

  public Map<String, Object> upload(long owner, MultipartFile file, Scope scope)
    throws IOException {
    return store(
      owner,
      file.getOriginalFilename(),
      file.getInputStream(),
      scope
    );
  }

  Map<String, Object> store(long owner, String filename, InputStream stream)
    throws IOException {
    return store(owner, filename, stream, Scope.LIBRARY);
  }

  Map<String, Object> store(
    long owner,
    String filename,
    InputStream stream,
    Scope scope
  ) throws IOException {
    if (filename == null) throw Support.bad("文件名缺失");
    filename = Path.of(filename).getFileName().toString();
    if (filename.length() > 240) throw Support.bad("文件名过长");
    String suffix = filename
      .substring(filename.lastIndexOf('.') + 1)
      .toLowerCase(Locale.ROOT);
    if (
      !Set.of("pdf", "html", "htm", "txt", "png", "jpg", "jpeg").contains(
        suffix
      )
    ) throw Support.bad("仅支持 PDF、HTML、TXT、PNG、JPG");
    var folder = root.resolve(".runtime/uploads");
    Files.createDirectories(folder);
    var target = folder.resolve(UUID.randomUUID() + "." + suffix);
    try (stream) {
      Files.copy(stream, target);
    }
    if (Files.size(target) == 0 || Files.size(target) > 35L * 1024 * 1024) {
      Files.delete(target);
      throw Support.bad("文件为空或超过 35 MB");
    }
    var row = new HashMap<String, Object>();
    row.put("owner_id", owner);
    row.put("storage_scope", scope.name());
    row.put("filename", filename);
    row.put("path", target.toString());
    row.put(
      "mime_type",
      switch (suffix) {
        case "pdf" -> "application/pdf";
        case "png" -> "image/png";
        case "jpg", "jpeg" -> "image/jpeg";
        default -> "text/plain;charset=UTF-8";
      }
    );
    try {
      db.insertDocument(row);
    } catch (RuntimeException e) {
      Files.deleteIfExists(target);
      throw e;
    }
    long id = Support.id(row);
    try {
      pools.index.execute(() -> {
        try {
          if ("DISCARDED".equals(db.document(id, owner).get("status"))) return;
          var answer = gateway.rag(
            "/index",
            Map.of(
              "document_id",
              id,
              "owner_id",
              owner,
              "filename",
              row.get("filename"),
              "path",
              target.toString()
            )
          );
          db.indexStatus(id, "READY", answer.path("chunks").asInt(), null);
        } catch (Exception e) {
          db.indexStatus(id, "FAILED", 0, Support.error(e));
        } finally {
          if ("DISCARDED".equals(db.document(id, owner).get("status"))) {
            try {
              erase(owner, id, target);
            } catch (Exception e) {
              org.slf4j.LoggerFactory.getLogger(DocumentService.class).warn(
                "附件清理失败，文档 ID {}",
                id
              );
            }
          }
        }
      });
    } catch (java.util.concurrent.RejectedExecutionException e) {
      db.indexStatus(id, "FAILED", 0, "文档索引队列已满，请稍后重新上传");
      throw new ResponseStatusException(
        HttpStatus.TOO_MANY_REQUESTS,
        "文档索引队列已满"
      );
    }
    return publicDocument(Support.require(db.document(id, owner)));
  }

  public Map<String, Object> get(long owner, long id) {
    var row = Support.require(db.document(id, owner));
    if (
      "DISCARDED".equals(row.get("status"))
    ) throw new ResponseStatusException(HttpStatus.NOT_FOUND, "附件已移除");
    return row;
  }

  public void discard(long owner, long id) throws Exception {
    var row = Support.require(db.document(id, owner));
    if (db.discardDocument(id, owner) != 1) throw new ResponseStatusException(
      HttpStatus.CONFLICT,
      "仅可移除尚未提交的本次任务附件"
    );
    erase(owner, id, Path.of(row.get("path").toString()));
  }

  private void erase(long owner, long id, Path path) throws Exception {
    gateway.rag("/delete", Map.of("owner_id", owner, "document_id", id));
    Files.deleteIfExists(path);
  }

  public Map<String, Object> publicDocument(Map<String, Object> row) {
    var result = new HashMap<>(row);
    result.remove("path");
    result.remove("owner_id");
    return result;
  }

  public ResponseEntity<Resource> source(long owner, long id)
    throws IOException {
    var row = get(owner, id);
    var file = Path.of(row.get("path").toString());
    if (
      (row.get("mime_type").toString().equals("application/pdf") ||
        row.get("mime_type").toString().startsWith("image/"))
    ) return ResponseEntity.ok()
      .header("Content-Disposition", "inline")
      .contentType(MediaType.parseMediaType(row.get("mime_type").toString()))
      .body(new FileSystemResource(file));
    if (!"READY".equals(row.get("status"))) throw new ResponseStatusException(
      HttpStatus.CONFLICT,
      "文档索引尚未完成"
    );
    var parsed = gateway.rag(
      "/source",
      Map.of("owner_id", owner, "document_id", id)
    );
    StringBuilder html = new StringBuilder(
      "<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>文档原文</title><style>body{max-width:960px;margin:40px auto;font-family:system-ui;line-height:1.9;padding:20px}pre{white-space:pre-wrap}section{border-top:1px solid #ddd;padding:20px 0}section:target{background:#fff8d9}h2{font-size:14px;color:#64796f}</style><body>"
    );
    html
      .append("<h1>")
      .append(
        org.springframework.web.util.HtmlUtils.htmlEscape(
          row.get("filename").toString()
        )
      )
      .append("</h1>");
    for (var chunk : parsed.path("chunks")) {
      html
        .append("<section id='chunk-")
        .append(java.util.UUID.fromString(chunk.path("id").asText()))
        .append("'><h2>")
        .append(
          org.springframework.web.util.HtmlUtils.htmlEscape(
            chunk.path("anchor").asText()
          )
        )
        .append("</h2><pre>")
        .append(
          org.springframework.web.util.HtmlUtils.htmlEscape(
            chunk.path("text").asText()
          )
        )
        .append("</pre></section>");
    }
    html.append("</body></html>");
    return ResponseEntity.ok()
      .header(
        "Content-Security-Policy",
        "sandbox; default-src 'none'; style-src 'unsafe-inline'"
      )
      .contentType(MediaType.parseMediaType("text/html;charset=UTF-8"))
      .body(
        new ByteArrayResource(
          html.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8)
        )
      );
  }

  public List<Map<String, Object>> samples(long owner) throws IOException {
    List<Map<String, Object>> result = new ArrayList<>();
    try (var paths = Files.list(root.resolve("samples"))) {
      for (var path : paths.filter(Files::isRegularFile).sorted().toList()) {
        if (path.getFileName().toString().equals("README.md")) continue;
        result.add(
          store(
            owner,
            path.getFileName().toString(),
            Files.newInputStream(path)
          )
        );
      }
    }
    return result;
  }
}
