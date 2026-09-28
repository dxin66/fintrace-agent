package com.financial.workflow;

import java.util.*;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

@Mapper
public interface DataMapper {
  Map<String, Object> user(String username);
  void insertUser(Map<String, Object> row);
  void insertDocument(Map<String, Object> row);
  int claimDocument(
    @Param("id") long id,
    @Param("owner") long owner,
    @Param("task") long task
  );
  int discardDocument(@Param("id") long id, @Param("owner") long owner);
  List<Map<String, Object>> documents(long owner);
  Map<String, Object> document(
    @Param("id") long id,
    @Param("owner") long owner
  );
  void indexStatus(
    @Param("id") long id,
    @Param("status") String status,
    @Param("count") int count,
    @Param("error") String error
  );
  void insertSession(Map<String, Object> row);
  List<Map<String, Object>> sessions(long owner);
  Map<String, Object> session(@Param("id") long id, @Param("owner") long owner);
  void insertTask(Map<String, Object> row);
  Map<String, Object> task(@Param("id") long id, @Param("owner") long owner);
  Map<String, Object> idempotent(
    @Param("owner") long owner,
    @Param("key") String key
  );
  List<Map<String, Object>> tasks(
    @Param("owner") long owner,
    @Param("offset") int offset
  );
  int transition(
    @Param("id") long id,
    @Param("status") String status,
    @Param("result") String result,
    @Param("error") String error
  );
  int startTask(long id);
  void interruptTasks();
  void interruptRuns();
  void interruptTools();
  void interruptDocuments();
  void insertRun(Map<String, Object> row);
  void finishRun(
    @Param("id") String id,
    @Param("status") String status,
    @Param("result") String result,
    @Param("steps") int steps
  );
  void tokens(
    @Param("id") String id,
    @Param("prompt") int prompt,
    @Param("completion") int completion
  );
  List<Map<String, Object>> runs(long task);
  void insertTool(Map<String, Object> row);
  void finishTool(
    @Param("id") String id,
    @Param("status") String status,
    @Param("result") String result,
    @Param("duration") long duration
  );
  List<Map<String, Object>> tools(long task);
  void evidence(
    @Param("task") long task,
    @Param("chunk") String chunk,
    @Param("document") long document,
    @Param("payload") String payload
  );
  List<Map<String, Object>> evidenceList(long task);
  void event(
    @Param("task") long task,
    @Param("type") String type,
    @Param("payload") String payload
  );
  List<Map<String, Object>> events(
    @Param("task") long task,
    @Param("after") long after
  );
  int reviewState(
    @Param("task") long task,
    @Param("owner") long owner,
    @Param("version") int version,
    @Param("decision") String decision
  );
  void insertReview(
    @Param("task") long task,
    @Param("owner") long owner,
    @Param("decision") String decision,
    @Param("note") String note
  );
  List<Map<String, Object>> reviews(long task);
}
